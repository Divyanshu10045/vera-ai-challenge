from typing import Any

MISSING = object()


def _section(payload: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def merchant_identity(merchant: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(merchant, dict):
        return {}
    nested = _section(merchant, "identity")
    if nested:
        merged = dict(nested)
        for key, value in merchant.items():
            if key != "identity" and key not in merged and isinstance(value, (str, int, float, bool)):
                merged[key] = value
        return merged
    return merchant


def merchant_name(merchant: dict[str, Any] | None) -> str:
    value = merchant_identity(merchant).get("name")
    return str(value).strip() if isinstance(value, str) and value.strip() else ""


def merchant_owner(merchant: dict[str, Any] | None) -> str:
    value = merchant_identity(merchant).get("owner_first_name")
    return str(value).strip() if isinstance(value, str) and value.strip() else ""


def merchant_locality(merchant: dict[str, Any] | None) -> str:
    identity = merchant_identity(merchant)
    for key in ("locality", "city"):
        value = identity.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def merchant_city(merchant: dict[str, Any] | None) -> str:
    identity = merchant_identity(merchant)
    for key in ("city", "locality"):
        value = identity.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def merchant_languages(merchant: dict[str, Any] | None) -> list[str]:
    value = merchant_identity(merchant).get("languages")
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def merchant_verified(merchant: dict[str, Any] | None) -> bool:
    return bool(merchant_identity(merchant).get("verified"))


def merchant_id(merchant: dict[str, Any] | None) -> str:
    if not isinstance(merchant, dict):
        return ""
    value = merchant.get("merchant_id") or merchant.get("id")
    return str(value) if isinstance(value, str) else ""


def merchant_category(merchant: dict[str, Any] | None) -> str:
    if not isinstance(merchant, dict):
        return ""
    for key in ("category_slug", "category", "vertical"):
        value = merchant.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def performance(merchant: dict[str, Any] | None) -> dict[str, Any]:
    return _section(merchant, "performance")


def signals(merchant: dict[str, Any] | None) -> list[str]:
    if not isinstance(merchant, dict):
        return []
    value = merchant.get("signals")
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, str) and v.strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def offers(merchant: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(merchant, dict):
        return []
    value = merchant.get("offers")
    if isinstance(value, list):
        return [o for o in value if isinstance(o, dict)]
    return []


def subscription(merchant: dict[str, Any] | None) -> dict[str, Any]:
    return _section(merchant, "subscription")


def aggregate(merchant: dict[str, Any] | None) -> dict[str, Any]:
    return _section(merchant, "customer_aggregate")


def conversation_history(merchant: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(merchant, dict):
        return []
    value = merchant.get("conversation_history")
    if isinstance(value, list):
        return [h for h in value if isinstance(h, dict)]
    return []


def trigger_payload(trigger: dict[str, Any] | None) -> dict[str, Any]:
    return _section(trigger, "payload")


def trigger_id(trigger: dict[str, Any] | None) -> str:
    if not isinstance(trigger, dict):
        return ""
    for key in ("trigger_id", "id", "context_id"):
        value = trigger.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def trigger_merchant_id(trigger: dict[str, Any] | None) -> str:
    if not isinstance(trigger, dict):
        return ""
    for key in ("merchant_id", "merchant_ref"):
        value = trigger.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def trigger_customer_id(trigger: dict[str, Any] | None) -> str:
    if not isinstance(trigger, dict):
        return ""
    for key in ("customer_id", "customer_ref"):
        value = trigger.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def customer_id(customer: dict[str, Any] | None) -> str:
    if not isinstance(customer, dict):
        return ""
    for key in ("customer_id", "id", "context_id"):
        value = customer.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def customer_identity(customer: dict[str, Any] | None) -> dict[str, Any]:
    return _section(customer, "identity")


def customer_relationship(customer: dict[str, Any] | None) -> dict[str, Any]:
    return _section(customer, "relationship")


def customer_preferences(customer: dict[str, Any] | None) -> dict[str, Any]:
    return _section(customer, "preferences")


def customer_consent(customer: dict[str, Any] | None) -> dict[str, Any]:
    return _section(customer, "consent")


def customer_state(customer: dict[str, Any] | None) -> str:
    if not isinstance(customer, dict):
        return ""
    value = customer.get("state") or customer.get("lifecycle_state")
    return str(value).strip().lower() if isinstance(value, str) else ""


HONORIFICS = {
    "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "miss", "dr", "dr.", "prof", "prof.",
    "shri", "smt", "md", "phd", "bds", "mbbs", "mrs", "sir", "madam",
}


def _strip_honorific(name: str) -> str:
    parts = name.split()
    while parts and parts[0].strip(".").lower() in {h.strip(".") for h in HONORIFICS}:
        parts.pop(0)
    return " ".join(parts).strip()


def customer_name(customer: dict[str, Any] | None) -> str:
    identity = customer_identity(customer)
    for key in ("name", "first_name", "display_name"):
        value = identity.get(key)
        if isinstance(value, str) and value.strip():
            cleaned = value.strip().split("(")[0].strip()
            without_honorific = _strip_honorific(cleaned)
            return without_honorific or cleaned
    return ""


def customer_age_band(customer: dict[str, Any] | None) -> str:
    value = customer_identity(customer).get("age_band")
    return str(value) if isinstance(value, str) else ""


def customer_channel(customer: dict[str, Any] | None) -> str:
    value = customer_preferences(customer).get("channel")
    return str(value) if isinstance(value, str) and value.strip() else "whatsapp"


def consent_scope(customer: dict[str, Any] | None) -> list[str]:
    value = customer_consent(customer).get("scope")
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def reminder_opt_in(customer: dict[str, Any] | None) -> bool:
    value = customer_preferences(customer).get("reminder_opt_in")
    if isinstance(value, bool):
        return value
    return True


def customer_category_from_id(customer: dict[str, Any] | None) -> str:
    return ""


def context_ids_for(
    trigger: dict[str, Any] | None, merchant: dict[str, Any] | None, customer: dict[str, Any] | None
) -> dict[str, str]:
    ids: dict[str, str] = {}
    tid = trigger_id(trigger)
    if tid:
        ids["trigger_id"] = tid
    mid = merchant_id(merchant) or trigger_merchant_id(trigger)
    if mid:
        ids["merchant_id"] = mid
    cid = customer_id(customer) or trigger_customer_id(trigger)
    if cid:
        ids["customer_id"] = cid
    return ids
