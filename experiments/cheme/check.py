"""The frozen Jev checker (experiments/jev-check/check.py, unchanged, its hash verified) run on every ChemE-test answer.

    JEV_API_KEY=... python experiments/cheme/check.py run [--workers 8]     check every answer of the three arms
    python experiments/cheme/check.py report                               checker verdicts against the hand grades

As in experiments/new6/check.py, only two things differ from the jev-check run: a paper's passages are read from its
v5 run (runs/new6-v5/<paper> or runs/cheme/<paper>, linked under cheme/_root/runs/bench), and Jev's answers are cached
in cheme/jev_cache.jsonl. The reused new6 pdf answers are checked again here, against the v5 passages. Results:
check-results.json, keyed like hand.json.
"""
import collections
import hashlib
import json
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
JC = ROOT / "experiments" / "jev-check"
digest = (JC / "frozen.sha256").read_text().split()[0]
if hashlib.sha256((JC / "check.py").read_bytes()).hexdigest() != digest:
    raise SystemExit("jev-check/check.py changed since it was frozen")
sys.path.insert(0, str(JC))
import check  # noqa: E402
sys.path.insert(0, str(HERE))
import run as R  # noqa: E402  (SETS, probes, answer_path)

check.CACHE = HERE / "jev_cache.jsonl"
ARMS = ("hybrid", "facts", "pdf")
RUNS = (1, 2, 3)


def _passages(paper):
    """check.passages itself, reading ROOT / "runs" / "bench" / paper with ROOT = cheme/_root."""
    g = dict(check.passages.__globals__)
    g["ROOT"] = HERE / "_root"
    return types.FunctionType(check.passages.__code__, g)(paper)


def _links():
    d = HERE / "_root" / "runs" / "bench"
    d.mkdir(parents=True, exist_ok=True)
    for s, spec in R.SETS.items():
        for paper in json.loads(spec["probes"].read_text())["papers"]:
            if not (d / paper).exists():
                (d / paper).symlink_to(spec["runs"] / paper)


def records():
    out = {}
    for s, paper, p in R.probes():
        for a in ARMS:
            for r in RUNS:
                f = R.answer_path(a, r, s, paper, p["id"])
                if f.exists():
                    out[f"{a}-r{r}/{paper}-{p['id']}"] = json.loads(f.read_text())
    return out


def run(workers):
    _links()
    recs = records()
    psg = {p: _passages(p) for p in {r["paper"] for r in recs.values()}}
    results = {}

    def one(k):
        results[k] = check.check(recs[k], psg[recs[k]["paper"]])
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, sorted(recs)))
    (HERE / "check-results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    print(f"{len(results)} answers checked; {sum(len(v['numbers']) for v in results.values())} numbers")
    report()


def report():
    results = json.loads((HERE / "check-results.json").read_text())
    hand = json.loads((HERE / "hand.json").read_text()) if (HERE / "hand.json").exists() else {}
    sets = {f"{paper}-{p['id']}": s for s, paper, p in R.probes()}
    for arm in ARMS:
        for sname in ("all", "new6", "cheme"):
            tab = collections.Counter()
            for k, res in results.items():
                if k.startswith(arm + "-r") and sname in ("all", sets[k.split("/", 1)[1]]):
                    tab[(res["verdict"], (hand.get(k) or {}).get("verdict", "ungraded"))] += 1
            vs = ("correct", "partial", "wrong", "ungraded")
            n = sum(tab.values())
            if not n:
                continue
            print(f"\n== {arm} ({sname}): checker verdict against hand grade ({n} answers)")
            print(f"{'':10} " + " ".join(f"{h:>9}" for h in vs) + "    total")
            for c in ("passed", "flagged", "no claim"):
                print(f"{c:10} " + " ".join(f"{tab[(c, h)]:>9}" for h in vs) + f"   {sum(tab[(c, h)] for h in vs):>6}")
            right = sum(tab[(c, "correct")] for c in ("passed", "flagged", "no claim"))
            wrong = sum(tab[(c, "wrong")] for c in ("passed", "flagged", "no claim"))
            nk = sum(tab[(c, h)] for c in ("passed", "no claim") for h in vs)
            if nk:
                kr = sum(tab[(c, "correct")] for c in ("passed", "no claim"))
                kw = sum(tab[(c, "wrong")] for c in ("passed", "no claim"))
                print(f"all: {right} right ({100 * right / n:.0f}%), {wrong} wrong ({100 * wrong / n:.0f}%); "
                      f"delivered (passed + no claim): {nk}, {kr} right ({100 * kr / nk:.0f}%), {kw} wrong "
                      f"({100 * kw / nk:.0f}%); right answers held back: {tab[('flagged', 'correct')]} of {right}")


if __name__ == "__main__":
    if sys.argv[1] == "report":
        report()
    else:
        run(int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 8)
