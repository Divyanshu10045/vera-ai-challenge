from typing import Any, Callable

from . import normalize, render
from .evidence import EvidenceBundle, build_bundle, indian_group
from .plan import ActionPlan, suppressed
from .render import (
    VoiceProfile,
    all_texts,
    compose,
    count_text,
    first_atom,
    first_text,
    prune_to_budget,
    scrub,
    voice_for,
)

MERCHANT_CHANNEL = "merchant"
CUSTOMER_CHANNEL = "customer"

RATIONALE_MAX = 240

DIAGNOSTIC = "diagnostic"
ASSUMPTION = "assumption"
PROACTIVE = "proactive"
CONFIRMATORY = "confirmatory"
FOLLOW_UP = "follow_up"
REACTIVATION = "reactivation"
FACT = "fact"
RECOURSE = "recourse"
RECALL = "recall"
ASK = "ask"
REASSURANCE = "reassurance"
CONTRARIAN = "contrarian"
RESTRAINT = "restraint"
DEFERRAL = "deferral"
COMPLIANCE = "compliance"
COMMERCIAL = "commercial"


def _clip(text: str, limit: int = RATIONALE_MAX) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:") + "."


def _why(intent: str, judgement: str) -> str:
    return _clip(f"{intent}: {judgement}")


def _ctx(
    trigger: dict[str, Any] | None, merchant: dict[str, Any] | None, customer: dict[str, Any] | None
) -> dict[str, str]:
    return normalize.context_ids_for(trigger, merchant, customer)


def _tail(voice: VoiceProfile) -> str:
    return voice.closer()


def _lang(merchant: dict[str, Any] | None) -> str:
    return render.language_note(merchant)


def _loc(merchant: dict[str, Any] | None) -> str:
    return normalize.merchant_locality(merchant) or normalize.merchant_city(merchant)


def _owner_line(voice: VoiceProfile, owner: str | None) -> str:
    return voice.opener(owner)


def _active_offer(merchant: dict[str, Any] | None) -> str:
    for offer in normalize.offers(merchant):
        if str(offer.get("status") or "active").lower() != "active":
            continue
        title = str(offer.get("title") or "").strip()
        if title:
            return title
    return ""


def _offer_promo_text(bundle: EvidenceBundle) -> str:
    if not bundle.promo_allowed:
        return ""
    return all_texts(bundle, ("offer",), 1)[0] if bundle.has("offer") else ""


def _finalise_body(body: str, voice: VoiceProfile) -> str:
    return prune_to_budget(scrub(body, voice.taboos))


def _consent_rationale(bundle: EvidenceBundle, fallback: str) -> str:
    if bundle.consent_note:
        return bundle.consent_note
    return fallback


def _agreement(subject: str) -> str:
    head = subject.strip().split(" ", 1)[-1].lower() if subject.strip() else ""
    return "are" if head.endswith("s") and not head.endswith("ss") else "is"


def plan_research_digest(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    owner = render.owner_of(merchant)
    title = first_text(bundle, ("digest",))
    source = first_text(bundle, ("citation",))
    trial = first_text(bundle, ("trial",))
    credits = first_text(bundle, ("credit",))
    when = first_text(bundle, ("date",))
    deadline = first_text(bundle, ("deadline",))
    segment = first_text(bundle, ("segment",))
    cohort = first_text(bundle, ("signal",))
    perf = first_text(bundle, ("number", "delta"))

    if title and source:
        fragments = [f"{title} ({source})"]
        if when:
            fragments.append(f"dated {when}")
        elif deadline:
            fragments.append(deadline)
        if trial:
            fragments.append(f"it has run as a {trial}")
        if segment:
            fragments.append(f"the {segment} segment is the fit")
        if cohort:
            fragments.append(f"you already show {cohort}")
        if credits and len(fragments) < 3:
            fragments.append(f"there are {credits} on your account")
        ask = "want the two-line version"
        judgement = (
            "trigger pointed at a specific item, so cited that item with its source and effective date "
            "and matched it to a cohort already on the merchant's record instead of paraphrasing a generic digest"
        )
        intent = DIAGNOSTIC
    else:
        fragments = ["nothing in this week's clinical updates needs action for you today"]
        if perf:
            fragments.append(f"you have {perf}")
        ask = "want the next one only when it matches something you are doing"
        judgement = (
            "payload carried no resolvable item, so reported no-match rather than paraphrasing an advisory "
            "I cannot cite, and asked to keep the channel open"
        )
        intent = RESTRAINT

    body = _finalise_body(compose([_owner_line(voice, owner), *fragments], ask), voice)
    return ActionPlan(
        channel=MERCHANT_CHANNEL,
        kind="research_digest_update",
        shape="DIGEST_CITE",
        body=body,
        rationale=_why(intent, judgement),
        intents=[intent],
        citations=[source] if source else [],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:5]],
    )


