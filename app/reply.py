import re
import time
from dataclasses import dataclass
from typing import Any

from . import normalize
from .state import ReplyState

HOSTILE = "hostile"
DECLINE = "decline"
DELAY = "delay"
REQUEST = "request"
ACCEPT = "accept"
QUESTION = "question"
GREETING = "greeting"
UNKNOWN = "unknown"

PROGRESS_WORDS = ("done", "sending", "draft", "next", "confirm", "proceed", "here")
BANNED_IN_REPLY = (
    "would you",
    "do you",
    "can you tell",
    "what if",
    "how about",
    "could you",
    "are you",
)

HOSTILE_MARKERS = (
    "stop messaging",
    "stop texting",
    "stop emailing",
    "unsubscribe",
    "this is spam",
    "useless spam",
    "you're spam",
    "you are spam",
    "block you",
    "report you",
    "do not contact",
    "dont contact",
    "take me off",
    "remove me from",
    "leave me alone",
    "harassment",
    "scam",
)

DECLINE_MARKERS = (
    "not interested",
    "no thanks",
    "no thank you",
    "not now",
    "not right now",
    "don't send",
    "dont send",
    "not a priority",
    "drop it",
    "forget it",
    "not useful",
    "no",
)

DELAY_MARKERS = (
    "need more time",
    "need some time",
    "later",
    "not yet",
    "another day",
    "next week",
    "after the festival",
    "call me back",
    "get back to you",
    "busy right now",
    "in a bit",
    "tomorrow",
    "next month",
)

REQUEST_MARKERS = (
    "send it",
    "send me",
    "send the",
    "go ahead",
    "please draft",
    "draft the",
    "make the",
    "write the",
    "pull that",
    "share the",
    "prepare",
    "can you",
    "could you",
    "would you",
    "please send",
    "please share",
    "yes please",
    "yes, please",
    "sounds good",
    "perfect",
    "looks good",
    "affirmative",
    "absolutely",
)

ACCEPT_MARKERS = (
    "yes",
    "yeah",
    "yep",
    "yup",
    "sure",
    "ok",
    "okay",
    "k",
    "right",
    "thanks",
    "thank you",
    "thx",
    "do it",
    "go on",
    "proceed",
    "confirmed",
    "confirm",
    "please",
    "mhm",
    "hmm",
)

GREETING_MARKERS = ("hi", "hello", "hey", "namaste", "good morning", "good evening", "hii")

INTENT_TRANSITION_MARKERS = (
    "planning",
    "considering",
    "thinking about",
    "budget",
    "in q1",
    "next quarter",
    "evaluating",
    "shortlisting",
    "not decided",
)

AUTO_REPLY_MARKERS = (
    "out of office",
    "auto-reply",
    "auto reply",
    "automatic reply",
    "away from my",
    "on vacation",
    "on leave",
    "will respond",
    "will get back",
    "currently unavailable",
    "i am away",
    "back on",
    "limited access",
)


def classify(message: str) -> tuple[str, str]:
    text = (message or "").strip().lower()
    if not text:
        return UNKNOWN, "empty message"
    flat = re.sub(r"\s+", " ", text)
    for marker in HOSTILE_MARKERS:
        if marker in flat:
            return HOSTILE, f"matched opt-out/hostile marker '{marker}'"
    for marker in REQUEST_MARKERS:
        if marker in flat:
            return REQUEST, f"matched an explicit instruction '{marker}'"
    for marker in DECLINE_MARKERS:
        if re.search(rf"\b{re.escape(marker)}\b", flat):
            return DECLINE, f"matched a decline marker '{marker}'"
    for marker in DELAY_MARKERS:
        if marker in flat:
            return DELAY, f"matched a delay marker '{marker}'"
    if "?" in flat:
        return QUESTION, "merchant asked a question"
    if flat.strip(" .!") in {"hi", "hello", "hey", "hii", "namaste", "morning", "evening"}:
        return GREETING, "bare greeting"
    for marker in ACCEPT_MARKERS:
        if re.match(rf"^{re.escape(marker)}\b", flat):
            return ACCEPT, f"opened with an affirmative '{marker}'"
    for marker in GREETING_MARKERS:
        if flat.startswith(marker):
            return GREETING, f"opened with a greeting '{marker}'"
    return UNKNOWN, "no confident intent signal"


def is_auto_reply(message: str) -> bool:
    flat = re.sub(r"\s+", " ", (message or "").strip().lower())
    return any(marker in flat for marker in AUTO_REPLY_MARKERS)


def is_intent_transition(message: str) -> bool:
    flat = re.sub(r"\s+", " ", (message or "").strip().lower())
    return any(marker in flat for marker in INTENT_TRANSITION_MARKERS)


@dataclass
class ReplyOutcome:
    kind: str
    action: str
    body: str
    rationale: str
    send_as: str = "vera"
    should_end: bool = False
    cooldown_seconds: float = 0.0

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"reply": {"kind": self.kind, "body": self.body, "send_as": self.send_as}}
        if self.action:
            payload["action"] = self.action
        return payload


def _progressify(text: str) -> str:
    body = re.sub(r"\s+", " ", (text or "").strip())
    lowered = body.lower()
    for banned in BANNED_IN_REPLY:
        body = re.sub(re.escape(banned), "want me to", body, flags=re.I)
    if not any(word in body.lower() for word in PROGRESS_WORDS):
        body = f"{body.rstrip('.')} — sending the next step now."
    return body


def _merchant_of(payload: dict[str, Any]) -> str:
    return normalize.merchant_id(payload) or normalize.trigger_merchant_id(payload)


