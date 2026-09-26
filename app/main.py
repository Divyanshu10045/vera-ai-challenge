import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import llm as llm_mod
from . import normalize, reply as reply_mod, strategies, validate
from .config import SETTINGS
from .context_store import ContextStore, utc_now_iso
from .evidence import build_bundle
from .plan import ActionPlan
from .render import voice_for
from .state import ReplyState

app = FastAPI(title="Vera Engagement Composer", version=SETTINGS.version)

store = ContextStore()
reply_state = ReplyState()
STARTED_AT = utc_now_iso()
counters: dict[str, int] = {"ticks": 0, "replies": 0, "actions": 0, "suppressed": 0, "llm_calls": 0}


@app.get("/v1/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse(
        {
            "status": "healthy",
            "service": "vera-engagement-composer",
            "version": SETTINGS.version,
            "started_at": STARTED_AT,
            "checked_at": utc_now_iso(),
            "contexts": store.counts(),
            "conversation": reply_state.snapshot(),
        }
    )


@app.get("/v1/metadata")
async def metadata() -> JSONResponse:
    return JSONResponse(
        {
            "team_name": SETTINGS.team_name,
            "team_members": SETTINGS.team_members,
            "contact_email": SETTINGS.contact_email,
            "model": SETTINGS.model_label,
            "approach": SETTINGS.approach,
            "version": SETTINGS.version,
        }
    )


@app.post("/v1/context")
async def push_context(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"accepted": False, "reason": "invalid_json", "details": "body must be JSON"}, 400)
    if not isinstance(body, dict):
        return JSONResponse({"accepted": False, "reason": "invalid_body", "details": "expected an object"}, 400)

    scope = body.get("scope")
    context_id = body.get("context_id")
    version = body.get("version")
    payload = body.get("payload", body)
    delivered_at = str(body.get("delivered_at") or utc_now_iso())
    status, response = store.put(scope, context_id, version, payload, delivered_at)
    return JSONResponse(response, status)


@app.post("/v1/tick")
async def tick(request: Request) -> JSONResponse:
    started = time.time()
    counters["ticks"] += 1
    try:
        body = await request.json()
    except Exception:
        body = {}
    requested: list[str] = []
    if isinstance(body, dict):
        raw = body.get("trigger_ids") or body.get("context_ids") or []
        if isinstance(raw, list):
            requested = [str(t) for t in raw if isinstance(t, (str, int))]

    now = datetime.now(timezone.utc)
    actions: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    seen_merchants: dict[str, int] = {}

    candidates = [store.record("trigger", tid) for tid in requested] if requested else []
    candidates = [c for c in candidates if c is not None]
    if not candidates:
        candidates = list(store.iter_scope("trigger"))
        candidates.sort(key=lambda r: (-r.payload.get("urgency", 0) if isinstance(r.payload.get("urgency"), int) else 0, r.context_id))

    for record in candidates:
        if len(actions) >= SETTINGS.max_actions_per_tick:
            break
        if time.time() - started > SETTINGS.tick_budget_seconds:
            decisions.append({"trigger_id": record.context_id, "decision": "deferred", "reason": "tick time budget reached"})
            continue
        trigger = record.payload
        merchant_id = normalize.trigger_merchant_id(trigger) or str(
            trigger.get("merchant_id") or trigger.get("merchant_ref") or ""
        )
        if not merchant_id:
            decisions.append({"trigger_id": record.context_id, "decision": "skipped", "reason": "trigger has no merchant reference"})
            continue
        if reply_state.is_opted_out(merchant_id) or reply_state.declined(merchant_id):
            decisions.append({"trigger_id": record.context_id, "decision": "suppressed", "reason": "merchant opted out or declined"})
            counters["suppressed"] += 1
            continue
        if reply_state.in_cooldown(merchant_id):
            decisions.append({"trigger_id": record.context_id, "decision": "deferred", "reason": "merchant asked for time"})
            continue
        if seen_merchants.get(merchant_id, 0) >= SETTINGS.per_merchant_tick_cap:
            continue

        merchant = store.get("merchant", merchant_id) or {}
        customer_id = normalize.trigger_customer_id(trigger)
        customer = store.get("customer", customer_id) if customer_id else None
        category = store.category_for_merchant(merchant) if merchant else None
        if category is None and isinstance(trigger.get("category_slug"), str):
            category = store.get("category", trigger["category_slug"])
        if category is None:
            category = store.get("category", normalize.merchant_category(merchant)) or None

        if not merchant:
            decisions.append({"trigger_id": record.context_id, "decision": "deferred", "reason": "merchant context not pushed yet"})
            continue

        plan = strategies.plan_for_trigger(trigger, merchant, customer, category, now)
        bundle = build_bundle(category, merchant, trigger, customer, now)
        voice = voice_for(category, merchant)
        plan = validate.finalise(plan, bundle, merchant, customer)

        if plan.suppressed:
            counters["suppressed"] += 1
            decisions.append(
                {
                    "trigger_id": record.context_id,
                    "decision": "suppressed",
                    "reason": plan.suppress_reason or "held back",
                }
            )
            continue

        if SETTINGS.llm_enabled and not SETTINGS.deterministic_only:
            counters["llm_calls"] += 1
            improved = llm_mod.realise(plan, bundle, SETTINGS, voice.formality)
            if improved is not None:
                plan = improved

        action = plan.to_action()
        action.setdefault("channel", plan.channel)
        action["trigger_id"] = record.context_id
        if plan.context_ids.get("merchant_id"):
            action["merchant_id"] = plan.context_ids["merchant_id"]
        elif merchant_id:
            action["merchant_id"] = merchant_id
        if customer_id:
            action["customer_id"] = customer_id
        action["cta"] = _cta_of(plan.body)
        action["send_as"] = "vera"
        actions.append(action)
        seen_merchants[merchant_id] = seen_merchants.get(merchant_id, 0) + 1
        counters["actions"] += 1
        reply_state.remember_ask(
            merchant_id,
            {"trigger": trigger, "merchant_id": merchant_id, "customer_id": customer_id or ""},
        )
        decisions.append(
            {
                "trigger_id": record.context_id,
                "decision": "sent",
                "shape": plan.shape,
                "intent": (plan.intents or ["FYI"])[0],
                "context_version": record.version,
            }
        )

    return JSONResponse(
        {
            "actions": actions,
            "decisions": decisions,
            "elapsed_ms": int((time.time() - started) * 1000),
        }
    )


