"""Adversarial protocol and behaviour tests.

Covers the endpoint contract, context versioning, the four documented judge traps,
and the grounding rules. Run: .venv\\Scripts\\python.exe -m pytest tests -q
"""
import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402

PACK = Path(r"C:\Users\dk732\Documents\Magicpin AI Challenge\challenge-pack")
EXPANDED = PACK / "expanded"
SEEDS = PACK / "dataset"

PROGRESS_WORDS = ("done", "sending", "draft", "here", "confirm", "proceed", "next")
BANNED_REPLY_PHRASES = ("would you", "do you", "can you tell", "what if", "how about")
JARGON = ("trigger", "payload", "context_id", "urgency", "consent scope", "evidence atom", "provenance")


def _rows(data, *keys):
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), list):
                return [r for r in data[key] if isinstance(r, dict)]
        if any(k in data for k in ("slug", "merchant_id", "customer_id", "trigger_id", "id")):
            return [data]
    return []


def _index(rows, *keys):
    out = {}
    for row in rows:
        for key in keys:
            if isinstance(row.get(key), str) and row[key].strip():
                out[row[key].strip()] = row
                break
    return out


def _load_dir(directory, *keys):
    rows = []
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            rows.extend(_rows(json.loads(path.read_text(encoding="utf-8")), *keys))
    return rows


@pytest.fixture(scope="session")
def dataset():
    categories = _index(_load_dir(SEEDS / "categories", "category", "categories"), "slug", "category_slug")
    for row in _load_dir(EXPANDED / "categories", "category", "categories"):
        if isinstance(row.get("slug"), str):
            categories[row["slug"]] = row
    merchants = _index(_rows(json.loads((SEEDS / "merchants_seed.json").read_text(encoding="utf-8")), "merchants"), "merchant_id", "id")
    customers = _index(_rows(json.loads((SEEDS / "customers_seed.json").read_text(encoding="utf-8")), "customers"), "customer_id", "id")
    triggers = _index(_rows(json.loads((SEEDS / "triggers_seed.json").read_text(encoding="utf-8")), "triggers"), "trigger_id", "id")
    merchants.update(_index(_load_dir(EXPANDED / "merchants", "merchants"), "merchant_id", "id"))
    customers.update(_index(_load_dir(EXPANDED / "customers", "customers"), "customer_id", "id"))
    triggers.update(_index(_load_dir(EXPANDED / "triggers", "triggers"), "trigger_id", "id"))
    return {"categories": categories, "merchants": merchants, "customers": customers, "triggers": triggers}


@pytest.fixture(scope="session")
def pairs():
    data = json.loads((EXPANDED / "test_pairs.json").read_text(encoding="utf-8"))
    if isinstance(data, dict):
        for key in ("test_pairs", "pairs", "cases"):
            if isinstance(data.get(key), list):
                return data[key]
        return []
    return data


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.post("/v1/reset")
        yield c
        c.post("/v1/reset")


@pytest.fixture()
def loaded(client, dataset):
    for slug, payload in dataset["categories"].items():
        client.post("/v1/context", json={"scope": "category", "context_id": slug, "version": 1, "payload": payload})
    for mid, payload in dataset["merchants"].items():
        client.post("/v1/context", json={"scope": "merchant", "context_id": mid, "version": 1, "payload": payload})
    for cid, payload in dataset["customers"].items():
        client.post("/v1/context", json={"scope": "customer", "context_id": cid, "version": 1, "payload": payload})
    return client


def _push(client, dataset, trigger_id):
    trigger = dataset["triggers"][trigger_id]
    client.post(
        "/v1/context",
        json={"scope": "trigger", "context_id": trigger_id, "version": 1, "payload": trigger},
    )
    return trigger


