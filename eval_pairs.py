"""Offline harness: push every canonical pair through the composer and print the drafts.

Run from the vera-bot directory:  python eval_pairs.py
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import normalize, strategies, validate
from app.context_store import ContextStore
from app.evidence import build_bundle
from app.render import voice_for

PACK = Path(r"C:\Users\dk732\Documents\Magicpin AI Challenge\challenge-pack")
EXPANDED = PACK / "expanded"
SEEDS = PACK / "dataset"


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(data, *keys):
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
        if any(k in data for k in ("slug", "merchant_id", "customer_id", "trigger_id", "id")):
            return [data]
    return []


def _index(rows, *keys):
    out = {}
    for row in rows:
        for key in keys:
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                out[value.strip()] = row
                break
    return out


def _load_dir(directory, *keys):
    rows = []
    if not directory.is_dir():
        return rows
    for path in sorted(directory.glob("*.json")):
        rows.extend(_rows(_read_json(path), *keys))
    return rows


def load_all():
    categories = _index(_load_dir(SEEDS / "categories", "category", "categories"), "slug", "category_slug")
    for row in _load_dir(EXPANDED / "categories", "category", "categories"):
        slug = row.get("slug") or row.get("category_slug")
        if isinstance(slug, str) and slug.strip():
            categories[slug.strip()] = row

    merchants = _index(
        _rows(_read_json(SEEDS / "merchants_seed.json"), "merchants", "merchant"), "merchant_id", "id"
    )
    customers = _index(
        _rows(_read_json(SEEDS / "customers_seed.json"), "customers", "customer"), "customer_id", "id"
    )
    triggers = _index(
        _rows(_read_json(SEEDS / "triggers_seed.json"), "triggers", "trigger"), "trigger_id", "id"
    )
    merchants.update(_index(_load_dir(EXPANDED / "merchants", "merchants", "merchant"), "merchant_id", "id"))
    customers.update(_index(_load_dir(EXPANDED / "customers", "customers", "customer"), "customer_id", "id"))
    triggers.update(_index(_load_dir(EXPANDED / "triggers", "triggers", "trigger"), "trigger_id", "id"))
    return categories, merchants, customers, triggers


def load_pairs():
    path = EXPANDED / "test_pairs.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        for key in ("test_pairs", "pairs", "cases"):
            if key in data and isinstance(data[key], list):
                return data[key]
        return []
    return data


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    categories, merchants, customers, triggers = load_all()
    pairs = load_pairs()
    print(f"loaded {len(categories)} categories, {len(merchants)} merchants, {len(customers)} customers, {len(triggers)} triggers")
    print(f"canonical pairs: {len(pairs)}\n")
    now = datetime.now(timezone.utc)
    suppressed = 0
    total = 0
    for pair in pairs:
        tid = pair.get("trigger_id") or pair.get("trigger")
        mid = pair.get("merchant_id") or pair.get("merchant")
        cid = pair.get("customer_id") or pair.get("customer")
        trigger = triggers.get(tid)
        merchant = merchants.get(mid)
        customer = customers.get(cid) if cid else None
        label = pair.get("id") or tid
        if trigger is None or merchant is None:
            print(f"[{label}] SKIP — missing trigger/merchant (t={tid} m={mid})")
            continue
        category = categories.get(normalize.merchant_category(merchant)) or categories.get(trigger.get("category_slug"))
        plan = strategies.plan_for_trigger(trigger, merchant, customer, category, now)
        bundle = build_bundle(category, merchant, trigger, customer, now)
        plan = validate.finalise(plan, bundle, merchant, customer)
        total += 1
        state = normalize.customer_state(customer) if customer else "-"
        consent = ",".join(normalize.consent_scope(customer)) if customer else "-"
        print(f"[{label}] {trigger.get('kind')} | {plan.channel} | m={mid} c={cid or '-'} state={state} consent=[{consent}]")
        if plan.suppressed:
            suppressed += 1
            print(f"   SUPPRESSED: {plan.suppress_reason}\n")
            continue
        print(f"   BODY ({plan.word_count}w): {plan.body}")
        print(f"   RATIONALE: {plan.rationale}")
        if bundle.contradiction:
            print(f"   CONTRADICTION: {bundle.contradiction}")
        if bundle.consent_note:
            print(f"   CONSENT: {bundle.consent_note}")
        print()
    print(f"=== {total} pairs, {suppressed} suppressed, {total - suppressed} drafted ===")


if __name__ == "__main__":
    main()