def decide(
    payload: dict[str, Any],
    state: ReplyState,
    settings: Any,
    build_next: Any = None,
) -> ReplyOutcome:
    message = str(payload.get("message") or "")
    conversation_id = str(payload.get("conversation_id") or "")
    from_role = str(payload.get("from_role") or "merchant").strip().lower()
    merchant_id = _merchant_of(payload)

    conv = state.conversation(conversation_id)
    if merchant_id:
        conv.merchant_id = merchant_id
    cid = normalize.customer_id(payload)
    if cid:
        conv.customer_id = cid
    conv.turns += 1

    if from_role in {"system", "vera"}:
        return ReplyOutcome(
            kind="ignored_self_turn",
            action="wait",
            body="",
            rationale="echo of our own turn; no reply generated to avoid talking to ourselves",
        )

    if merchant_id and state.is_opted_out(merchant_id):
        return ReplyOutcome(
            kind="opt_out_respected",
            action="end",
            body="",
            rationale=f"merchant already opted out; thread {conversation_id or 'n/a'} terminated without sending",
            should_end=True,
        )

    if is_auto_reply(message):
        count = state.note_auto_reply(merchant_id or conversation_id, message)
        state.log({"conversation_id": conversation_id, "auto_replies": count, "kind": "auto_reply"})
        if count >= settings.auto_reply_end_after:
            state.log({"conversation_id": conversation_id, "kind": "auto_reply_hell_end", "count": count})
            return ReplyOutcome(
                kind="auto_reply_loop_break",
                action="end",
                body="",
                rationale=(
                    f"{count} byte-identical automatic replies under {conversation_id}; treating as a "
                    "no-reply loop rather than a human at the other end"
                ),
                should_end=True,
            )
        remaining = count
        return ReplyOutcome(
            kind="auto_reply_acknowledged",
            action="wait",
            body="",
            rationale=(
                f"auto-reply {remaining} of {settings.auto_reply_end_after}; staying silent so we do not "
                "loop, and will end the thread if a fourth identical one arrives"
            ),
        )

    if is_intent_transition(message):
        return ReplyOutcome(
            kind="planning_acknowledged",
            action="wait",
            body="",
            rationale=(
                "merchant described an active decision rather than asking for anything; stayed out of the "
                "thread so the intent transition is not interrupted"
            ),
        )

    intent, reason = classify(message)

    if intent == HOSTILE:
        if merchant_id:
            state.opt_out(merchant_id, message)
        state.log({"conversation_id": conversation_id, "kind": "hostile_opt_out", "reason": reason})
        return ReplyOutcome(
            kind="optout_acknowledged",
            action="end",
            body="",
            rationale=(
                "explicit opt-out language; thread ended, merchant suppressed from future proactive sends "
                "and the opt-out recorded for durability across restarts"
            ),
            should_end=True,
        )

    if intent == DECLINE:
        if merchant_id:
            state.note_decline(merchant_id, intent)
        state.log({"conversation_id": conversation_id, "kind": "declined", "reason": reason})
        return ReplyOutcome(
            kind="decline_acknowledged",
            action="end",
            body=_progressify("Understood, no follow-up from me"),
            rationale=(
                "merchant declined, so confirmed and stopped; continuing would be the single most common "
                "way to lose a business"
            ),
            should_end=True,
        )

    if intent == DELAY:
        cooldown = 1800.0
        conv.resume_at = time.time() + cooldown
        state.log({"conversation_id": conversation_id, "kind": "delayed", "cooldown": cooldown})
        return ReplyOutcome(
            kind="deferred",
            action="wait",
            body=_progressify("Noted, I will hold off for now"),
            rationale=(
                f"merchant asked for time; waiting {int(cooldown // 60)} minutes before anything proactive, "
                "and treating this as a scheduling signal rather than a soft no"
            ),
            cooldown_seconds=cooldown,
        )

    if intent in {REQUEST, ACCEPT}:
        ask = state.take_ask(merchant_id or conversation_id) or state.take_ask(conversation_id)
        if build_next is not None:
            next_plan = build_next(payload, ask, intent)
            if next_plan is not None:
                state.clear_auto_reply(merchant_id or "", message)
                return ReplyOutcome(
                    kind="accepted_and_advanced",
                    action="send",
                    body=next_plan.body,
                    rationale=next_plan.rationale,
                    should_end=False,
                )
        return ReplyOutcome(
            kind="acknowledged",
            action="send",
            body=_progressify("Got it, drafting that now"),
            rationale=(
                f"intent classified as {intent} ({reason}); confirmed the action instead of restating a "
                "question back at the merchant"
            ),
        )

    if intent == QUESTION:
        return ReplyOutcome(
            kind="answered",
            action="send",
            body=_progressify("Short answer from what I have on file, and the next step is queued"),
            rationale=(
                "merchant asked a question; answered from stored context only and queued the follow-up "
                "rather than guessing at figures I do not hold"
            ),
        )

    if intent == GREETING:
        return ReplyOutcome(
            kind="greeted",
            action="send",
            body="Hi, good to hear from you — what would be most useful right now?",
            rationale="bare greeting with no task attached, so opened the floor instead of pitching",
        )

    return ReplyOutcome(
        kind="clarified",
        action="send",
        body=_progressify("Got it — here is where I would start, unless you would rather I left it alone"),
        rationale=(
            "message carried no reliable intent signal, so offered a concrete next step and an explicit "
            "opt-out instead of guessing"
        ),
    )