def plan_perf_dip(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    owner = render.owner_of(merchant)
    drop = first_text(bundle, ("pct",))
    metric = first_text(bundle, ("topic",))
    current = first_atom(bundle, ("current",))
    baseline = first_atom(bundle, ("baseline",))
    delta = first_text(bundle, ("delta",))
    views = first_text(bundle, ("number",))
    signal = first_text(bundle, ("signal",))
    ask = "want me to test a different first line, or look at review replies first"

    if bundle.has_rich_trigger and drop:
        subject = metric or "your listing"
        fragments = [f"{subject} {_agreement(subject)} {drop} week-on-week"]
        if current is not None and current.num is not None:
            level = count_text(current, "view" if "view" in subject.lower() else "call")
            if level:
                fragments.append(f"you are at {level}")
        if baseline is not None and baseline.num is not None:
            base = count_text(baseline, "view" if "view" in subject.lower() else "call")
            if base:
                fragments.append(f"against a baseline of {base}")
        if signal:
            fragments.append(f"your record also shows {signal}")
        judgement = (
            "payload carried a measured drop, so led with the figure the merchant can verify, then offered "
            "two reversible levers rather than a rewrite they did not ask for"
        )
    else:
        lead = delta or signal or views
        fragments = [lead] if lead else ["your listing is underperforming its own recent baseline"]
        if signal and signal != lead:
            fragments.append(f"your record shows {signal}")
        judgement = (
            "no measured delta in the payload, so reported the live performance signal instead of claiming "
            "a cause the context does not support, and stopped at diagnosis"
        )

    body = _finalise_body(compose([_owner_line(voice, owner), *fragments], ask), voice)
    return ActionPlan(
        channel=MERCHANT_CHANNEL,
        kind="performance_alert",
        shape="PERF_OBSERVE",
        body=body,
        rationale=_why(DIAGNOSTIC, judgement),
        intents=[DIAGNOSTIC],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:5]],
    )


def plan_perf_spike(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    owner = render.owner_of(merchant)
    delta = first_text(bundle, ("delta",))
    views = first_text(bundle, ("number",))
    offer = _active_offer(merchant)
    fragments = [delta or views] if (delta or views) else ["your listing is trending up"]
    if offer:
        fragments.append(f"your {offer} is live right now")
    ask = "point the extra demand at that offer, or leave it organic"
    body = _finalise_body(compose([_owner_line(voice, owner), *fragments], ask), voice)
    return ActionPlan(
        channel=MERCHANT_CHANNEL,
        kind="performance_alert",
        shape="PERF_OBSERVE",
        body=body,
        rationale=_why(
            PROACTIVE,
            "momentum is merchant-verifiable, so treated the spike as a decision point rather than assuming "
            "they want more spend or more posting",
        ),
        intents=[PROACTIVE],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:5]],
    )


