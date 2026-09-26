import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

MONEY = "₹"

JUDGE_VISIBLE_ROOTS = {
    ("merchant", "identity"),
    ("merchant", "performance"),
    ("merchant", "signals"),
    ("merchant", "offers"),
    ("trigger", "payload"),
    ("trigger", "kind"),
    ("trigger", "urgency"),
    ("customer", "identity"),
    ("category", "slug"),
    ("category", "voice"),
}


@dataclass(frozen=True)
class EvidenceAtom:
    text: str
    provenance: str
    kind: str
    weight: int = 50
    resolution_of: str | None = None
    taboo_risk: tuple[str, ...] = ()
    label: str = ""
    num: float | None = None

    @property
    def judge_verifiable(self) -> bool:
        if self.resolution_of:
            return True
        parts = self.provenance.split(".")
        if len(parts) >= 2 and (parts[0], parts[1]) in JUDGE_VISIBLE_ROOTS:
            return True
        return self.provenance.startswith(("trigger.", "customer.identity"))


@dataclass
class EvidenceBundle:
    atoms: list[EvidenceAtom] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    is_placeholder_trigger: bool = False
    has_rich_trigger: bool = False
    category_slug: str | None = None
    merchant_id: str | None = None
    customer_id: str | None = None
    trigger_kind: str | None = None
    trigger_scope: str | None = None
    urgency: int = 0
    consent_block: str | None = None
    promo_allowed: bool = True
    consent_note: str | None = None
    contradiction: str | None = None

    def add(self, atom: EvidenceAtom) -> None:
        if atom.text and atom.text.strip():
            self.atoms.append(atom)

    def ranked(self, prefer_verifiable: bool = True) -> list[EvidenceAtom]:
        return sorted(
            self.atoms,
            key=lambda a: (a.judge_verifiable if prefer_verifiable else True, a.weight),
            reverse=True,
        )

    def top(self, n: int = 3, kinds: Iterable[str] | None = None) -> list[EvidenceAtom]:
        pool = self.ranked()
        if kinds:
            wanted = set(kinds)
            filtered = [a for a in pool if a.kind in wanted]
            if filtered:
                return filtered[:n]
        return pool[:n]

    def has(self, kind: str) -> bool:
        return any(a.kind == kind for a in self.atoms)


def indian_group(value: int) -> str:
    digits = str(abs(int(value)))
    if len(digits) <= 3:
        grouped = digits
    else:
        head = len(digits) - 3
        head_digits = digits[:head]
        tail = digits[head:]
        parts = []
        while len(head_digits) > 2:
            parts.insert(0, head_digits[-2:])
            head_digits = head_digits[:-2]
        if head_digits:
            parts.insert(0, head_digits)
        grouped = ",".join(parts) + "," + tail
    return ("-" if value < 0 else "") + grouped


def pct(value: float, decimals: int = 1) -> str:
    return f"{round(float(value) * 100, decimals):g}%"


def parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


