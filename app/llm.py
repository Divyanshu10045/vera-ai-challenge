import json
import re
import urllib.error
import urllib.request
from typing import Any

from .evidence import EvidenceBundle
from .plan import ActionPlan
from . import render, validate

SYSTEM_PROMPT = (
    "You rewrite short business messages so they read naturally. "
    "You are NOT allowed to add, remove or alter any fact, number, date, name, price or offer. "
    "Every fact in your output must already appear in the FACTS list you are given. "
    "Never invent a statistic, never add a superlative, never add urgency, never add a link, "
    "never use the words trigger, payload, context, consent, signal or score, "
    "never use a phrase like 'would you', 'do you', 'can you tell', 'what if' or 'how about'. "
    "Output only the rewritten message body and nothing else."
)

USER_TEMPLATE = """Rewrite the DRAFT to sound like a person wrote it. Keep every fact identical. Keep it under {max_words} words and {max_sentences} sentences. Keep the same ask at the end.

FACTS (the only things you may say):
{facts}

TONE: {tone}

DRAFT:
{draft}

REWRITTEN BODY:"""

TONE_MAP = {
    "casual": "casual, warm, one or two short sentences",
    "professional": "warm and professional, plain words",
    "warm": "warm and direct",
}


def _facts_block(bundle: EvidenceBundle, limit: int = 8) -> str:
    lines = [f"- {a.text}" for a in bundle.ranked()[:limit]]
    return "\n".join(lines) if lines else "- (no facts available; do not add any)"


def _post(payload: dict[str, Any], base_url: str, api_key: str, timeout: float) -> str:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"] or ""


def _provider_base(settings: Any) -> str:
    if settings.llm_base_url:
        return settings.llm_base_url
    if settings.llm_provider == "groq":
        return "https://api.groq.com/openai/v1"
    if settings.llm_provider == "openai":
        return "https://api.openai.com/v1"
    if settings.llm_provider == "together":
        return "https://api.together.xyz/v1"
    if settings.llm_provider == "openrouter":
        return "https://openrouter.ai/api/v1"
    return "https://api.groq.com/openai/v1"


def realise(
    plan: ActionPlan,
    bundle: EvidenceBundle,
    settings: Any,
    voice_style: str = "warm",
) -> ActionPlan | None:
    if not settings.llm_enabled or settings.deterministic_only:
        return None
    if not settings.llm_api_key or plan.suppressed or not plan.body.strip():
        return None
    try:
        content = _post(
            {
                "model": settings.llm_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": USER_TEMPLATE.format(
                            max_words=validate.MAX_WORDS,
                            max_sentences=validate.MAX_SENTENCES,
                            facts=_facts_block(bundle),
                            tone=TONE_MAP.get(voice_style, "warm and direct"),
                            draft=plan.body,
                        ),
                    },
                ],
                "temperature": 0.3,
                "max_tokens": settings.llm_max_tokens,
            },
            _provider_base(settings),
            settings.llm_api_key,
            settings.llm_timeout_seconds,
        )
    except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError, IndexError):
        return None

    candidate = (content or "").strip()
    candidate = re.sub(r"^```[a-z]*\n?|```$", "", candidate).strip()
    candidate = candidate.strip('"').strip()
    if not candidate or candidate.lower() == plan.body.lower():
        return None

    trial = ActionPlan(
        channel=plan.channel,
        kind=plan.kind,
        shape=plan.shape,
        body=render.prune_to_budget(candidate),
        rationale=plan.rationale,
        intents=list(plan.intents),
        citations=list(plan.citations),
        context_ids=dict(plan.context_ids),
        evidence=list(plan.evidence),
    )
    report = validate.validate_plan(trial, bundle, None, None)
    if not report.ok:
        return None
    allowed = _numbers(_facts_block(bundle)) | _numbers(plan.body)
    if not _numbers(trial.body) <= allowed:
        return None
    return trial


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+", text or ""))