def plan_competitor(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    owner = render.owner_of(merchant)
    rival = first_text(bundle, ("name",))
    distance = first_text(bundle, ("number",))
    their_offer = first_text(bundle, ("offer",))
    locality = _loc(merchant)
    own = _active_offer(merchant)
    ask = "want a one-line differentiator from what you already run"

    if bundle.has_rich_trigger and rival:
        fragments = [f"{rival} opened {distance or 'nearby'}"]
        if their_offer:
            fragments.append(f"they are running {their_offer}")
        same_offer = bool(own) and bool(their_offer) and own.strip().lower() == their_offer.strip().lower()
        if same_offer:
            fragments.append("you are already at the same price, so price is the wrong angle")
        elif own:
            fragments.append(f"your {own} sits elsewhere")
        judgement = (
            "reported the opening as given with distance and their offer, kept it factual, and steered away "
            "from disparaging a competitor or recommending a price war"
        )
    else:
        fragments = [f"a new listing opened in {locality}" if locality else "a new listing opened nearby"]
        if own:
            fragments.append(f"you already run {own}")
        judgement = (
            "payload named no competitor, so said only that a listing opened nearby and offered help rather "
            "than inventing a rival, their price or their quality"
        )

    body = _finalise_body(compose([_owner_line(voice, owner), *fragments], ask), voice)
    return ActionPlan(
        channel=MERCHANT_CHANNEL,
        kind="competitor_alert",
        shape="COMPETITOR_NEUTRAL",
        body=body,
        rationale=_why(COMMERCIAL, judgement),
        intents=[COMMERCIAL],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:5]],
    )


def plan_curious_ask(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    owner = render.owner_of(merchant)
    ask_atom = first_text(bundle, ("topic",))
    topic = (ask_atom or "").replace("the most-asked service this week", "").strip()
    question = "quick one — which service is in most demand from your customers this week?"
    if topic and topic.lower() not in {"ask", "question"}:
        question = f"{question[:-1]} — i had {topic} in mind?"
    ask = "i can turn that into a short weekly brief you set the pace on, want me to"
    body = _finalise_body(compose([_owner_line(voice, owner), question, _lang(merchant)], ask), voice)
    return ActionPlan(
        channel=MERCHANT_CHANNEL,
        kind="curiosity_prompt",
        shape="ASK_MERCHANT",
        body=body,
        rationale=_why(
            ASK,
            "one open question only the merchant can answer, with an opt-in to a recurring brief; no offer "
            "attached because the answer is the point, not a conversion",
        ),
        intents=[ASK],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:3]],
    )


def plan_seasonal(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    owner = render.owner_of(merchant)
    festival = first_text(bundle, ("topic",))
    when = first_text(bundle, ("date",))
    countdown = first_atom(bundle, ("countdown",))
    seasonal = first_text(bundle, ("seasonal",))
    trend = first_text(bundle, ("trend",))
    offer = _active_offer(merchant)
    ask = "hold a few slots around it, or leave that with you"

    if bundle.has_rich_trigger and festival and when:
        fragments = [f"{festival} is on {when}"]
        if countdown is not None and countdown.num is not None:
            fragments.append(f"that is {count_text(countdown)} out")
        if seasonal or trend:
            fragments.append(seasonal or trend)
        if offer:
            fragments.append(f"your {offer} fits that window")
        judgement = (
            "anchored to the dated event in the payload plus one seasonal pattern, then asked about capacity "
            "instead of pushing a campaign nobody requested"
        )
    else:
        anchor = seasonal or trend
        fragments = [anchor] if anchor else [f"{festival} is coming up" if festival else "this season has a pattern worth noting"]
        if offer:
            fragments.append(f"your {offer} is still live")
        judgement = (
            "no date in the payload, so used the category's own seasonal beat and asked about capacity rather "
            "than inventing a festival date or manufacturing urgency"
        )

    body = _finalise_body(compose([_owner_line(voice, owner), *fragments], ask), voice)
    return ActionPlan(
        channel=MERCHANT_CHANNEL,
        kind="seasonal_planning",
        shape="SEASONAL_TIE",
        body=body,
        rationale=_why(PROACTIVE, judgement),
        intents=[PROACTIVE],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:5]],
    )