def test_healthz(client):
    r = client.get("/v1/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_metadata(client):
    r = client.get("/v1/metadata")
    assert r.status_code == 200
    body = r.json()
    for key in ("team_name", "model", "approach"):
        assert key in body and body[key]


def test_context_accepts_and_rejects_stale(client):
    r = client.post("/v1/context", json={"scope": "category", "context_id": "dentists", "version": 1, "payload": {"slug": "dentists"}})
    assert r.status_code == 200 and r.json()["accepted"] is True
    stale = client.post("/v1/context", json={"scope": "category", "context_id": "dentists", "version": 1, "payload": {"slug": "dentists"}})
    assert stale.status_code == 409 and stale.json()["reason"] == "stale_version"
    same = client.post("/v1/context", json={"scope": "category", "context_id": "dentists", "version": 0, "payload": {"slug": "dentists"}})
    assert same.status_code == 409
    newer = client.post("/v1/context", json={"scope": "category", "context_id": "dentists", "version": 2, "payload": {"slug": "dentists", "voice": {}}})
    assert newer.status_code == 200 and newer.json()["accepted"] is True


def test_context_rejects_bad_input(client):
    assert client.post("/v1/context", json={"scope": "nope", "context_id": "x", "version": 1, "payload": {}}).status_code == 400
    assert client.post("/v1/context", json={"scope": "category", "context_id": "", "version": 1, "payload": {}}).status_code == 400
    assert client.post("/v1/context", json={"scope": "category", "context_id": "a", "version": -1, "payload": {}}).status_code == 400
    assert client.post("/v1/context", content=b"not json").status_code == 400


def test_tick_returns_wellformed_actions(loaded, dataset, pairs):
    pair = pairs[0]
    tid = pair.get("trigger_id")
    _push(loaded, dataset, tid)
    r = loaded.post("/v1/tick", json={"trigger_ids": [tid]})
    assert r.status_code == 200
    actions = r.json()["actions"]
    for action in actions:
        assert action["trigger_id"] == tid
        assert action["merchant_id"]
        assert action["body"].strip()
        assert action["channel"] in {"merchant", "customer"}
        assert len(action["body"]) <= 480
        assert len([w for w in action["body"].split() if w]) <= 36
        assert action["rationale"].strip()


def test_no_banned_content_in_any_message(loaded, dataset, pairs):
    trigger_ids = [p.get("trigger_id") for p in pairs if p.get("trigger_id")]
    for tid in trigger_ids:
        if tid not in dataset["triggers"]:
            continue
        _push(loaded, dataset, tid)
    r = loaded.post("/v1/tick", json={"trigger_ids": trigger_ids})
    seen = 0
    for action in r.json()["actions"]:
        body = action["body"]
        seen += 1
        assert not re.search(r"https?://|www\.", body, re.I), body
        lowered = body.lower()
        for word in ("guaranteed", "guarantee", "miracle", "best in city", "no.1", "cheapest", "100%", "risk-free"):
            assert word not in lowered, f"{word} in: {body}"
        for term in JARGON:
            assert term not in lowered, f"jargon {term} in: {body}"
        for phrase in ("would you", "can you tell", "what if", "how about"):
            assert phrase not in lowered, f"phrase {phrase} in: {body}"
    assert seen > 0, "expected at least one drafted action"


def test_reply_intent_transition_carries_progress_word(loaded, dataset, pairs):
    pair = next(p for p in pairs if p.get("merchant_id") and p.get("trigger_id"))
    tid, mid = pair["trigger_id"], pair["merchant_id"]
    _push(loaded, dataset, tid)
    loaded.post("/v1/tick", json={"trigger_ids": [tid]})
    r = loaded.post(
        "/v1/reply",
        json={"conversation_id": "conv_t1", "merchant_id": mid, "from_role": "merchant", "message": "Yes please send the abstract", "turn_number": 1},
    )
    body = r.json()["reply"]["body"].lower()
    assert any(word in body for word in PROGRESS_WORDS), body
    for phrase in BANNED_REPLY_PHRASES:
        assert phrase not in body, body


def test_reply_auto_reply_hell_ends_by_fourth(loaded, dataset, pairs):
    pair = next(p for p in pairs if p.get("merchant_id") and p.get("trigger_id"))
    mid = pair["merchant_id"]
    _push(loaded, dataset, pair["trigger_id"])
    loaded.post("/v1/tick", json={"trigger_ids": [pair["trigger_id"]]})
    message = "Out of office. I am away until Monday and will respond then."
    outcomes = []
    for i in range(1, 5):
        r = loaded.post(
            "/v1/reply",
            json={"conversation_id": f"auto_{i}", "merchant_id": mid, "from_role": "merchant", "message": message, "turn_number": i},
        )
        outcomes.append(r.json())
    assert outcomes[0]["action"] == "wait"
    assert outcomes[1]["action"] == "wait"
    assert outcomes[2]["action"] == "wait"
    assert outcomes[3]["action"] == "end", outcomes[3]


def test_reply_hostile_optout_ends_and_suppresses(loaded, dataset, pairs):
    pair = next(p for p in pairs if p.get("merchant_id") and p.get("trigger_id"))
    mid = pair["merchant_id"]
    r = loaded.post(
        "/v1/reply",
        json={"conversation_id": "conv_hostile", "merchant_id": mid, "from_role": "merchant", "message": "Stop messaging me. This is useless spam.", "turn_number": 1},
    )
    assert r.json()["action"] == "end"
    _push(loaded, dataset, pair["trigger_id"])
    after = loaded.post("/v1/tick", json={"trigger_ids": [pair["trigger_id"]]}).json()
    assert not any(a.get("merchant_id") == mid for a in after["actions"]), after
    assert any(d.get("reason", "").find("opt") >= 0 or "declin" in d.get("reason", "") for d in after["decisions"]) or not after["actions"]


def test_reply_decline_ends(loaded, dataset, pairs):
    mid = pairs[0]["merchant_id"]
    r = loaded.post(
        "/v1/reply",
        json={"conversation_id": "conv_dec", "merchant_id": mid, "from_role": "merchant", "message": "not interested, thanks", "turn_number": 1},
    )
    assert r.json()["action"] == "end"


def test_reply_delay_backs_off(loaded, dataset, pairs):
    mid = pairs[0]["merchant_id"]
    r = loaded.post(
        "/v1/reply",
        json={"conversation_id": "conv_delay", "merchant_id": mid, "from_role": "merchant", "message": "I need more time, maybe next week", "turn_number": 1},
    )
    body = r.json()
    assert body["action"] == "wait"
    tid = pairs[0]["trigger_id"]
    _push(loaded, dataset, tid)
    tick = loaded.post("/v1/tick", json={"trigger_ids": [tid]}).json()
    assert not tick["actions"], tick


def test_reply_planning_intent_is_not_pitched_at(loaded, dataset, pairs):
    mid = pairs[0]["merchant_id"]
    r = loaded.post(
        "/v1/reply",
        json={"conversation_id": "conv_plan", "merchant_id": mid, "from_role": "merchant", "message": "We are planning this for next quarter and thinking about the budget", "turn_number": 1},
    )
    assert r.json()["action"] == "wait"


def test_tick_never_exceeds_action_cap(loaded, dataset):
    trigger_ids = list(dataset["triggers"].keys())[:25]
    for tid in trigger_ids:
        _push(loaded, dataset, tid)
    r = loaded.post("/v1/tick", json={"trigger_ids": trigger_ids})
    assert len(r.json()["actions"]) <= 20


def test_consent_optout_blocks_customer_send(client, dataset):
    client.post("/v1/context", json={"scope": "category", "context_id": "gyms", "version": 1, "payload": dataset["categories"]["gyms"]})
    mid = "m_007_powerhouse_gym_bangalore"
    cid = "c_010_rashmi_for_m007"
    for scope, key, payload in (("merchant", mid, dataset["merchants"][mid]), ("customer", cid, dataset["customers"][cid])):
        client.post("/v1/context", json={"scope": scope, "context_id": key, "version": 1, "payload": payload})
    customer = dict(dataset["customers"][cid])
    customer["preferences"] = {**customer.get("preferences", {}), "reminder_opt_in": False}
    client.post("/v1/context", json={"scope": "customer", "context_id": cid, "version": 2, "payload": customer})
    trigger = {"trigger_id": "trg_consent_block", "kind": "customer_lapsed_hard", "scope": "customer", "channel": "customer", "customer_id": cid, "merchant_id": mid, "urgency": 5, "payload": {}}
    client.post("/v1/context", json={"scope": "trigger", "context_id": "trg_consent_block", "version": 1, "payload": trigger})
    r = client.post("/v1/tick", json={"trigger_ids": ["trg_consent_block"]}).json()
    assert not any(a.get("channel") == "customer" for a in r["actions"]), r
    assert any(d["decision"] == "suppressed" for d in r["decisions"]), r


def test_missing_consent_scope_blocks_customer_send(client, dataset):
    client.post("/v1/context", json={"scope": "category", "context_id": "gyms", "version": 1, "payload": dataset["categories"]["gyms"]})
    mid, cid = "m_007_powerhouse_gym_bangalore", "c_010_rashmi_for_m007"
    client.post("/v1/context", json={"scope": "merchant", "context_id": mid, "version": 1, "payload": dataset["merchants"][mid]})
    customer = dict(dataset["customers"][cid])
    customer["consent"] = {"opted_in_at": "2025-01-01", "scope": []}
    client.post("/v1/context", json={"scope": "customer", "context_id": cid, "version": 1, "payload": customer})
    trigger = {"trigger_id": "trg_scope_block", "kind": "recall_due", "scope": "customer", "channel": "customer", "customer_id": cid, "merchant_id": mid, "urgency": 5, "payload": {}}
    client.post("/v1/context", json={"scope": "trigger", "context_id": "trg_scope_block", "version": 1, "payload": trigger})
    r = client.post("/v1/tick", json={"trigger_ids": ["trg_scope_block"]}).json()
    assert not any(a.get("channel") == "customer" for a in r["actions"]), r


def test_every_merchant_number_is_grounded(loaded, dataset, pairs):
    from app.evidence import build_bundle
    from app import normalize, strategies, validate
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    checked = 0
    for pair in pairs:
        tid = pair.get("trigger_id")
        mid = pair.get("merchant_id")
        cid = pair.get("customer_id")
        if not tid or not mid or mid not in dataset["merchants"] or tid not in dataset["triggers"]:
            continue
        merchant = dataset["merchants"][mid]
        trigger = dataset["triggers"][tid]
        customer = dataset["customers"].get(cid) if cid else None
        category = dataset["categories"].get(normalize.merchant_category(merchant))
        plan = strategies.plan_for_trigger(trigger, merchant, customer, category, now)
        bundle = build_bundle(category, merchant, trigger, customer, now)
        plan = validate.finalise(plan, bundle, merchant, customer)
        if plan.suppressed:
            continue
        report = validate.validate_plan(plan, bundle, merchant, customer)
        ungrounded = [v for v in report.violations if v.startswith("ungrounded number")]
        assert not ungrounded, f"{tid}: {ungrounded} body={plan.body}"
        checked += 1
    assert checked >= 20
