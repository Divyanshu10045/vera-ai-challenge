import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

VALID_SCOPES = ("category", "merchant", "customer", "trigger")


@dataclass(frozen=True)
class ContextRecord:
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str

    def age_seconds(self, now: datetime | None = None) -> float:
        reference = now or datetime.now(timezone.utc)
        stamp = _parse_iso(self.delivered_at)
        if stamp is None:
            return 0.0
        return max(0.0, (reference - stamp).total_seconds())


def _parse_iso(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ContextStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str], ContextRecord] = {}
        self._ack_seq = 0
        self.push_audit: list[dict[str, Any]] = []

    def put(
        self, scope: str, context_id: str, version: int, payload: dict[str, Any], delivered_at: str
    ) -> tuple[int, dict[str, Any]]:
        if scope not in VALID_SCOPES:
            return 400, {
                "accepted": False,
                "reason": "invalid_scope",
                "details": f"scope must be one of {list(VALID_SCOPES)}",
            }
        if not isinstance(context_id, str) or not context_id.strip():
            return 400, {"accepted": False, "reason": "invalid_context_id", "details": "context_id required"}
        if not isinstance(version, int) or isinstance(version, bool) or version < 0:
            return 400, {"accepted": False, "reason": "invalid_version", "details": "version must be a non-negative int"}
        if not isinstance(payload, dict):
            return 400, {"accepted": False, "reason": "invalid_payload", "details": "payload must be an object"}

        key = (scope, context_id)
        with self._lock:
            current = self._records.get(key)
            if current is not None and version <= current.version:
                self._audit(scope, context_id, version, "rejected_stale", current.version)
                return 409, {
                    "accepted": False,
                    "reason": "stale_version",
                    "current_version": current.version,
                }
            replaced = current.version if current is not None else None
            self._records[key] = ContextRecord(
                scope=scope,
                context_id=context_id,
                version=version,
                payload=payload,
                delivered_at=delivered_at or utc_now_iso(),
            )
            self._ack_seq += 1
            ack_id = f"ack_{context_id}_v{version}_{self._ack_seq:05d}"
            self._audit(scope, context_id, version, "accepted", replaced)
            return 200, {"accepted": True, "ack_id": ack_id, "stored_at": utc_now_iso()}

    def get(self, scope: str, context_id: str | None) -> dict[str, Any] | None:
        if not context_id:
            return None
        with self._lock:
            record = self._records.get((scope, context_id))
            return record.payload if record else None

    def record(self, scope: str, context_id: str | None) -> ContextRecord | None:
        if not context_id:
            return None
        with self._lock:
            return self._records.get((scope, context_id))

    def version_of(self, scope: str, context_id: str | None) -> int:
        found = self.record(scope, context_id)
        return found.version if found else 0

    def counts(self) -> dict[str, int]:
        tally = {scope: 0 for scope in VALID_SCOPES}
        with self._lock:
            for (scope, _), _ in self._records.items():
                tally[scope] = tally.get(scope, 0) + 1
        return tally

    def ids(self, scope: str) -> list[str]:
        with self._lock:
            return [cid for (sc, cid) in self._records if sc == scope]

    def iter_scope(self, scope: str) -> Iterator[ContextRecord]:
        with self._lock:
            records = [r for (sc, _), r in self._records.items() if sc == scope]
        return iter(records)

    def category_for_merchant(self, merchant: dict[str, Any] | None) -> dict[str, Any] | None:
        if not merchant:
            return None
        slug = merchant.get("category_slug")
        if not slug:
            return self.get("category", slug)
        return self.get("category", slug)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self.push_audit.clear()

    def _audit(self, scope: str, context_id: str, version: int, outcome: str, replaced: int | None) -> None:
        self.push_audit.append(
            {
                "at": utc_now_iso(),
                "scope": scope,
                "context_id": context_id,
                "version": version,
                "outcome": outcome,
                "replaced_version": replaced,
            }
        )
        if len(self.push_audit) > 2000:
            del self.push_audit[:1000]