def plan_milestone(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    owner = render.owner_of(merchant)
    metric = first_text(bundle, ("topic",))
    current = first_atom(bundle, ("current",))
    target = first_atom(bundle, ("target",))
    lapsed = first_atom(bundle, ("lapsed",))
    signal = first_text(bundle, ("signal",))
    ask = "mark it publicly, or quietly reach the customers who went quiet"

    if bundle.has_rich_trigger and current is not None and current.num is not None:
        subject = metric or "your listing"
        reach = indian_group(int(current.num))
        fragments = [f"{subject} is at {reach}"]
        shortfall = False
        if target is not None and target.num is not None:
            if current.num >= target.num:
                fragments.append(f"past the {indian_group(int(target.num))} mark")
            else:
                gap_value = indian_group(int(target.num - current.num))
                fragments.append(f"{gap_value} short of the {indian_group(int(target.num))} mark")
                shortfall = True
        if lapsed is not None and lapsed.num is not None:
            fragments.append(f"{indian_group(int(lapsed.num))} customers have lapsed since you started")
        if signal:
            fragments.append(f"and your record shows {signal}")
        ask = (
            "want me to hold reminders for the ones due, or leave it"
            if shortfall
            else "mark it publicly, or quietly reach the customers who went quiet"
        )
        judgement = (
            "the payload's own numbers put the metric below the stated milestone, so reported the shortfall "
            "instead of congratulating the merchant on a threshold they have not crossed"
            if shortfall
            else "milestone is trigger-verifiable, so acknowledged it briefly and handed over the visibility-versus-reactivation choice"
        )
    else:
        lead = signal or first_text(bundle, ("number", "delta"))
        fragments = [lead] if lead else ["noted a milestone on your listing"]
        if lapsed is not None and lapsed.num is not None:
            fragments.append(f"you have {indian_group(int(lapsed.num))} lapsed customers")
        judgement = "milestone value absent from the payload, so flagged it without inventing a number and asked which response they want"

    body = _finalise_body(compose([_owner_line(voice, owner), *fragments], ask), voice)
    return ActionPlan(
        channel=MERCHANT_CHANNEL,
        kind="milestone",
        shape="MILESTONE",
        body=body,
        rationale=_why(FACT, judgement),
        intents=[FACT],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:5]],
    )


def plan_dormancy(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    owner = render.owner_of(merchant)
    gap = first_atom(bundle, ("gap",))
    last_topic = first_text(bundle, ("topic",))
    status = first_text(bundle, ("status",))
    history = normalize.conversation_history(merchant)
    silence = count_text(gap)
    fragments = [f"it has been {silence} since your last message" if silence else ("we have not spoken in a while" if history else "it has been a while")]
    if last_topic:
        fragments.append(f"the last thread was {last_topic}")
    if status:
        fragments.append(status)
    ask = "go quiet until something real changes, or check in monthly"
    body = _finalise_body(compose([_owner_line(voice, owner), *fragments], ask), voice)
    return ActionPlan(
        channel=MERCHANT_CHANNEL,
        kind="engagement_checkin",
        shape="DORMANCY",
        body=body,
        rationale=_why(
            FOLLOW_UP,
            "a long silence plus an inactive subscription makes silence the right default, so offered the "
            "merchant an explicit cadence choice instead of manufacturing urgency",
        ),
        intents=[FOLLOW_UP],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:5]],
    )