SIGNAL_PATTERNS: tuple[tuple[re.Pattern[str], Any], ...] = (
    (re.compile(r"^perf_dip:views_7d:(-?[\d.]+)$"), lambda m: f"views down {pct(abs(float(m.group(1))))} week-on-week"),
    (re.compile(r"^perf_dip:calls_7d:(-?[\d.]+)$"), lambda m: f"calls down {pct(abs(float(m.group(1))))} week-on-week"),
    (re.compile(r"^views_spike_7d:\+?([\d.]+)$"), lambda m: f"views up {pct(float(m.group(1)))} week-on-week"),
    (re.compile(r"^calls_spike_7d:\+?([\d.]+)$"), lambda m: f"calls up {pct(float(m.group(1)))} week-on-week"),
    (re.compile(r"^milestone_reached:reviews_(\d+)$"), lambda m: f"{m.group(1)} reviews on the listing"),
    (re.compile(r"^milestone_reached:(\w+)_(\d+)$"), lambda m: f"{m.group(1).replace('_',' ')} reached {m.group(2)}"),
    (re.compile(r"^stale_posts:(\d+)d$"), lambda m: f"posts going stale for {m.group(1)} days"),
    (re.compile(r"^no_active_offer:(\d+)d$"), lambda m: f"no active offer for {m.group(1)} days"),
    (re.compile(r"^gbp_unverified:(\d+)d$"), lambda m: f"listing unverified for {m.group(1)} days"),
    (re.compile(r"^renewal_due:(\d+)d$"), lambda m: f"renewal due in {m.group(1)} days"),
    (re.compile(r"^dormant_(\d+)d$"), lambda m: f"dormant for {m.group(1)} days"),
    (re.compile(r"^lapsed_(\d+)d$"), lambda m: f"no activity for {m.group(1)} days"),
    (re.compile(r"^(\w+)_(\d+)d$"), lambda m: f"{m.group(1).replace('_',' ')} for {m.group(2)} days"),
)


def render_signal(raw: str) -> str:
    text = str(raw).strip()
    for pattern, builder in SIGNAL_PATTERNS:
        match = pattern.match(text)
        if match:
            return builder(match)
    cleaned = re.sub(r":\d+[a-z]?$", "", text)
    return cleaned.replace("_", " ")


def _signal_label(raw: str) -> str:
    return render_signal(raw)


def _offer_price(title: str) -> tuple[str, int | None]:
    match = re.search(r"(\d[\d,]*)\s*(?:OFF|off|%)?", title)
    if "₹" in title and match:
        return MONEY + match.group(1), int(match.group(1).replace(",", ""))
    percent = re.search(r"(\d+)\s*%", title)
    if percent:
        return percent.group(1) + "%", None
    return "", None


def resolve_digest_item(category: dict[str, Any] | None, item_id: Any) -> dict[str, Any] | None:
    if not category or not item_id:
        return None
    digest = category.get("digest") or []
    for item in digest:
        if isinstance(item, dict) and item.get("id") == item_id:
            return item
    lowered = str(item_id).lower()
    for item in digest:
        if not isinstance(item, dict):
            continue
        haystack = f"{item.get('id','')} {item.get('title','')}".lower()
        if lowered in haystack or any(tok and tok in haystack for tok in lowered.split("_") if len(tok) > 4):
            return item
    return None


def extract_digest_atoms(
    bundle: EvidenceBundle, category: dict[str, Any] | None, trigger: dict[str, Any], now: datetime
) -> None:
    payload = trigger.get("payload") or {}
    pointer = payload.get("top_item_id") or payload.get("digest_item_id") or payload.get("alert_id")
    item = resolve_digest_item(category, pointer)
    if item is None and not payload.get("placeholder"):
        digest = (category or {}).get("digest") or []
        if digest and str(trigger.get("kind", "")).endswith("digest"):
            item = digest[0]
    if not isinstance(item, dict):
        return
    ref = f"trigger.payload.{pointer}" if pointer else "category.digest[0]"
    title = str(item.get("title") or "").strip().rstrip(".")
    if title:
        bundle.add(EvidenceAtom(text=title, provenance=ref, kind="digest", weight=95, resolution_of=ref))
    source = str(item.get("source") or "").strip()
    if source:
        bundle.add(EvidenceAtom(text=source, provenance=ref, kind="citation", weight=92, resolution_of=ref))
    trial_n = item.get("trial_n")
    if isinstance(trial_n, int) and trial_n > 0:
        bundle.add(
            EvidenceAtom(
                text=f"{indian_group(trial_n)}-patient trial",
                provenance=ref,
                kind="trial",
                weight=90,
                resolution_of=ref,
            )
        )
    credits = item.get("credits")
    if isinstance(credits, int) and credits > 0:
        bundle.add(
            EvidenceAtom(
                text=f"{credits} CDE credits", provenance=ref, kind="credit", weight=80, resolution_of=ref
            )
        )
    when = parse_iso(item.get("date"))
    if when:
        bundle.add(
            EvidenceAtom(
                text=when.strftime("%d %b %Y, %I:%M %p").lstrip("0"),
                provenance=ref,
                kind="date",
                weight=88,
                resolution_of=ref,
            )
        )
    deadline = payload.get("deadline_iso")
    if deadline:
        parsed = parse_iso(deadline)
        if parsed:
            days = (parsed.date() - now.date()).days
            if days >= 0:
                bundle.add(
                    EvidenceAtom(
                        text=f"effective in {days} days" if days else "effective today",
                        provenance="trigger.payload.deadline_iso",
                        kind="deadline",
                        weight=94,
                    )
                )
    actionable = str(item.get("actionable") or "").strip()
    if actionable:
        bundle.add(
            EvidenceAtom(
                text=actionable, provenance=ref, kind="actionable", weight=70, resolution_of=ref
            )
        )
    if item.get("patient_segment"):
        bundle.add(
            EvidenceAtom(
                text=str(item["patient_segment"]).replace("_", " "),
                provenance=ref,
                kind="segment",
                weight=72,
                resolution_of=ref,
            )
        )


