import re
from dataclasses import dataclass, field
from typing import Any

from . import normalize
from .evidence import EvidenceBundle
from .plan import ActionPlan

MAX_WORDS = 35
MAX_SENTENCES = 3
MAX_BODY_CHARS = 480
MAX_RATIONALE_CHARS = 260

INTERNAL_JARGON = (
    "trigger",
    "payload",
    "context_id",
    "context ids",
    "urgency",
    "customercontext",
    "merchantcontext",
    "categorycontext",
    "evidence atom",
    "provenance",
    "lifecycle state",
    "conversion",
    "funnel",
    "retention cohort",
    "placebo",
    "b2c",
    "b2b",
    "kpi",
    "signal score",
    "dormancy score",
    "consent scope",
    "opt_in",
    "scoring",
    "rubric",
    "placeholder",
    "canonical",
    "replay",
    "harness",
    "simulator",
    "verifier",
    "latency budget",
    "cold start",
    "graders",
    "json",
    "api",
    "endpoint",
    "schema",
)

STRUCTURAL_NUMBER_ALLOW = {
    "1",
    "2",
    "3",
    "4",
    "5",
    "30",
    "60",
    "7",
    "24",
}

NUMBER_RE = re.compile(r"\d+")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class ValidationReport:
    ok: bool = True
    fixes: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def fail(self, reason: str) -> None:
        self.ok = False
        self.violations.append(reason)

    def fix(self, note: str) -> None:
        self.fixes.append(note)


def _numbers(text: str) -> set[str]:
    return set(NUMBER_RE.findall(text or ""))


def validate_plan(
    plan: ActionPlan,
    bundle: EvidenceBundle,
    merchant: dict[str, Any] | None,
    customer: dict[str, Any] | None = None,
) -> ValidationReport:
    report = ValidationReport()
    if plan.suppressed:
        return report
    body = plan.body or ""
    if not body.strip():
        report.fail("empty body")
        return report
    if len(body) > MAX_BODY_CHARS:
        report.fail(f"body too long ({len(body)} chars)")
    words = [w for w in body.split() if w.strip()]
    if len(words) > MAX_WORDS:
        report.fail(f"body too wordy ({len(words)} words)")
    sentences = [s for s in SENTENCE_SPLIT.split(body) if s.strip()]
    if len(sentences) > MAX_SENTENCES:
        report.fail(f"too many sentences ({len(sentences)})")
    if re.search(r"https?://|www\.|\S+\.(?:com|net|org|io|co\.in|app)\b", body, re.I):
        report.fail("body contains a URL")
    if re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", body):
        report.fail("body contains an email address")
    lowered = body.lower()
    for term in INTERNAL_JARGON:
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            report.fail(f"internal jargon exposed: {term}")

    rationale = plan.rationale or ""
    if len(rationale) > MAX_RATIONALE_CHARS:
        report.fail(f"rationale too long ({len(rationale)} chars)")
    if not rationale.strip():
        report.fail("missing rationale")
    if body.strip() and body.strip()[:40].lower() in rationale.lower():
        report.fail("rationale restates the message body")
    cot = re.search(
        r"\b(?:because i|my reasoning|i chose|i decided|first i then|step \d|rule \d|according to my)\b",
        rationale,
        re.I,
    )
    if cot:
        report.fail("rationale exposes chain-of-thought")

    if plan.channel == "merchant" and customer is not None and _mentions_third_party(bundle):
        report.fail("merchant-facing message appears to reference customer personal data")

    grounded_texts = " ".join(a.text for a in bundle.atoms)
    grounded_numbers = _numbers(grounded_texts)
    identity_numbers = _numbers(
        f"{normalize.merchant_name(merchant)} {normalize.merchant_locality(merchant)}"
    )
    for number in _numbers(body):
        if number in grounded_numbers or number in identity_numbers:
            continue
        if number in STRUCTURAL_NUMBER_ALLOW:
            continue
        if number.rstrip("0") == number.rstrip("0") and number in {n.lstrip("0") for n in grounded_numbers if n.lstrip("0")}:
            continue
        report.fail(f"ungrounded number in body: {number}")
    return report


def _mentions_third_party(bundle: EvidenceBundle) -> bool:
    return any(
        a.provenance.startswith("customer.") and "identity" not in a.provenance for a in bundle.atoms
    )


def finalise(
    plan: ActionPlan,
    bundle: EvidenceBundle,
    merchant: dict[str, Any] | None,
    customer: dict[str, Any] | None = None,
) -> ActionPlan:
    from . import render

    plan.body = render.prune_to_budget(render.scrub(plan.body))
    plan.rationale = plan.rationale.strip()
    report = validate_plan(plan, bundle, merchant, customer)
    if report.ok:
        return plan
    if not plan.body.strip():
        plan.suppressed = True
        plan.suppress_reason = report.violations[0] if report.violations else "invalid"
        return plan
    plan.rationale = (
        f"{plan.rationale} Draft held back: {'; '.join(report.violations[:2])}.".strip()
    )[:MAX_RATIONALE_CHARS]
    return plan
