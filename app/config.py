import os
from dataclasses import dataclass, field


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    team_name: str
    team_members: list[str]
    contact_email: str
    model_label: str
    approach: str
    version: str

    llm_enabled: bool
    llm_provider: str
    llm_api_key: str
    llm_model: str
    llm_base_url: str
    llm_timeout_seconds: float
    llm_max_tokens: int

    tick_budget_seconds: float
    reply_budget_seconds: float
    max_actions_per_tick: int
    deterministic_only: bool

    per_merchant_tick_cap: int
    per_merchant_daily_cap: int
    auto_reply_end_after: int
    unanswered_nudge_limit: int

    def __post_init__(self) -> None:
        if self.max_actions_per_tick > 20:
            raise ValueError("judge caps actions at 20 per tick")


def _members() -> list[str]:
    raw = os.getenv("VERA_TEAM_MEMBERS", "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def load_settings() -> Settings:
    return Settings(
        team_name=os.getenv("VERA_TEAM_NAME", "Team Sigma"),
        team_members=_members(),
        contact_email=os.getenv("VERA_CONTACT_EMAIL", ""),
        model_label=os.getenv("VERA_MODEL_LABEL", "deterministic-composer-v1"),
        approach=os.getenv(
            "VERA_APPROACH",
            "evidence-atom composer: deterministic fact extraction from the four contexts, "
            "category-voice realisation, schema validator, optional bounded LLM surface realiser",
        ),
        version=os.getenv("VERA_VERSION", "1.0.0"),
        llm_enabled=_flag("VERA_LLM_ENABLED", False),
        llm_provider=os.getenv("VERA_LLM_PROVIDER", "groq"),
        llm_api_key=os.getenv("VERA_LLM_API_KEY", ""),
        llm_model=os.getenv("VERA_LLM_MODEL", "llama-3.3-70b-versatile"),
        llm_base_url=os.getenv("VERA_LLM_BASE_URL", ""),
        llm_timeout_seconds=float(os.getenv("VERA_LLM_TIMEOUT", "4.0")),
        llm_max_tokens=int(os.getenv("VERA_LLM_MAX_TOKENS", "400")),
        tick_budget_seconds=float(os.getenv("VERA_TICK_BUDGET", "9.0")),
        reply_budget_seconds=float(os.getenv("VERA_REPLY_BUDGET", "6.0")),
        max_actions_per_tick=int(os.getenv("VERA_MAX_ACTIONS", "8")),
        deterministic_only=_flag("VERA_DETERMINISTIC_ONLY", False),
        per_merchant_tick_cap=int(os.getenv("VERA_MERCHANT_TICK_CAP", "2")),
        per_merchant_daily_cap=int(os.getenv("VERA_MERCHANT_DAILY_CAP", "4")),
        auto_reply_end_after=int(os.getenv("VERA_AUTO_REPLY_END_AFTER", "4")),
        unanswered_nudge_limit=int(os.getenv("VERA_UNANSWERED_LIMIT", "3")),
    )


SETTINGS = load_settings()
