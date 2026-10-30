"""The frozen Jev checker (experiments/jev-check/check.py, unchanged, its hash verified) run on the new6 answers.

    JEV_API_KEY=... python experiments/new6/check.py run [--workers 8]     check every answer of both arms
    python experiments/new6/check.py report                               checker verdicts against the hand grades

Only two things differ from the jev-check run: a paper's passages are read from runs/new6/<paper> (the same code,
pointed at another directory), and Jev's answers are cached in new6/jev_cache.jsonl. Results: check-results.json.
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

check.CACHE = HERE / "jev_cache.jsonl"


def _passages(paper):
    """check.passages itself, reading ROOT / "runs" / "bench" / paper with ROOT = new6/_root."""
    g = dict(check.passages.__globals__)
    g["ROOT"] = HERE / "_root"          # _root/runs/bench -> ../../../../runs/new6 (a symlink, made below)
    return types.FunctionType(check.passages.__code__, g)(paper)


link = HERE / "_root" / "runs" / "bench"
if not link.exists():
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(ROOT / "runs" / "new6")

ARMS = [f"{a}-r{r}" for a in ("llama-hybrid", "llama-direct") for r in (1, 2, 3)]


def records():
    out = {}
    for arm in ARMS:
        for f in sorted((HERE / "answers" / arm).glob("*.json")):
            out[f"{arm}/{f.stem}"] = json.loads(f.read_text())
    return out


def run(workers):
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
    for arm in ("llama-hybrid", "llama-direct"):
        tab = collections.Counter()
        for k, res in results.items():
            if k.startswith(arm + "-r"):
                tab[(res["verdict"], (hand.get(k) or {}).get("verdict", "ungraded"))] += 1
        vs = ("correct", "partial", "wrong", "ungraded")
        n = sum(tab.values())
        print(f"\n== {arm}: checker verdict against hand grade ({n} answers)")
        print(f"{'':10} " + " ".join(f"{h:>9}" for h in vs) + "    total")
        for c in ("passed", "flagged", "no claim"):
            print(f"{c:10} " + " ".join(f"{tab[(c, h)]:>9}" for h in vs) + f"   {sum(tab[(c, h)] for h in vs):>6}")
        right = sum(tab[(c, "correct")] for c in ("passed", "flagged", "no claim"))
        wrong = sum(tab[(c, "wrong")] for c in ("passed", "flagged", "no claim"))
        kept = [(c, h) for c in ("passed", "no claim") for h in vs]
        nk = sum(tab[x] for x in kept)
        if n and nk:
            kr = sum(tab[(c, "correct")] for c in ("passed", "no claim"))
            kw = sum(tab[(c, "wrong")] for c in ("passed", "no claim"))
            print(f"all: {right} right ({100 * right / n:.0f}%), {wrong} wrong ({100 * wrong / n:.0f}%); "
                  f"delivered (passed + no claim): {nk}, {kr} right ({100 * kr / nk:.0f}%), {kw} wrong ({100 * kw / nk:.0f}%); "
                  f"right answers held back: {tab[('flagged', 'correct')]} of {right}")


if __name__ == "__main__":
    if sys.argv[1] == "report":
        report()
    else:
        run(int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 8)