@app.post("/v1/reply")
async def reply(request: Request) -> JSONResponse:
    counters["replies"] += 1
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"reply": {"kind": "error", "body": ""}, "action": "end"}, 400)
    if not isinstance(body, dict):
        return JSONResponse({"reply": {"kind": "error", "body": ""}, "action": "end"}, 400)

    outcome = reply_mod.decide(body, reply_state, SETTINGS, _build_next)
    if outcome.cooldown_seconds:
        conversation_id = str(body.get("conversation_id") or "")
        conv = reply_state.conversation(conversation_id)
        conv.resume_at = time.time() + outcome.cooldown_seconds
    if outcome.action == "send" and outcome.body:
        conversation_id = str(body.get("conversation_id") or "")
        conv = reply_state.conversation(conversation_id)
        conv.last_outbound = outcome.body
        conv.awaiting_reply_since = time.time()
        conv.unanswered_nudges = 0
        reply_state.sent_bodies[conversation_id] = outcome.body
    if outcome.should_end:
        conversation_id = str(body.get("conversation_id") or "")
        reply_state.conversation(conversation_id).finished = True
    reply_state.log(
        {
            "conversation_id": body.get("conversation_id"),
            "from_role": body.get("from_role"),
            "kind": outcome.kind,
            "action": outcome.action,
        }
    )
    return JSONResponse(outcome.to_payload())


@app.post("/v1/reset")
async def reset() -> JSONResponse:
    store.clear()
    reply_state.__init__()
    for key in counters:
        counters[key] = 0
    return JSONResponse({"reset": True, "at": utc_now_iso()})


def _cta_of(body: str) -> str:
    for sentence in reversed([s for s in body.replace("!", ".").replace("?", ".").split(".") if s.strip()]):
        lowered = sentence.lower()
        if any(
            token in lowered
            for token in ("want me to", "want i to", "shall i", "reply to confirm", "tell me", "say the word", "want a", "want the")
        ):
            return sentence.strip()[:120]
    return "none"


def _build_next(payload: dict[str, Any], ask: dict[str, Any] | None, intent: str) -> ActionPlan | None:
    if not ask:
        return None
    now = datetime.now(timezone.utc)
    trigger = ask.get("trigger") or {}
    merchant = store.get("merchant", ask.get("merchant_id") or "") or {}
    customer = store.get("customer", ask.get("customer_id") or "") if ask.get("customer_id") else None
    category = store.category_for_merchant(merchant) if merchant else None
    if not trigger or not merchant:
        return None
    plan = strategies.plan_for_trigger(trigger, merchant, customer, category, now)
    plan.rationale = strategies._clip(
        f"{plan.rationale} Sent as the next step after the merchant's {intent}, not as a fresh pitch."
    )
    return plan
