"""Ask the professor's questions of the 10-paper corpus with the question loop (Claude), keeping traces.

    ANTHROPIC_API_KEY=... python experiments/prof-rag/run.py [ID ...]
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

DB = ROOT / "runs" / "papers-corpus"
OUT = HERE / os.environ.get("ANSWERS", "answers")     # another folder for another model
lock = threading.Lock()


def log(msg):
    with lock:
        print(msg, flush=True)


def one(q):
    if (OUT / f"{q['id']}.json").exists():
        return log(f"skip  {q['id']}")
    try:
        rec = ask.ask(DB, q["q"], cl=llm.client(), log=lambda *_: None)
        (OUT / f"{q['id']}.json").write_text(json.dumps(dict(rec, probe=q["id"], kind=q["kind"]), indent=2,
                                                        ensure_ascii=False, default=str))
        log(f"done  {q['id']}  tools={rec['tool_calls']} refusals={len(rec['door_refusals'])}")
    except Exception as e:
        log(f"FAIL  {q['id']}: {type(e).__name__}: {e}")
        (OUT / f"{q['id']}.error.txt").write_text(traceback.format_exc())


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    qs = json.loads((HERE / "questions.json").read_text())["questions"]
    if sys.argv[1:]:
        qs = [q for q in qs if q["id"] in sys.argv[1:]]
    log(f"{len(qs)} questions")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(one, qs))
    log("all done")
