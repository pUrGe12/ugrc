"""Answering the short questions (ANSWER.md): search on the short form picks the paper, then that paper's facts+prose
form, as the big-library test's top1; and the short form on the question's own paper where search picks another.

    python experiments/short-route/answer.py check                  no model: unchanged prompts equal big-library's
    python experiments/short-route/answer.py answer [--workers 8]   needs LLAMA_URL, LLAMA_KEY
"""
import hashlib
import importlib.util
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BIG = ROOT / "experiments" / "big-library"
_spec = importlib.util.spec_from_file_location("big_run", BIG / "run.py")
run = importlib.util.module_from_spec(_spec)
sys.modules["big_run"] = run
_spec.loader.exec_module(run)
R, L, C = run.R, run.L, run.C

ARMS = ("short", "short-oracle")


def load():
    qs, routes = run.frozen()                       # library, routed and big-library frozen files still hold
    C._check_frozen(HERE / "frozen.sha256")
    C._check_frozen(HERE / "answer.sha256")
    short = json.loads((HERE / "short.json").read_text())["questions"]
    rows = json.loads((HERE / "routing.json").read_text())
    return qs, routes, short, rows


def paper(arm, key, rows):
    return rows[key]["short"]["routed"] if arm == "short" else rows[key]["target"]


def needed(arm, rows):
    """short: the changed questions; short-oracle: those of them search sends to another paper."""
    keys = [k for k in rows if not rows[k]["unchanged"]]
    return keys if arm == "short" else [k for k in keys if rows[k]["short"]["routed"] != rows[k]["target"]]


def answer_path(arm, key):
    s, p, pid = key.split("/")
    return HERE / "answers" / f"{arm}-r1" / f"{s}__{p}-{pid}.json"


def check():
    """Every unchanged question's prompt is the big-library answer's, byte for byte (top1, or oracle for short-oracle)."""
    qs, routes, short, rows = load()
    n = 0
    for k, r in rows.items():
        if not r["unchanged"]:
            continue
        for arm, big in (("short", "top1"), ("short-oracle", "top1" if routes[k]["routed_right"] else "oracle")):
            _, user, _ = R.prompt("prose", short[k]["short"], paper(arm, k, rows))
            rec = json.loads(run.answer_path(big, k).read_text())
            assert hashlib.sha256(user.encode()).hexdigest() == rec["prompt"]["user_sha256"], (k, arm)
            n += 1
    print(f"{n} unchanged prompts equal the big-library answers' prompts")


def one(arm, key, q, text, rows):
    f = answer_path(arm, key)
    if f.exists():
        return
    t = time.time()
    d = paper(arm, key, rows)
    system, user, extra = R.prompt("prose", text, d)
    resp = R.scaling.cr.chat(system, user)
    choice = resp["choices"][0]
    out = choice["message"].get("content") or ""
    target = rows[key]["target"]
    rec = {"arm": arm, "run": 1, "key": key, "set": q["set"], "paper": q["paper"], "probe": q["id"], "cat": q["cat"],
           "question": text, "question_long": q["q"], "expect": q["expect"], "trap": q["trap"], "must": q["must"],
           "model": R.scaling.cr.MODEL, "rendered": out, "finish_reason": choice.get("finish_reason"),
           "shown_papers": [d], "target": target, "target_shown": d == target, "short_routed": rows[key]["short"]["routed"],
           "short_target_rank": rows[key]["short"]["whole"],
           "numbers_not_in_paper": sorted({R.scaling.cr._n(x) for x in R.scaling.cr.NUM.findall(out)}
                                          - L.numbers(target) - {""}),
           **extra,
           "prompt": {"style": f"short-route:{arm}", "system": system, "user_chars": len(user),
                      "user_sha256": hashlib.sha256(user.encode()).hexdigest()},
           "usage": resp.get("usage"),
           "sampling": {"temperature": R.llm.TEMPERATURE, "top_p": R.llm.TOP_P, "max_tokens": R.llm.MAX_OUTPUT},
           "seconds": round(time.time() - t, 1)}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
    u = rec["usage"] or {}
    R.log(f"done  {arm:12} {key:40} prompt={u.get('prompt_tokens', '?'):>6} target_shown={rec['target_shown']!s:5} "
          f"{rec['finish_reason']} {time.time() - t:5.1f}s")


def answer(workers):
    if not R.scaling.cr.URL:
        raise SystemExit("set LLAMA_URL (the server's /v1) and LLAMA_KEY")
    qs, _, short, rows = load()
    R.log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} start")
    for arm in ARMS:
        keys = sorted((k for k in needed(arm, rows) if not answer_path(arm, k).exists()),
                      key=lambda k: (paper(arm, k, rows), k))                       # shared prefill
        R.log(f"-- {arm}: {len(keys)} questions")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda k: one(arm, k, qs[k], short[k]["short"], rows), keys))
    R.log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} end")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "check":
        check()
    elif cmd == "answer":
        answer(int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 8)
    else:
        raise SystemExit(__doc__)