def plan_planning_intent(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    owner = render.owner_of(merchant)
    quote = first_text(bundle, ("quote",))
    topic = first_text(bundle, ("topic",))
    fragments = []
    if quote:
        fragments.append(f'you wrote "{quote.strip().rstrip("?.")}"')
    elif topic:
        fragments.append(f"you are working through {topic}")
    fragments.append("adding nothing on top of it")
    body = _finalise_body(
        compose([_owner_line(voice, owner), *fragments], "want me to put a draft together"), voice
    )
    return ActionPlan(
        channel=MERCHANT_CHANNEL,
        kind="planning_note",
        shape="PLANNING_HOLD",
        body=body,
        rationale=_why(
            DEFERRAL,
            "merchant is mid-decision, so acknowledged without pitching; adding a commercial angle here would "
            "have interrupted an intent transition they opened themselves",
        ),
        intents=[DEFERRAL],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:3]],
    )


def plan_verification(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    owner = render.owner_of(merchant)
    path = first_text(bundle, ("topic",))
    signal = first_text(bundle, ("signal",))
    calls = first_text(bundle, ("number",))
    ask = "want the exact steps, or should I just watch for it to change"

    if bundle.has_rich_trigger and path:
        fragments = ["customers currently see your listing as unverified", f"{path} is the fix"]
        if calls:
            fragments.append(f"you had {calls} in the last 30 days")
        judgement = (
            "a fact the merchant can check themselves, plus the path the trigger supplied; framed as the usual "
            "effect rather than a promised lift"
        )
    else:
        fragments = ["your listing is still unverified, which is why you show up less often nearby"]
        if signal:
            fragments.append(f"your record shows {signal}")
        judgement = "payload had no verification path, so named the problem and asked before prescribing steps"

    body = _finalise_body(compose([_owner_line(voice, owner), *fragments], ask), voice)
    return ActionPlan(
        channel=MERCHANT_CHANNEL,
        kind="profile_health",
        shape="VERIFY_FACT",
        body=body,
        rationale=_why(FACT, judgement),
        intents=[FACT],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:5]],
    )


def plan_event_contrarian(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    owner = render.owner_of(merchant)
    venue = first_text(bundle, ("topic",))
    payload = normalize.trigger_payload(trigger)
    is_weeknight = payload.get("is_weeknight")
    festival = first_text(bundle, ("topic",))
    perf = first_text(bundle, ("number", "delta"))
    label = venue or "the match"
    ask = "boost tonight, or hold it"

    if is_weeknight is True:
        fragments = [f"{label} is on tonight, and it is a weeknight"]
        if perf:
            fragments.append(f"you had {perf}")
        fragments.append("a match-day post works here only if someone is on the floor")
        judgement = (
            "weeknight plus a match is the one case where the obvious play is right, so gave the condition it "
            "depends on instead of pushing it unconditionally"
        )
    else:
        fragments = [f"{label} is on tonight, but it is a weekday"]
        if perf:
            fragments.append(f"you had {perf}")
        fragments.append(f"i would hold it for {festival}" if festival else "i would hold it for the weekend")
        judgement = (
            "recommended against the obvious play: a weekday event against soft demand is a poor fit, so "
            "advised holding rather than manufacturing urgency to look responsive"
        )

    body = _finalise_body(compose([_owner_line(voice, owner), *fragments], ask), voice)
    return ActionPlan(
        channel=MERCHANT_CHANNEL,
        kind="event_opportunity",
        shape="CONTRARIAN",
        body=body,
        rationale=_why(CONTRARIAN, judgement),
        intents=[CONTRARIAN],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:5]],
    )


def plan_renewal(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    owner = render.owner_of(merchant)
    sub = normalize.subscription(merchant)
    plan_name = str(sub.get("plan") or "").strip()
    status = first_text(bundle, ("status",))
    amount = first_text(bundle, ("money",))
    members = first_text(bundle, ("number",))
    fragments = [status or (f"your {plan_name} plan is up for renewal" if plan_name else "your plan is up for renewal")]
    if amount:
        fragments.append(f"it comes to {amount} for the year")
    if members:
        fragments.append(f"you have {members} on the platform")
    ask = "want the renewal summary before you decide"
    body = _finalise_body(compose([_owner_line(voice, owner), *fragments], ask), voice)
    return ActionPlan(
        channel=MERCHANT_CHANNEL,
        kind="renewal_notice",
        shape="RENEWAL",
        body=body,
        rationale=_why(
            COMMERCIAL,
            "renewal is a commercial conversation, so stated the terms and what is at stake and stopped there "
            "rather than stacking a second ask on top",
        ),
        intents=[COMMERCIAL],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:5]],
    )


