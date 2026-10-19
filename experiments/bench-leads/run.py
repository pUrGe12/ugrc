"""Ask the 88 frozen probes of probes.json, in two arms and several runs, keeping every record.

    ANTHROPIC_API_KEY=... UGRC_MODEL=claude-haiku-5-5 python experiments/bench-leads/run.py [RUNS] [ARM ...]

plain  the paper's substrate with no clause base beside it (runs/papers/<paper>, runs/cai2026)
leads  the same substrate with its clause base (runs/bench/<paper>): leads with each question, measure runs
Each answer goes to answers/<arm>-r<k>/<paper>-<id>.json; answered probes are skipped, so a run resumes.
"""
import hashlib
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

WORKERS = 8
lock = threading.Lock()


def substrate(arm, paper):
    if arm == "leads":
        return ROOT / "runs" / "bench" / paper
    return ROOT / "runs" / ("cai2026" if paper == "cai2026" else f"papers/{paper}")


def log(msg):
    with lock:
        print(msg, flush=True)


def one(job):
    arm, k, paper, probe = job
    out = HERE / "answers" / f"{arm}-r{k}"
    name = f"{paper}-{probe['id']}"
    if (out / f"{name}.json").exists():
        return
    try:
        rec = ask.ask(substrate(arm, paper), probe["q"], cl=llm.client(), log=lambda *_: None)
        rec = dict(rec, arm=arm, run=k, paper=paper, probe=probe["id"], cat=probe["cat"], expect=probe["expect"],
                   trap=probe.get("trap"))
        (out / f"{name}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
        log(f"done  {arm}-r{k} {name:24} tools={rec['tool_calls']} refusals={len(rec['door_refusals'])}")
    except Exception as e:
        log(f"FAIL  {arm}-r{k} {name}: {type(e).__name__}: {e}")
        (out / f"{name}.error.txt").write_text(traceback.format_exc())


if __name__ == "__main__":
    frozen = (HERE / "frozen.sha256").read_text().split()[0]
    if hashlib.sha256((HERE / "probes.json").read_bytes()).hexdigest() != frozen:
        raise SystemExit("probes.json changed since it was frozen")
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    arms = sys.argv[2:] or ["plain", "leads"]
    papers = json.loads((HERE / "probes.json").read_text())["papers"]
    jobs = [(arm, k, paper, p) for k in range(1, runs + 1) for arm in arms for paper, ps in papers.items() for p in ps]
    for arm in arms:
        for k in range(1, runs + 1):
            (HERE / "answers" / f"{arm}-r{k}").mkdir(parents=True, exist_ok=True)
    log(f"{len(jobs)} answers ({os.environ.get('UGRC_MODEL', llm.MODEL)}), {WORKERS} workers")
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(one, jobs))
    log("all done")
