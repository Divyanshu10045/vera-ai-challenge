"""End-to-end HTTP check against a running server. Usage: python smoke.py [base_url]"""
import json
import sys
import time
from pathlib import Path

import httpx

PACK = Path(r"C:\Users\dk732\Documents\Magicpin AI Challenge\challenge-pack")
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8077"
c = httpx.Client(base_url=BASE, timeout=30.0)

fails = []


def check(label, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {label}{(' :: ' + str(detail)[:300]) if (detail and not cond) else ''}")
    if not cond:
        fails.append(label)


def push_dir(sub, scope, id_keys):
    n = 0
    for path in sorted((PACK / "expanded" / sub).glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        cid = next((payload[k] for k in id_keys if isinstance(payload.get(k), str) and payload.get(k)), None)
        if not cid:
            continue
        r = c.post("/v1/context", json={"scope": scope, "context_id": cid, "version": 1, "payload": payload})
        if r.status_code == 200 and r.json().get("accepted"):
            n += 1
    return n


t0 = time.time()
c.post("/v1/reset")
h = c.get("/v1/healthz")
check("healthz 200 + healthy", h.status_code == 200 and h.json()["status"] == "healthy", h.text)
m = c.get("/v1/metadata")
check("metadata has team_name/model/approach", all(k in m.json() for k in ("team_name", "model", "approach")), m.text)

cats = 0
for path in sorted((PACK / "dataset" / "categories").glob("*.json")):
    payload = json.loads(path.read_text(encoding="utf-8"))
    r = c.post("/v1/context", json={"scope": "category", "context_id": payload["slug"], "version": 1, "payload": payload})
    cats += 1 if r.json().get("accepted") else 0
mer = push_dir("merchants", "merchant", ("merchant_id", "id"))
cus = push_dir("customers", "customer", ("customer_id", "id"))
trg = push_dir("triggers", "trigger", ("trigger_id", "id"))
check(f"contexts pushed (cats={cats} mer={mer} cus={cus} trg={trg})", cats == 5 and mer == 50 and cus == 200 and trg == 100)

s1 = c.post("/v1/context", json={"scope": "category", "context_id": "dentists", "version": 1, "payload": {"slug": "dentists"}})
s2 = c.post("/v1/context", json={"scope": "category", "context_id": "dentists", "version": 2, "payload": {"slug": "dentists", "voice": {}}})
s3 = c.post("/v1/context", json={"scope": "category", "context_id": "dentists", "version": 2, "payload": {"slug": "dentists"}})
check("stale v1 -> 409", s1.status_code == 409, s1.text)
check("fresh v2 -> 200", s2.status_code == 200, s2.text)
check("repeat v2 -> 409", s3.status_code == 409, s3.text)
check("bad scope -> 400", c.post("/v1/context", json={"scope": "nope", "context_id": "x", "version": 1, "payload": {}}).status_code == 400)

raw_pairs = json.loads((PACK / "expanded" / "test_pairs.json").read_text(encoding="utf-8"))
if isinstance(raw_pairs, dict):
    pairs = next((raw_pairs[k] for k in ("test_pairs", "pairs", "cases") if isinstance(raw_pairs.get(k), list)), [])
else:
    pairs = raw_pairs
ids = [p["trigger_id"] for p in pairs if isinstance(p, dict) and p.get("trigger_id")]
t1 = time.time()
tick = c.post("/v1/tick", json={"trigger_ids": ids})
elapsed = time.time() - t1
body = tick.json()
check(f"tick 200 under 15s ({elapsed:.2f}s, {len(body['actions'])} actions)", tick.status_code == 200 and elapsed < 15, tick.text)
check("tick <= 20 actions", len(body["actions"]) <= 20, len(body["actions"]))
required = {"channel", "kind", "body", "rationale", "trigger_id", "merchant_id"}
check("every action well-formed", all(required <= set(a) and a["body"].strip() and a["rationale"].strip() for a in body["actions"]), body["actions"][:1])
check("no URLs / jargon in bodies", not any(
    __import__("re").search(r"https?://|www\.|\b(trigger|payload|context_id|consent scope|provenance)\b", a["body"], __import__("re").I)
    for a in body["actions"]), [a["body"] for a in body["actions"]][:3])

# Trap 1: intent reply must carry a progress word, never a banned question form
mid = pairs[0]["merchant_id"]
c.post("/v1/tick", json={"trigger_ids": [pairs[0]["trigger_id"]]})
r = c.post("/v1/reply", json={"conversation_id": "c1", "merchant_id": mid, "from_role": "merchant", "message": "Yes please send the abstract", "turn_number": 1})
rb = r.json()["reply"]["body"].lower()
check("intent reply has progress word", any(w in rb for w in ("done", "sending", "draft", "here", "confirm", "proceed", "next")), rb)
check("intent reply avoids banned phrases", not any(p in rb for p in ("would you", "do you", "can you tell", "what if", "how about")), rb)

# Trap 2: four identical auto-replies under different conversation ids
msg = "Out of office. I am away until Monday and will respond then."
acts = [c.post("/v1/reply", json={"conversation_id": f"auto{i}", "merchant_id": mid, "from_role": "merchant", "message": msg, "turn_number": i}).json()["action"] for i in range(1, 5)]
check("auto-reply 1-3 wait then end", acts[:3] == ["wait"] * 3 and acts[3] == "end", acts)

# Trap 3: hostile opt-out
r = c.post("/v1/reply", json={"conversation_id": "c2", "merchant_id": mid, "from_role": "merchant", "message": "Stop messaging me. This is useless spam.", "turn_number": 1})
check("hostile opt-out -> end", r.json()["action"] == "end", r.text)
after = c.post("/v1/tick", json={"trigger_ids": ids}).json()
check("opted-out merchant gets no sends", not any(a.get("merchant_id") == mid for a in after["actions"]), [a.get("merchant_id") for a in after["actions"]])

# Decline + delay
other = next(p["merchant_id"] for p in pairs if p["merchant_id"] != mid)
check("decline -> end", c.post("/v1/reply", json={"conversation_id": "c3", "merchant_id": other, "from_role": "merchant", "message": "not interested, thanks"}).json()["action"] == "end")
check("delay -> wait", c.post("/v1/reply", json={"conversation_id": "c4", "merchant_id": other, "from_role": "merchant", "message": "I need more time, maybe next week"}).json()["action"] == "wait")

print(f"\ntotal {time.time()-t0:.1f}s | {'ALL PASS' if not fails else 'FAILURES: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
