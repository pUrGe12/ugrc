"""Run the existing probe sets through the question loop with Claude, keeping each answer's trace.

    ANTHROPIC_API_KEY=... python experiments/claude-capability/run.py [ID ...]

Paper 2: the 31 independent probes of experiments/hallucination-paper2/probes.json.
Paper 3: the 29 probes of experiments/paper3/probes.json.
Each answer is saved to answers/<paper>-<id>.json with the full record, including `trace` (every tool
call: the SQL written, figures viewed, refused submissions), which mark.py reads.
"""
import json
import os
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from ugrc import ask, llm  # noqa: E402

SETS = {"p2": (ROOT / "runs" / "paper2", ROOT / "experiments" / "hallucination-paper2" / "probes.json"),
        "p3": (ROOT / "runs" / "paper3", ROOT / "experiments" / "paper3" / "probes.json")}
OUT = HERE / os.environ.get("ANSWERS", "answers")     # another folder for another model
WORKERS = 6
lock = threading.Lock()


def log(msg):
    with lock:
        print(msg, flush=True)


def one(job):
    paper, probe = job
    db, _ = SETS[paper]
    name = f"{paper}-{probe['id']}"
    if (OUT / f"{name}.json").exists():
        return log(f"skip  {name} (answered)")
    try:
        rec = ask.ask(db, probe["q"], cl=llm.client(), log=lambda *_: None)
        rec = dict(rec, paper=paper, probe=probe["id"], cat=probe["cat"], expect=probe["expect"], trap=probe.get("trap"))
        (OUT / f"{name}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
        log(f"done  {name:7} tools={rec['tool_calls']} refusals={len(rec['door_refusals'])}")
    except Exception as e:
        log(f"FAIL  {name}: {type(e).__name__}: {e}")
        (OUT / f"{name}.error.txt").write_text(traceback.format_exc())


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    jobs = [(paper, p) for paper, (_, f) in SETS.items() for p in json.loads(f.read_text())["probes"]]
    only = sys.argv[1:]
    if only:
        jobs = [(paper, p) for paper, p in jobs if f"{paper}-{p['id']}" in only]
    log(f"{len(jobs)} probes, {WORKERS} workers")
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(one, jobs))
    log("all done")
