import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import normalize
from .evidence import EvidenceAtom, EvidenceBundle, MONEY

MAX_WORDS = 35
MAX_SENTENCES = 3

GLOBAL_TABOOS = (
    "guaranteed",
    "guarantee",
    "miracle",
    "best in city",
    "best in",
    "no.1",
    "number one",
    "cheapest",
    "100%",
    "risk-free",
    "risk free",
    "instantly",
    "act now",
    "limited time",
    "hurry",
    "don't miss out",
    "amazing",
    "incredible",
    "unbelievable",
    "world class",
    "top rated",
    "cure",
    "guaranteed results",
    "we guarantee",
    "you will see",
    "proven to work",
)

SCRUB_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bthe best\b", re.I), "one of the better"),
    (re.compile(r"\bbest\b", re.I), "strong"),
    (re.compile(r"\bcheapest\b", re.I), "sharper priced"),
    (re.compile(r"\bperfect\b", re.I), "very good"),
    (re.compile(r"\bamazing\b", re.I), "solid"),
    (re.compile(r"\bguarantee[ds]?\b", re.I), "aim for"),
    (re.compile(r"\b100%\s*(?:safe|accurate|secure)\b", re.I), "handled with care"),
    (re.compile(r"\binstant(?:ly)?\b", re.I), "quickly"),
    (re.compile(r"\bsuper\b", re.I), "very"),
    (re.compile(r"\bno\.?\s*1\b", re.I), "leading"),
    (re.compile(r"\bnumber one\b", re.I), "leading"),
    (re.compile(r"\bamazing\b", re.I), "solid"),
    (re.compile(r"\b[!?]{2,}\b"), "!"),
    (re.compile(r"\s+([,.!?])"), r"\1"),
    (re.compile(r"([,.!?]){2,}"), r"\1"),
    (re.compile(r"\s{2,}"), " "),
)

