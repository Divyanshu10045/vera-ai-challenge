import hashlib
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any


def fingerprint(merchant_id: str, body: str) -> str:
    digest = hashlib.sha256(f"{merchant_id}|{body.strip().lower()}".encode("utf-8")).hexdigest()
    return digest[:16]


@dataclass
class Conversation:
    conversation_id: str
    merchant_id: str = ""
    customer_id: str = ""
    channel: str = "merchant"
    last_outbound: str = ""
    last_intent: str = ""
    turns: int = 0
    unanswered_nudges: int = 0
    awaiting_reply_since: float = 0.0
    resume_at: float = 0.0
    finished: bool = False
    history: list[tuple[str, str, str]] = field(default_factory=list)


class ReplyState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.conversations: dict[str, Conversation] = {}
        self.auto_replies: dict[str, int] = {}
        self.opt_outs: set[str] = set()
        self.declines: dict[str, str] = {}
        self.pending_asks: dict[str, dict[str, Any]] = {}
        self.decision_log: list[dict[str, Any]] = []
        self.sent_bodies: dict[str, str] = {}

    def conversation(self, conversation_id: str) -> Conversation:
        with self._lock:
            existing = self.conversations.get(conversation_id)
            if existing is None:
                existing = Conversation(conversation_id=conversation_id)
                self.conversations[conversation_id] = existing
            return existing

    def note_auto_reply(self, merchant_id: str, body: str) -> int:
        key = fingerprint(merchant_id, body)
        with self._lock:
            self.auto_replies[key] = self.auto_replies.get(key, 0) + 1
            return self.auto_replies[key]

    def auto_reply_count(self, merchant_id: str, body: str) -> int:
        return self.auto_replies.get(fingerprint(merchant_id, body), 0)

    def clear_auto_reply(self, merchant_id: str, body: str) -> None:
        with self._lock:
            self.auto_replies.pop(fingerprint(merchant_id, body), None)

    def is_opted_out(self, merchant_id: str) -> bool:
        return merchant_id in self.opt_outs

    def opt_out(self, merchant_id: str, reason: str) -> None:
        with self._lock:
            self.opt_outs.add(merchant_id)
            for conv in self.conversations.values():
                if conv.merchant_id == merchant_id:
                    conv.finished = True

    def note_decline(self, merchant_id: str, intent: str) -> None:
        with self._lock:
            self.declines[merchant_id] = intent
            for conv in self.conversations.values():
                if conv.merchant_id == merchant_id:
                    conv.finished = True

    def declined(self, merchant_id: str) -> str | None:
        return self.declines.get(merchant_id)

    def remember_ask(self, conversation_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self.pending_asks[conversation_id] = payload

    def take_ask(self, conversation_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self.pending_asks.pop(conversation_id, None)

    def cooldown_remaining(self, conversation_id: str) -> float:
        conv = self.conversations.get(conversation_id)
        if conv is None:
            return 0.0
        return max(0.0, conv.resume_at - time.time())

    def in_cooldown(self, merchant_id: str) -> bool:
        now = time.time()
        with self._lock:
            for conv in self.conversations.values():
                if conv.merchant_id == merchant_id and conv.resume_at > now:
                    return True
        return False

    def log(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self.decision_log.append({"at": round(time.time(), 3), **entry})
            if len(self.decision_log) > 1000:
                del self.decision_log[:500]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "conversations": len(self.conversations),
                "auto_reply_threads": len(self.auto_replies),
                "opt_outs": len(self.opt_outs),
                "declines": len(self.declines),
                "decisions": len(self.decision_log),
            }