def extract_trigger_payload_atoms(bundle: EvidenceBundle, trigger: dict[str, Any], now: datetime) -> None:
    payload = trigger.get("payload") or {}
    if not isinstance(payload, dict) or payload.get("placeholder"):
        return
    ref = "trigger.payload"

    for key, label, kind in (
        ("metric", "metric", "topic"),
        ("intent_topic", "topic", "topic"),
        ("season", "season", "topic"),
        ("theme", "theme", "topic"),
        ("molecule", "molecule", "topic"),
        ("last_topic", "last topic", "topic"),
        ("ask_template", "ask", "topic"),
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            pretty = value.replace("_", " ")
            if key == "ask_template":
                pretty = pretty.replace("what service in demand this week", "the most-asked service this week")
            bundle.add(EvidenceAtom(text=pretty, provenance=f"{ref}.{key}", kind=kind, weight=60))

    for key, kind, weight in (
        ("delta_pct", "pct", 93),
        ("perf_dip_pct", "pct", 93),
        ("estimated_uplift_pct", "pct", 88),
    ):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            direction = "up" if value > 0 else "down"
            bundle.add(
                EvidenceAtom(
                    text=f"{pct(abs(value))} {direction}",
                    provenance=f"{ref}.{key}",
                    kind=kind,
                    weight=weight,
                )
            )

    for key, kind, weight in (
        ("vs_baseline", "baseline", 90),
        ("value_now", "current", 92),
        ("milestone_value", "target", 92),
        ("days_until", "countdown", 90),
        ("days_since_last_visit", "gap", 92),
        ("days_since_last_merchant_message", "gap", 92),
        ("days_since_expiry", "gap", 90),
        ("days_to_wedding", "countdown", 94),
        ("lapsed_customers_added_since_expiry", "lapsed", 85),
        ("occurrences_30d", "count", 88),
        ("previous_membership_months", "count", 80),
    ):
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            bundle.add(
                EvidenceAtom(
                    text=f"{indian_group(int(value))} {key.replace('_', ' ')}",
                    provenance=f"{ref}.{key}",
                    kind=kind,
                    weight=weight,
                    label=key,
                    num=float(value),
                )
            )

    amount = payload.get("renewal_amount")
    if isinstance(amount, (int, float)) and not isinstance(amount, bool):
        bundle.add(
            EvidenceAtom(
                text=f"{MONEY}{indian_group(int(amount))}",
                provenance=f"{ref}.renewal_amount",
                kind="money",
                weight=90,
                label="renewal_amount",
                num=float(amount),
            )
        )

    for key, kind, weight in (
        ("competitor_name", "name", 92),
        ("manufacturer", "name", 88),
        ("festival", "topic", 92),
        ("match", "topic", 93),
        ("venue", "topic", 88),
        ("city", "topic", 70),
        ("verification_path", "topic", 84),
        ("last_service_date", "date", 90),
        ("due_date", "date", 92),
        ("last_refill", "date", 86),
        ("opened_date", "date", 84),
        ("date", "date", 86),
        ("merchant_last_message", "quote", 88),
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            pretty = value.replace("_", " ")
            if key == "merchant_last_message":
                pretty = value.strip().strip('"')
            bundle.add(EvidenceAtom(text=pretty, provenance=f"{ref}.{key}", kind=kind, weight=weight, label=key))

    for key, kind, weight in (
        ("distance_km", "number", 92),
        ("is_imminent", "bool", 80),
        ("is_expected_seasonal", "bool", 86),
        ("is_weeknight", "bool", 92),
        ("likely_driver", "topic", 78),
        ("previous_focus", "topic", 86),
        ("service_due", "topic", 90),
        ("next_step_window_open", "topic", 84),
        ("season_note", "topic", 82),
        ("their_offer", "offer", 92),
        ("fee", "money", 78),
        ("molecule_list", "list", 92),
        ("affected_batches", "list", 94),
        ("trends", "list", 88),
        ("category_relevance", "list", 55),
    ):
        value = payload.get(key)
        if isinstance(value, bool):
            if value:
                bundle.add(EvidenceAtom(text="yes", provenance=f"{ref}.{key}", kind=kind, weight=weight))
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            unit = "km away" if key == "distance_km" else ""
            bundle.add(
                EvidenceAtom(
                    text=f"{indian_group(int(value))} {unit}".strip(),
                    provenance=f"{ref}.{key}",
                    kind=kind,
                    weight=weight,
                )
            )
        elif isinstance(value, list) and value:
            rendered = ", ".join(str(v) for v in value if str(v).strip())
            if rendered:
                bundle.add(
                    EvidenceAtom(text=rendered, provenance=f"{ref}.{key}", kind=kind, weight=weight)
                )

    slots = payload.get("available_slots") or payload.get("next_session_options")
    if isinstance(slots, list) and slots:
        labels = [
            str(s.get("label")) for s in slots if isinstance(s, dict) and s.get("label")
        ] or [str(parse_iso(s.get("iso")).strftime("%a %d %b, %I%p")) for s in slots if isinstance(s, dict) and parse_iso(s.get("iso"))]
        if labels:
            bundle.add(
                EvidenceAtom(
                    text=" and ".join(labels[:2]) if len(labels) <= 2 else ", ".join(labels[:2]) + f" (+{len(labels)-2} more)",
                    provenance=f"{ref}.available_slots",
                    kind="slot",
                    weight=94,
                )
            )
    elif payload.get("stock_runs_out_iso"):
        parsed = parse_iso(payload["stock_runs_out_iso"])
        if parsed:
            bundle.add(
                EvidenceAtom(
                    text=parsed.strftime("%d %b"),
                    provenance=f"{ref}.stock_runs_out_iso",
                    kind="date",
                    weight=94,
                )
            )


def extract_performance_atoms(bundle: EvidenceBundle, merchant: dict[str, Any]) -> None:
    perf = merchant.get("performance") or {}
    ref = "merchant.performance"
    views, calls = perf.get("views"), perf.get("calls")
    ctr = perf.get("ctr")
    window = perf.get("window_days") or 30
    if isinstance(views, int):
        bundle.add(
            EvidenceAtom(
                text=f"{indian_group(views)} views in {window}d",
                provenance=f"{ref}.views",
                kind="number",
                weight=70,
            )
        )
    if isinstance(calls, int):
        bundle.add(
            EvidenceAtom(
                text=f"{calls} calls in {window}d", provenance=f"{ref}.calls", kind="number", weight=72
            )
        )
    if isinstance(ctr, (int, float)) and ctr > 0:
        bundle.add(
            EvidenceAtom(
                text=f"{pct(ctr)} CTR", provenance=f"{ref}.ctr", kind="pct", weight=74
            )
        )
    delta = perf.get("delta_7d") or {}
    for key, metric, weight in (("views_pct", "views", 76), ("calls_pct", "calls", 78), ("ctr_pct", "CTR", 70)):
        value = delta.get(key)
        if isinstance(value, (int, float)) and abs(value) >= 0.05:
            direction = "up" if value > 0 else "down"
            bundle.add(
                EvidenceAtom(
                    text=f"{metric} {direction} {pct(abs(value))} week-on-week",
                    provenance=f"{ref}.delta_7d.{key}",
                    kind="delta",
                    weight=weight,
                )
            )


def extract_signal_atoms(bundle: EvidenceBundle, merchant: dict[str, Any]) -> None:
    signals = merchant.get("signals") or []
    if not isinstance(signals, list):
        return
    for raw in signals:
        if not isinstance(raw, str) or not raw.strip():
            continue
        weight = 80
        label = _signal_label(raw)
        if any(k in raw for k in ("dip", "below", "unverified", "dormant", "lapsed", "stale", "renewal", "expired", "no_active", "no_recent")):
            weight = 92
        elif any(k in raw for k in ("spike", "milestone", "above_peer", "high_", "growing", "engaged")):
            weight = 86
        bundle.add(EvidenceAtom(text=label, provenance="merchant.signals", kind="signal", weight=weight))


def extract_offer_atoms(bundle: EvidenceBundle, merchant: dict[str, Any]) -> None:
    offers = merchant.get("offers") or []
    if not isinstance(offers, list):
        return
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        status = str(offer.get("status") or "active").lower()
        title = str(offer.get("title") or "").strip()
        if not title:
            continue
        if status != "active":
            bundle.add(
                EvidenceAtom(
                    text=f"{title} ({status})",
                    provenance="merchant.offers",
                    kind="offer_inactive",
                    weight=60,
                )
            )
            continue
        price_text, _ = _offer_price(title)
        bundle.add(
            EvidenceAtom(
                text=title, provenance="merchant.offers", kind="offer", weight=86,
                taboo_risk=("guaranteed", "best in city"),
            )
        )
        if price_text and price_text not in title:
            bundle.add(
                EvidenceAtom(
                    text=f"{title} at {price_text}", provenance="merchant.offers", kind="offer", weight=84
                )
            )


def extract_aggregate_atoms(bundle: EvidenceBundle, merchant: dict[str, Any]) -> None:
    agg = merchant.get("customer_aggregate") or {}
    if not isinstance(agg, dict):
        return
    ref = "merchant.customer_aggregate"
    plan = (
        ("total_active_members", "active members", "number", 90),
        ("chronic_rx_count", "chronic-Rx customers", "number", 92),
        ("high_risk_adult_count", "high-risk adult patients", "number", 94),
        ("total_unique_ytd", "unique customers YTD", "number", 66),
        ("lapsed_180d_plus", "lapsed 180d+", "number", 84),
        ("lapsed_90d_plus", "lapsed 90d+", "number", 82),
        ("delivery_orders_30d", "delivery orders in 30d", "number", 80),
        ("dine_in_orders_30d", "dine-in orders in 30d", "number", 80),
    )
    for key, label, kind, weight in plan:
        value = agg.get(key)
        if isinstance(value, int) and value > 0:
            bundle.add(
                EvidenceAtom(
                    text=f"{indian_group(value)} {label}", provenance=f"{ref}.{key}", kind=kind, weight=weight
                )
            )
    for key, label, weight in (
        ("retention_6mo_pct", "6-month retention", 86),
        ("retention_3mo_pct", "3-month retention", 84),
        ("repeat_customer_pct", "repeat customer share", 84),
        ("monthly_churn_pct", "monthly churn", 82),
        ("trial_to_paid_pct", "trial-to-paid", 80),
        ("delivery_share_pct", "delivery share", 76),
    ):
        value = agg.get(key)
        if isinstance(value, (int, float)) and 0 <= value <= 1:
            bundle.add(
                EvidenceAtom(
                    text=f"{label} at {pct(value)}", provenance=f"{ref}.{key}", kind="pct", weight=weight
                )
            )


def extract_subscription_atoms(bundle: EvidenceBundle, merchant: dict[str, Any]) -> None:
    sub = merchant.get("subscription") or {}
    if not isinstance(sub, dict):
        return
    ref = "merchant.subscription"
    status = str(sub.get("status") or "").lower()
    days = sub.get("days_remaining")
    if status == "expired":
        since = sub.get("days_since_expiry")
        if isinstance(since, int) and since > 0:
            bundle.add(
                EvidenceAtom(
                    text=f"subscription lapsed {since} days ago",
                    provenance=f"{ref}.days_since_expiry",
                    kind="status",
                    weight=92,
                )
            )
        else:
            bundle.add(
                EvidenceAtom(text="subscription is inactive", provenance=ref, kind="status", weight=88)
            )
    elif status == "trial" and isinstance(days, int) and days > 0:
        bundle.add(
            EvidenceAtom(
                text=f"trial ends in {days} days", provenance=f"{ref}.days_remaining", kind="status", weight=90
            )
        )
    elif status == "active" and isinstance(days, int) and 0 < days <= 30:
        bundle.add(
            EvidenceAtom(
                text=f"plan renews in {days} days", provenance=f"{ref}.days_remaining", kind="status", weight=86
            )
        )
    if not status:
        return


def extract_category_atoms(
    bundle: EvidenceBundle, category: dict[str, Any] | None, now: datetime
) -> None:
    if not isinstance(category, dict):
        return
    peer = category.get("peer_stats") or {}
    if isinstance(peer.get("avg_ctr"), (int, float)):
        bundle.add(
            EvidenceAtom(
                text=f"{pct(peer['avg_ctr'])} peer-median CTR",
                provenance="category.peer_stats.avg_ctr",
                kind="peer",
                weight=76,
            )
        )
    if isinstance(peer.get("avg_rating"), (int, float)):
        bundle.add(
            EvidenceAtom(
                text=f"{peer['avg_rating']}★ peer average",
                provenance="category.peer_stats.avg_rating",
                kind="peer",
                weight=70,
            )
        )
    if isinstance(peer.get("avg_calls_30d"), (int, float)):
        bundle.add(
            EvidenceAtom(
                text=f"peer median {peer['avg_calls_30d']} calls/30d",
                provenance="category.peer_stats.avg_calls_30d",
                kind="peer",
                weight=78,
            )
        )
    catalog = category.get("offer_catalog") or []
    if isinstance(catalog, list) and catalog:
        titles = [
            str(o.get("title")).strip()
            for o in catalog
            if isinstance(o, dict) and o.get("title")
        ]
        if titles:
            bundle.add(
                EvidenceAtom(
                    text=titles[0], provenance="category.offer_catalog", kind="catalog", weight=58
                )
            )
    month_name = now.strftime("%b")
    for beat in category.get("seasonal_beats") or []:
        if not isinstance(beat, dict):
            continue
        window = str(beat.get("month_range") or beat.get("month") or "")
        if month_name.lower() in window.lower():
            note = str(beat.get("note") or "").strip()
            if note:
                bundle.add(
                    EvidenceAtom(
                        text=f"{window}: {note}", provenance="category.seasonal_beats", kind="seasonal", weight=74
                    )
                )
    for trend in (category.get("trend_signals") or [])[:2]:
        if not isinstance(trend, dict):
            continue
        query, delta = trend.get("query"), trend.get("delta_yoy")
        if isinstance(query, str) and isinstance(delta, (int, float)):
            bundle.add(
                EvidenceAtom(
                    text=f'"{query}" searches {pct(abs(delta))} {"up" if delta > 0 else "down"} YoY',
                    provenance="category.trend_signals",
                    kind="trend",
                    weight=72,
                )
            )


def extract_customer_atoms(
    bundle: EvidenceBundle, customer: dict[str, Any] | None, trigger: dict[str, Any], now: datetime
) -> None:
    if not isinstance(customer, dict):
        return
    identity = customer.get("identity") or {}
    rel = customer.get("relationship") or {}
    ref = "customer.relationship"
    visits = rel.get("visits_total")
    if isinstance(visits, int) and visits > 0:
        bundle.add(
            EvidenceAtom(
                text=f"{visits} visits since {str(rel.get('first_visit') or '')[:10]}",
                provenance=f"{ref}.visits_total",
                kind="customer",
                weight=84,
            )
        )
    last_visit = parse_iso(rel.get("last_visit"))
    if last_visit:
        days = max(0, (now.date() - last_visit.date()).days)
        if days < 60:
            unit = f"{days} days"
        else:
            months = max(1, round(days / 30.0))
            unit = "about a month" if months <= 1 else f"{months} months"
        bundle.add(
            EvidenceAtom(
                text=unit,
                provenance=f"{ref}.last_visit",
                kind="customer",
                weight=90,
            )
        )
    services = rel.get("services_received") or []
    if isinstance(services, list) and services:
        counts: dict[str, int] = {}
        for svc in services:
            if isinstance(svc, str) and svc.strip():
                counts[svc] = counts.get(svc, 0) + 1
        if counts:
            top, hits = max(counts.items(), key=lambda kv: kv[1])
            bundle.add(
                EvidenceAtom(
                    text=f"most booked: {top.replace('_', ' ')}",
                    provenance=f"{ref}.services_received",
                    kind="customer",
                    weight=82,
                )
            )
    for key, label, weight in (
        ("age_band", "age band", 72),
        ("favourite_dish", "favourite", 84),
        ("training_focus", "focus", 84),
        ("health_focus", "focus", 84),
    ):
        value = rel.get(key) or identity.get(key)
        if isinstance(value, str) and value.strip():
            pretty = value.replace("_", " ")
            if key == "favourite_dish":
                pretty = f"favourite order: {pretty}"
            bundle.add(
                EvidenceAtom(text=pretty, provenance=f"{ref}.{key}", kind="customer", weight=weight)
            )
    age = identity.get("age_band")
    if isinstance(age, str) and age[:2].isdigit() and int(age[:2]) >= 60:
        bundle.add(
            EvidenceAtom(
                text="senior citizen", provenance="customer.identity.age_band", kind="customer", weight=86
            )
        )
    prefs = customer.get("preferences") or {}
    for key, label, weight in (
        ("preferred_slots", "prefers", 86),
        ("preferred_stylist", "prefers", 82),
        ("office_nearby", "", 60),
    ):
        value = prefs.get(key)
        if isinstance(value, str) and value.strip():
            pretty = value.replace("_", " ")
            if key == "preferred_slots":
                pretty = f"prefers {pretty}"
            elif key == "preferred_stylist":
                pretty = f"prefers {pretty}"
            bundle.add(
                EvidenceAtom(
                    text=pretty, provenance=f"customer.preferences.{key}", kind="preference", weight=weight
                )
            )


def evaluate_consent(customer: dict[str, Any] | None, trigger: dict[str, Any]) -> tuple[str | None, bool, str | None]:
    prefs = customer.get("preferences") or {}
    consent = customer.get("consent") or {}
    scope = consent.get("scope")
    if isinstance(scope, str):
        scope = [scope]
    if prefs.get("reminder_opt_in") is False:
        return ("customer preferences record reminder_opt_in=false", False,
                "hard block: the customer has opted out of reminders")
    if not isinstance(scope, list) or not [s for s in scope if str(s).strip()]:
        return ("customer has no recorded consent scope", False,
                "hard block: no consent scope on file, so no customer send is defensible")
    lowered = {str(s).strip().lower() for s in scope if str(s).strip()}
    kind = str(trigger.get("kind") or "")
    required = CONSENT_REQUIREMENTS.get(kind)
    if required is None:
        return (None, bool({"promotional_offers"} & lowered), None)
    if required.lower() in lowered:
        return (None, True, f"consent scope covers '{required}' for this trigger")
    if {"promotional_offers"} & lowered:
        return (None, True, f"no '{required}' scope, but promotional_offers is on file and no personal data is referenced")
    return (
        None,
        False,
        f"consent scope {sorted(lowered)} does not include '{required}'; sent as a plain service reminder with no offer, price or promotion",
    )


def detect_state_contradiction(customer: dict[str, Any] | None, trigger: dict[str, Any]) -> str | None:
    if customer is None:
        return None
    state = str(customer.get("state") or "").lower()
    kind = str(trigger.get("kind") or "")
    expected = TRIGGER_STATE_EXPECTATION.get(kind)
    if expected and state and state != expected:
        article = "an" if expected[:1] in "aeiou" else "a"
        return f"trigger '{kind}' implies {article} {expected} customer but the live customer record says '{state}'"
    return None


TRIGGER_STATE_EXPECTATION = {
    "recall_due": "lapsed_soft",
    "customer_lapsed_soft": "lapsed_soft",
    "customer_lapsed_hard": "lapsed_hard",
    "appointment_tomorrow": "active",
    "chronic_refill_due": "active",
    "trial_followup": "new",
}

CONSENT_REQUIREMENTS = {
    "recall_due": "recall_reminders",
    "appointment_tomorrow": "appointment_reminders",
    "chronic_refill_due": "refill_reminders",
    "customer_lapsed_hard": "winback_offers",
    "customer_lapsed_soft": "winback_offers",
    "trial_followup": "trial_followup",
}

BLOCKED_STATES = {"churned"}


def build_bundle(
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    now: datetime | None = None,
) -> EvidenceBundle:
    reference = now or datetime.now(timezone.utc)
    merchant = merchant if isinstance(merchant, dict) else {}
    trigger = trigger if isinstance(trigger, dict) else {}
    customer = customer if isinstance(customer, dict) else None

    bundle = EvidenceBundle(
        category_slug=(category or {}).get("slug") or merchant.get("category_slug"),
        merchant_id=merchant.get("merchant_id"),
        customer_id=(customer or {}).get("customer_id"),
        trigger_kind=trigger.get("kind"),
        trigger_scope=trigger.get("scope"),
        urgency=int(trigger.get("urgency") or 0) if isinstance(trigger.get("urgency"), int) else 0,
    )
    payload = trigger.get("payload") or {}
    bundle.is_placeholder_trigger = bool(isinstance(payload, dict) and payload.get("placeholder"))
    bundle.has_rich_trigger = not bundle.is_placeholder_trigger and bool(payload)

    extract_digest_atoms(bundle, category, trigger, reference)
    extract_trigger_payload_atoms(bundle, trigger, reference)
    extract_performance_atoms(bundle, merchant)
    extract_signal_atoms(bundle, merchant)
    extract_offer_atoms(bundle, merchant)
    extract_aggregate_atoms(bundle, merchant)
    extract_subscription_atoms(bundle, merchant)
    extract_category_atoms(bundle, category, reference)
    if customer is not None:
        extract_customer_atoms(bundle, customer, trigger, reference)
        bundle.consent_block, bundle.promo_allowed, bundle.consent_note = evaluate_consent(customer, trigger)
        bundle.contradiction = detect_state_contradiction(customer, trigger)
    return bundle