def _customer_gate(
    bundle: EvidenceBundle, customer: dict[str, Any] | None
) -> ActionPlan | None:
    state = normalize.customer_state(customer)
    if bundle.consent_block:
        return suppressed(CUSTOMER_CHANNEL, "customer_message", bundle.consent_block)
    if state == "churned":
        return suppressed(
            CUSTOMER_CHANNEL,
            "customer_message",
            "customer is recorded as churned; re-permissioning a lapsed relationship is a human decision, "
            "not an automated winback",
        )
    return None


def plan_recall(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    gate = _customer_gate(bundle, customer)
    if gate:
        return gate
    who = render.customer_name(customer)
    service = first_text(bundle, ("topic",))
    since = first_text(bundle, ("customer",))
    slots = first_text(bundle, ("slot",))
    promo = _offer_promo_text(bundle)
    fragments = []
    if since and service:
        fragments.append(f"it has been {since} since your last {service}")
    elif since:
        fragments.append(f"it has been {since}")
    if promo:
        fragments.append(f"{promo} is running if you want to rebook")
    ask = f"i can hold {slots}" if slots else "want me to hold a slot"
    body = _finalise_body(compose([voice.opener(who), *fragments], ask), voice)
    rationale = _why(
        RECALL,
        _consent_rationale(
            bundle,
            "recall timing and reminder consent are both on file, so one low-friction slot offer and nothing more",
        ),
    )
    if bundle.contradiction:
        rationale = _clip(f"{rationale}. Note: {bundle.contradiction}, so the live record was trusted")
    return ActionPlan(
        channel=CUSTOMER_CHANNEL,
        kind="recall_reminder",
        shape="RECALL_OFFER",
        body=body,
        rationale=rationale,
        intents=[RECOURSE],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:5]],
    )


def plan_lapse(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    gate = _customer_gate(bundle, customer)
    if gate:
        return gate
    who = render.customer_name(customer)
    state = normalize.customer_state(customer)
    since = first_text(bundle, ("customer",))
    focus = first_text(bundle, ("topic",))
    promo = _offer_promo_text(bundle)
    lead = f"it has been {since}" if since else "it has been a while"
    fragments = [lead + (f" since your last {focus}" if focus else " since your last visit")]
    if promo:
        fragments.append(f"you have {promo} running")
    if state == "lapsed_hard":
        ask = "want me to check in twice a year, or stop entirely"
    else:
        ask = "still on the list, or should i pause reminders"
    body = _finalise_body(compose([voice.opener(who), *fragments], ask), voice)
    judgement = _consent_rationale(
        bundle,
        "long gap, so a no-pressure check-in that offers to stop as easily as to rebook",
    )
    if state in {"lapsed_hard", "churned"} and "soft" in str(bundle.trigger_kind or ""):
        judgement = "live record shows a longer lapse than the trigger assumed, so used the gentler long-gap framing"
    return ActionPlan(
        channel=CUSTOMER_CHANNEL,
        kind="winback_checkin",
        shape="WINBACK_LOWFREQ",
        body=body,
        rationale=_why(REACTIVATION, judgement),
        intents=[RECOURSE],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:5]],
    )


