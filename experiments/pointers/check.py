"""Pointers and the Jev checker on the winning setup's answers (PLAN.md). The checker is ../jev-check/check.py,
loaded unchanged (its hash is checked); only its cache file is pointed here.

    JEV_API_KEY=... python experiments/pointers/check.py run [--workers 8]
    python experiments/pointers/check.py report
"""
import collections
import importlib.util
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


FR = _load("fresh_run", ROOT / "experiments" / "fresh" / "run.py")      # every set's runs dir (BL.SETS + fresh)
_CHECK = ROOT / "experiments" / "jev-check" / "check.py"
_want = (ROOT / "experiments" / "jev-check" / "frozen.sha256").read_text().split()[0]   # line 1: its hash, line 2: a date
if __import__("hashlib").sha256(_CHECK.read_bytes()).hexdigest() != _want:
    raise SystemExit("jev-check/check.py changed since it was frozen")
JC = _load("jev_check", _CHECK)
JC.CACHE = HERE / "jev_cache.jsonl"
RESULTS = HERE / "results.json"
SETS = {"fresh": (ROOT / "experiments" / "fresh", "top1-r1"), "big": (ROOT / "experiments" / "big-library", "top1-r1")}


def run_dir(pid):
    s, paper = pid.split("/")
    sets = FR.BL.SETS if s in FR.BL.SETS else FR.L.SETS
    return Path(sets[s]["runs"]) / paper


def passages(pid):
    """check.passages reads ROOT/runs/bench/<paper>; a path relative to that directory reaches any set's run."""
    return JC.passages(os.path.relpath(run_dir(pid), ROOT / "runs" / "bench"))


def records():
    out = {}
    for name, (d, arm) in SETS.items():
        hand = json.loads((d / "hand.json").read_text())
        for f in sorted((d / "answers" / arm).glob("*.json")):
            r = json.loads(f.read_text())
            out[f"{name}/{r['key']}"] = dict(r, grade=hand[f"top1/{r['key']}"]["verdict"])
    return out


def run(workers):
    FR.C._check_frozen(HERE / "frozen.sha256")
    FR.install()
    recs = records()
    psg = {}
    for r in recs.values():
        if r["routed"] not in psg:
            psg[r["routed"]] = passages(r["routed"])
    results = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}

    def one(k):
        results[k] = dict(JC.check(recs[k], psg[recs[k]["routed"]]), grade=recs[k]["grade"],
                          routed_right=recs[k]["routed"] == recs[k]["target"])
    todo = [k for k in sorted(recs) if k not in results]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, todo))
    RESULTS.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    print(f"{len(results)} answers checked; {sum(len(v['numbers']) for v in results.values())} numbers")
    report()


def report():
    res = json.loads(RESULTS.read_text())
    for name in list(SETS) + ["all"]:
        R = {k: v for k, v in res.items() if name == "all" or k.startswith(name + "/")}
        nums = [n for v in R.values() for n in v["numbers"]]
        by = collections.Counter(("pointed" if n["candidates"] else "not printed") + ", " + n["by"]
                                 + (", yes" if n["supported"] else ", no") for n in nums)
        print(f"\n== {name}: {len(R)} answers, {len(nums)} numbers ({len(nums) / len(R):.1f} an answer)")
        print(f"   given a pointer (printed in the paper): {sum(1 for n in nums if n['candidates'])} "
              f"({100 * sum(1 for n in nums if n['candidates']) / max(len(nums), 1):.0f}%)")
        for k, c in sorted(by.items(), key=lambda kv: -kv[1]):
            print(f"     {c:5}  {k}")
        tab = collections.Counter((v["verdict"], v["grade"]) for v in R.values())
        g = ("correct", "partial", "wrong")
        print(f"   {'':9}" + "".join(f"{x:>9}" for x in g) + "    total")
        for c in ("passed", "flagged", "no claim"):
            print(f"   {c:9}" + "".join(f"{tab[(c, x)]:>9}" for x in g) + f"   {sum(tab[(c, x)] for x in g):>6}")
        n = len(R)
        right, wrong = (sum(tab[(c, x)] for c in ("passed", "flagged", "no claim")) for x in ("correct", "wrong"))
        out = [v for v in R.values() if v["verdict"] != "flagged"]
        oright = sum(v["grade"] == "correct" for v in out)
        owrong = sum(v["grade"] == "wrong" for v in out)
        print(f"   all answers: {right} right ({100 * right / n:.0f}%), {wrong} wrong ({100 * wrong / n:.0f}%)")
        print(f"   flagged held back: {len(R) - len(out)} answers ({tab[('flagged', 'correct')]} of the {right} right, "
              f"{tab[('flagged', 'wrong')]} of the {wrong} wrong)")
        print(f"   delivered: {len(out)} answers, {oright} right ({100 * oright / max(len(out), 1):.0f}%), "
              f"{owrong} wrong ({100 * owrong / max(len(out), 1):.0f}%)")


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 8)
    else:
        report()
