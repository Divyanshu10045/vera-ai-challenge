from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActionPlan:
    channel: str
    kind: str
    shape: str
    body: str
    rationale: str
    intents: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    context_ids: dict[str, str] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    suppressed: bool = False
    suppress_reason: str | None = None

    def to_action(self) -> dict[str, Any]:
        if self.suppressed:
            return {}
        action: dict[str, Any] = {
            "channel": self.channel,
            "kind": self.kind,
            "body": self.body,
            "rationale": self.rationale,
            "intents": self.intents or ["FYI"],
        }
        if self.citations:
            action["citations"] = self.citations
        if self.context_ids:
            action["context_ids"] = self.context_ids
        if self.evidence:
            action["evidence"] = self.evidence
        return action

    @property
    def is_customer_facing(self) -> bool:
        return self.channel == "customer"

    @property
    def word_count(self) -> int:
        return len([w for w in self.body.split() if w.strip()])


def suppressed(channel: str, kind: str, reason: str) -> ActionPlan:
    return ActionPlan(
        channel=channel,
        kind=kind,
        shape="SUPPRESSED",
        body="",
        rationale=reason,
        suppressed=True,
        suppress_reason=reason,
    )