def plan_appointment(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    gate = _customer_gate(bundle, customer)
    if gate:
        return gate
    state = normalize.customer_state(customer)
    if bundle.contradiction and state in {"lapsed_soft", "lapsed_hard", "churned", "new"}:
        return suppressed(
            CUSTOMER_CHANNEL,
            "appointment_reminder",
            f"trigger asserts a booked appointment but the live record shows '{state}'; a reminder for an "
            "appointment I cannot confirm would be worse than saying nothing",
        )
    who = render.customer_name(customer)
    when = first_text(bundle, ("date",))
    pref = first_text(bundle, ("preference",))
    fragments = ["a quick reminder about tomorrow"]
    if when and "at" in when.lower():
        fragments.append(f"you are booked {when}")
    if pref:
        fragments.append(f"you usually come in {pref}")
    ask = "reply to confirm, or tell me if you need a different time"
    body = _finalise_body(compose([voice.opener(who), *fragments], ask), voice)
    return ActionPlan(
        channel=CUSTOMER_CHANNEL,
        kind="appointment_reminder",
        shape="APPT_CONFIRM",
        body=body,
        rationale=_why(
            REASSURANCE,
            _consent_rationale(
                bundle,
                "appointment reminders are on file, so a purely transactional confirm with an easy reschedule "
                "path and no promotion attached",
            ),
        ),
        intents=[REASSURANCE],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:4]],
    )


def plan_refill(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    gate = _customer_gate(bundle, customer)
    if gate:
        return gate
    who = render.customer_name(customer)
    molecules = first_text(bundle, ("list",))
    runout = first_text(bundle, ("date",))
    affected = first_text(bundle, ("list",))
    name = render.reference_of(category, merchant)
    lead = f"your {molecules} refill is due" if molecules else "your refill is due"
    fragments = [lead]
    if runout:
        fragments.append(f"{name} may run out around {runout}")
    elif affected:
        fragments.append(f"{name} has {affected} short")
    if voice.is_clinical:
        fragments.append(f"{render.contact_hint(voice, category)} can confirm the timing")
    ask = "want me to set one aside for pickup"
    body = _finalise_body(compose([voice.opener(who), *fragments], ask), voice)
    return ActionPlan(
        channel=CUSTOMER_CHANNEL,
        kind="refill_reminder",
        shape="REFILL_RUNOUT",
        body=body,
        rationale=_why(
            REASSURANCE,
            _consent_rationale(
                bundle,
                "medication and stock facts only, routed to the pharmacist for anything clinical; no dose, "
                "condition or safety claim was made on the customer's behalf",
            ),
        ),
        intents=[REASSURANCE],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:5]],
    )


def plan_trial_followup(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    gate = _customer_gate(bundle, customer)
    if gate:
        return gate
    who = render.customer_name(customer)
    topic = first_text(bundle, ("topic",))
    next_step = first_text(bundle, ("topic",))
    fragments = [f"how did the {topic} go" if topic else "how did it go"]
    ask = f"if it fits, {next_step}" if next_step else "if it fits, i can line up the next step"
    if not bundle.promo_allowed:
        fragments.append("if not, tell me and i will not bring it up again")
        ask = "want me to check in once more, or leave it there"
    body = _finalise_body(compose([voice.opener(who), *fragments], ask), voice)
    return ActionPlan(
        channel=CUSTOMER_CHANNEL,
        kind="trial_followup",
        shape="TRIAL_CHECKIN",
        body=body,
        rationale=_why(
            FOLLOW_UP,
            _consent_rationale(
                bundle,
                "a single visit with no purchase history, so asked how it went and made declining the easy path",
            ),
        ),
        intents=[FOLLOW_UP],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:4]],
    )


def plan_generic_merchant(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    owner = render.owner_of(merchant)
    lead = first_text(bundle, ("digest", "delta", "signal", "pct", "number", "topic"))
    perf = first_text(bundle, ("number", "delta"))
    fragments = [lead] if lead else ["something changed on your listing that i have not seen before"]
    if perf and perf != lead:
        fragments.append(perf)
    ask = "want me to do anything with it, or just keep watching"
    body = _finalise_body(compose([_owner_line(voice, owner), *fragments], ask), voice)
    return ActionPlan(
        channel=MERCHANT_CHANNEL,
        kind="observation",
        shape="GENERIC_OBSERVE",
        body=body,
        rationale=_why(
            PROACTIVE,
            f"no dedicated strategy for trigger kind '{bundle.trigger_kind}', so reported only "
            "merchant-verifiable facts and asked rather than guessing at intent",
        ),
        intents=[PROACTIVE],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:5]],
    )


