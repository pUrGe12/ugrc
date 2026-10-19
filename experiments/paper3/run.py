"""Run the paper 3 probes through the question loop, each in a fresh conversation.

    ANTHROPIC_API_KEY=... python experiments/paper3/run.py
"""
import json
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from ugrc import ask, llm  # noqa: E402

DB = ROOT / "runs" / "paper3"
OUT = HERE / "answers"
WORKERS = 7
lock = threading.Lock()


def log(msg):
    with lock:
        print(msg, flush=True)


def one(probe):
    pid = probe["id"]
    try:
        rec = ask.ask(DB, probe["q"], cl=llm.client(), log=lambda *_: None)
        (OUT / f"{pid}.json").write_text(json.dumps(dict(rec, probe=pid, cat=probe["cat"]),
                                                    indent=2, ensure_ascii=False, default=str))
        log(f"done  {pid:3} refusals={len(rec['door_refusals'])} tools={rec['tool_calls']}")
    except Exception as e:
        log(f"FAIL  {pid}: {type(e).__name__}: {e}")
        (OUT / f"{pid}.error.txt").write_text(traceback.format_exc())


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    probes = json.loads((HERE / "probes.json").read_text())["probes"]
    only = sys.argv[1:]
    if only:
        probes = [p for p in probes if p["id"] in only]
    log(f"{len(probes)} probes, {WORKERS} workers")
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(one, probes))
    log("all done")
