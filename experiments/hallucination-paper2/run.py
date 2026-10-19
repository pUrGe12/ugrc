"""Run the hallucination experiment on paper 2: independent probes, one long session, long tasks.

    ANTHROPIC_API_KEY=... python experiments/hallucination-paper2/run.py

Every answer is saved to answers/<arm>-<probe>.json with the full record (runs, rendered text,
citations, refusals, usage). Grading is done afterwards against probes.json, by hand.
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

DB = ROOT / "runs" / "paper2"
OUT = HERE / "answers"
WORKERS = 8
lock = threading.Lock()


def log(msg):
    with lock:
        print(msg, flush=True)


def save(arm, pid, rec):
    rec = dict(rec, arm=arm, probe=pid)
    (OUT / f"{arm}-{pid}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str))


def one(arm, pid, question):
    try:
        rec = ask.ask(DB, question, cl=llm.client(), log=lambda *_: None)
        save(arm, pid, rec)
        log(f"done  {arm}-{pid}  refusals={len(rec['door_refusals'])} tools={rec['tool_calls']}")
    except Exception as e:
        log(f"FAIL  {arm}-{pid}: {type(e).__name__}: {e}")
        (OUT / f"{arm}-{pid}.error.txt").write_text(traceback.format_exc())


def run_session(probes, ids):
    try:
        qs = [probes[i] for i in ids]
        done = []

        def on_answer(rec):
            pid = ids[rec["session_index"]]
            save("session", pid, rec)
            done.append(pid)
            log(f"done  session-{pid} ({len(done)}/{len(ids)})  refusals={len(rec['door_refusals'])}")
        ask.session(DB, qs, cl=llm.client(), log=lambda *_: None, on_answer=on_answer)
    except Exception as e:
        log(f"FAIL  session: {type(e).__name__}: {e}")
        (OUT / "session.error.txt").write_text(traceback.format_exc())


def main():
    spec = json.loads((HERE / "probes.json").read_text())
    OUT.mkdir(exist_ok=True)
    probes = {p["id"]: p["q"] for p in spec["probes"]}
    jobs = [("independent", p["id"], p["q"]) for p in spec["probes"]]
    jobs += [("long", t["id"], t["q"]) for t in spec["long_tasks"]]
    sess = threading.Thread(target=run_session, args=(probes, spec["session"]))
    sess.start()
    with ThreadPoolExecutor(WORKERS) as pool:
        for job in jobs:
            pool.submit(one, *job)
    sess.join()
    log("all done")


if __name__ == "__main__":
    main()