def plan_generic_customer(
    bundle: EvidenceBundle,
    category: dict[str, Any] | None,
    merchant: dict[str, Any] | None,
    trigger: dict[str, Any] | None,
    customer: dict[str, Any] | None,
    voice: VoiceProfile,
) -> ActionPlan:
    gate = _customer_gate(bundle, customer)
    if gate:
        return gate
    who = render.customer_name(customer)
    lead = first_text(bundle, ("customer", "topic", "date"))
    ask = "want me to hold something for you, or is this fine as it is"
    body = _finalise_body(compose([voice.opener(who), lead or "just checking in"], ask), voice)
    return ActionPlan(
        channel=CUSTOMER_CHANNEL,
        kind="customer_checkin",
        shape="GENERIC_CHECKIN",
        body=body,
        rationale=_why(
            FOLLOW_UP,
            f"no dedicated strategy for customer trigger '{bundle.trigger_kind}'; used relationship facts only "
            "and kept the ask reversible",
        ),
        intents=[FOLLOW_UP],
        context_ids=_ctx(trigger, merchant, customer),
        evidence=[a.text for a in bundle.ranked()[:4]],
    )


MERCHANT_STRATEGIES: dict[str, Callable[..., ActionPlan]] = {
    "research_digest": plan_research_digest,
    "regulation_change": plan_research_digest,
    "cde_opportunity": plan_research_digest,
    "perf_dip": plan_perf_dip,
    "perf_spike": plan_perf_spike,
    "competitor_opened": plan_competitor,
    "competitor_promoting": plan_competitor,
    "curious_ask_due": plan_curious_ask,
    "festival_upcoming": plan_seasonal,
    "category_seasonal": plan_seasonal,
    "seasonal_demand_shift": plan_seasonal,
    "milestone_reached": plan_milestone,
    "dormant_with_vera": plan_dormancy,
    "active_planning_intent": plan_planning_intent,
    "gbp_unverified": plan_verification,
    "ipl_match_today": plan_event_contrarian,
    "renewal_due": plan_renewal,
    "winback_eligible": plan_renewal,
    "supply_alert": plan_verification,
    "profile_health": plan_verification,
}

CUSTOMER_STRATEGIES: dict[str, Callable[..., ActionPlan]] = {
    "recall_due": plan_recall,
    "appointment_tomorrow": plan_appointment,
    "customer_lapsed_soft": plan_lapse,
    "customer_lapsed_hard": plan_lapse,
    "chronic_refill_due": plan_refill,
    "trial_followup": plan_trial_followup,
    "service_followup": plan_trial_followup,
}


def plan_for_trigger(
    trigger: dict[str, Any],
    merchant: dict[str, Any],
    customer: dict[str, Any] | None,
    category: dict[str, Any] | None,
    now=None,
) -> ActionPlan:
    bundle = build_bundle(category, merchant, trigger, customer, now)
    voice = voice_for(category, merchant)
    channel = str(trigger.get("channel") or "").strip().lower()
    if channel not in (MERCHANT_CHANNEL, CUSTOMER_CHANNEL):
        channel = (
            CUSTOMER_CHANNEL
            if (normalize.trigger_customer_id(trigger) or bundle.customer_id)
            else MERCHANT_CHANNEL
        )
    registry = CUSTOMER_STRATEGIES if channel == CUSTOMER_CHANNEL else MERCHANT_STRATEGIES
    strategy = registry.get(str(bundle.trigger_kind or ""))
    if strategy is None:
        strategy = plan_generic_customer if channel == CUSTOMER_CHANNEL else plan_generic_merchant
    return strategy(bundle, category, merchant, trigger, customer, voice)