URL_PATTERN = re.compile(r"(https?://|www\.|\b\S+\.(?:com|net|org|io|co\.in|app)\b)", re.I)
COT_PATTERN = re.compile(
    r"\b(?:because i|my reasoning|i think|i chose|i decided|let me|first i|then i|"
    r"i will|i'll|i must|i need to|my plan is|reasoning:|thought process|"
    r"step \d|rule \d|according to my)\b",
    re.I,
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

DIFFICULTY_WORDS = (
    "sign up",
    "subscribe",
    "upgrade your plan",
    "choose a plan",
    "get started",
    "book now",
    "opt in",
    "opt-in",
    "limited time",
    "act now",
    "don't miss",
    "act fast",
    "hurry",
)

CLINICAL_CLAIMS = (
    "will cure",
    "cures",
    "guaranteed to work",
    "no side effects",
    "completely safe",
    "removes all",
    "permanent solution",
    "works for everyone",
)


@dataclass
class VoiceProfile:
    slug: str
    tone: list[str] = field(default_factory=list)
    greeting: str = "Hi"
    signoff: str = "Thanks"
    taboos: tuple[str, ...] = ()
    is_b2c: bool = True
    is_clinical: bool = False
    offers_services: bool = True

    @property
    def formality(self) -> str:
        joined = " ".join(self.tone).lower()
        if "casual" in joined or "friendly" in joined:
            return "casual"
        if "professional" in joined or "clinical" in joined or "authoritative" in joined:
            return "professional"
        return "warm"

    def opener(self, name: str | None) -> str:
        who = name.split()[0] if name else None
        if self.formality == "professional":
            return f"Hello {who}," if who else "Hello,"
        if self.formality == "casual":
            return f"Hey {who}!" if who else "Hey!"
        return f"Hi {who}," if who else "Hi,"

    def closer(self) -> str:
        if self.formality == "professional":
            return "Happy to help if useful."
        if self.formality == "casual":
            return "No rush either way."
        return "No rush."


B2C_CATEGORY = {"dentist", "gym", "pharmacy", "restaurant", "salon"}
CLINICAL_CATEGORY = {"pharmacy", "dentist"}
CLINICAL_SAFE = {
    "pharmacy": "pharmacist",
    "dentist": "dental team",
}


def voice_for(category: dict[str, Any] | None, merchant: dict[str, Any] | None = None) -> VoiceProfile:
    category = category if isinstance(category, dict) else {}
    slug = str(category.get("slug") or normalize.merchant_category(merchant) or "")
    voice = category.get("voice") or {}
    tone = voice.get("tone")
    if isinstance(tone, str):
        tone = [tone]
    if not isinstance(tone, list):
        tone = ["warm", "concise"]
    greeting = str(voice.get("greeting_style") or "").lower()
    if "exclam" in greeting:
        opening = "Hey"
    elif "formal" in greeting or "professional" in greeting:
        opening = "Hello"
    else:
        opening = "Hi"
    signoff = str(voice.get("signoff_style") or "").lower()
    if "formal" in signoff or "professional" in signoff:
        closer = "Happy to help if useful."
    elif "casual" in signoff or "no" in signoff:
        closer = "No rush either way."
    else:
        closer = "No rush."
    taboos = tuple(str(t) for t in (voice.get("vocab_taboo") or ()) if str(t).strip())
    b2c = any(tag in slug for tag in ("restaurant", "gym", "salon", "clinic", "pharmacy", "dentist")) and "b2b" not in slug
    return VoiceProfile(
        slug=slug,
        tone=[str(t) for t in tone],
        greeting=opening,
        signoff=closer,
        taboos=taboos,
        is_b2c=b2c,
        is_clinical=any(tag in slug for tag in CLINICAL_CATEGORY),
        offers_services=b2c,
    )


def scrub(text: str, extra_taboos: Iterable[str] = ()) -> str:
    if not text:
        return ""
    banned = set(GLOBAL_TABOOS) | {str(t).strip().lower() for t in extra_taboos if str(t).strip()}
    working = text
    for pattern, replacement in SCRUB_PATTERNS:
        working = pattern.sub(replacement, working)
    working = URL_PATTERN.sub("", working)
    working = COT_PATTERN.sub("", working)
    working = EMAIL_RE.sub("", working)

    kept: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", working):
        lowered = sentence.lower()
        if any(bad in lowered for bad in banned):
            continue
        if any(bad in lowered for bad in DIFFICULTY_WORDS):
            continue
        if any(bad in lowered for bad in CLINICAL_CLAIMS):
            continue
        cleaned = sentence.strip()
        if cleaned:
            kept.append(cleaned)
    result = " ".join(kept)
    result = re.sub(r"\s+([,.!?])", r"\1", result)
    result = re.sub(r"\s{2,}", " ", result).strip()
    if result and result[-1] not in ".!?":
        result += "."
    return result


DECAP_SAFE = {
    "you", "your", "i", "it", "this", "that", "there", "we", "they", "the", "a", "an",
    "nothing", "no", "not", "one", "two", "three", "four", "do", "want", "shall",
    "reply", "say", "adding", "under", "verified", "calls", "views", "is", "was",
    "has", "have", "call", "drop", "retention", "peak", "searches", "stock", "both",
    "last", "next", "since", "plan", "trial", "delivery", "monthly", "repeat", "senior",
    "most", "prefers", "age", "favourite", "active", "6-month", "3-month", "trial-to-paid",
    "credits", "lapsed", "target", "against", "days", "months", "effective", "your listing",
    "i've", "i'm", "it's", "that's", "we're", "there's", "should", "could", "would", "can",
    "if", "when", "while", "after", "before", "because", "so", "and", "but", "or", "in", "on",
    "at", "to", "from", "by", "with", "for", "of", "as", "than", "then", "just", "also",
}


def decap(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped
    first = stripped.split(" ", 1)[0]
    bare = first.strip("\"'([“‘").rstrip(",.!?;:").lower()
    if bare in DECAP_SAFE:
        return stripped[0].lower() + stripped[1:]
    return stripped


def punctuate(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    if stripped[-1] in ".!?,;:":
        return stripped
    if stripped[-1] in '"”’\'' and len(stripped) > 1:
        closer = stripped[-1]
        return stripped[:-1].rstrip() + closer + "."
    return stripped + "."


def compose(fragments: list[str], ask: str = "") -> str:
    parts: list[str] = []
    continuing = False
    for fragment in fragments:
        cleaned = (fragment or "").strip()
        if not cleaned:
            continue
        if continuing:
            cleaned = decap(cleaned)
        cleaned = punctuate(cleaned)
        parts.append(cleaned)
        continuing = cleaned[-1] in ",;" if cleaned else False
    question = (ask or "").strip()
    if question:
        if not question.endswith("?"):
            question = question.rstrip(".") + "?"
        parts.append(question)
    return " ".join(p for p in parts if p.strip())


def prune_to_budget(text: str, max_words: int = MAX_WORDS, max_sentences: int = MAX_SENTENCES) -> str:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        return ""
    if len(sentences) <= max_sentences:
        return text.strip()
    head: list[str] = []
    count = 0
    tail = sentences[-1]
    for sentence in sentences[:-1]:
        words = len([w for w in sentence.split() if w.strip()])
        if head and (count + words > max_words or len(head) >= max_sentences - 1):
            break
        head.append(sentence)
        count += words
    while head and count + len([w for w in tail.split() if w.strip()]) > max_words:
        head.pop()
        if head:
            count = len([w for w in " ".join(head).split() if w.strip()])
    if not head:
        return tail
    return " ".join(head + [tail])


def take(bundle: EvidenceBundle, kinds: Iterable[str], n: int = 1) -> list[EvidenceAtom]:
    out: list[EvidenceAtom] = []
    for kind in kinds:
        for atom in bundle.ranked():
            if atom.kind == kind and atom not in out:
                out.append(atom)
                if len(out) >= n:
                    return out
    return out


def first_text(bundle: EvidenceBundle, kinds: Iterable[str]) -> str:
    found = take(bundle, kinds, 1)
    return found[0].text if found else ""


def first_atom(bundle: EvidenceBundle, kinds: Iterable[str]) -> EvidenceAtom | None:
    found = take(bundle, kinds, 1)
    return found[0] if found else None


def count_text(atom: EvidenceAtom | None, noun: str = "day", plural: str | None = None) -> str:
    if atom is None or atom.num is None:
        return ""
    value = int(round(atom.num))
    word = noun if value == 1 else (plural or f"{noun}s")
    from .evidence import indian_group

    return f"{indian_group(value)} {word}"


def all_texts(bundle: EvidenceBundle, kinds: Iterable[str], n: int = 3) -> list[str]:
    return [a.text for a in take(bundle, kinds, n)]


def reference_of(category: dict[str, Any] | None, merchant: dict[str, Any] | None) -> str:
    name = normalize.merchant_name(merchant)
    if name:
        return name
    if isinstance(category, dict) and category.get("slug"):
        return str(category["slug"]).replace("_", " ")
    return "your business"


def number_with_unit(text: str) -> str:
    return text


def money(value: int | float) -> str:
    return f"{MONEY}{int(value):,}"


def contact_hint(voice: VoiceProfile, category: dict[str, Any] | None) -> str:
    if voice.is_clinical:
        return f"the {CLINICAL_SAFE.get(voice.slug, 'care team')}"
    return "the team"


def read_style(voice: VoiceProfile) -> str:
    if voice.formality == "casual":
        return "casual"
    if voice.formality == "professional":
        return "warm-professional"
    return "warm"


def owner_of(merchant: dict[str, Any] | None) -> str | None:
    value = normalize.merchant_owner(merchant)
    return value or None


def customer_name(customer: dict[str, Any] | None) -> str | None:
    value = normalize.customer_name(customer)
    return value or None


def language_note(merchant: dict[str, Any] | None) -> str:
    languages = normalize.merchant_languages(merchant)
    if not languages:
        return ""
    first = str(languages[0]).lower()
    if first in {"hindi", "marathi", "tamil", "telugu", "bengali", "gujarati", "kannada", "malayalam"}:
        return f"{first.capitalize()} works too."
    return ""


def locality_of(merchant: dict[str, Any] | None) -> str:
    return normalize.merchant_locality(merchant)
