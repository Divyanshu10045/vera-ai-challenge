"""Run the official simulator's bot-facing scenarios without a judge LLM key.

Only the trap scenarios (warmup, auto_reply, intent, hostile) are exercised, since
the LLM judge is only needed for qualitative scoring, not for contract validation.
"""
import importlib.util
import sys
from pathlib import Path

PACK = Path(r"C:\Users\dk732\Documents\Magicpin AI Challenge\challenge-pack")
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8077"

spec = importlib.util.spec_from_file_location("judge_simulator", PACK / "judge_simulator.py")
js = importlib.util.module_from_spec(spec)
spec.loader.exec_module(js)

js.BOT_URL = BASE


class StubLLM:
    def name(self):
        return "stub (no key)"

    def judge(self, *a, **k):
        return {"scores": {}, "total": 0, "verdict": "skipped"}


sim = js.JudgeSimulator(StubLLM())
print(f"simulator -> {BASE}\n")
ok = sim._all()
print(f"\nBOT-FACING SCENARIOS: {'ALL PASS' if ok else 'FAILURES PRESENT'}")
sys.exit(0 if ok else 1)
