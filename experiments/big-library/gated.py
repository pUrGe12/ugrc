"""Post hoc, descriptive (PLAN.md, "What gets reported"): send the top 2 papers only when search is unsure.

Search's confidence is the BM25 score of the second paper's best page over the first paper's best page (1 = a tie).
For each cut-off, a question gets top2's graded answer when that ratio is at or above the cut-off, top1's otherwise.
No model; reads routes.json and hand.json.

    python experiments/big-library/gated.py
"""
import importlib.util
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("big_run", HERE / "run.py")
run = importlib.util.module_from_spec(_spec)
sys.modules["big_run"] = run
_spec.loader.exec_module(run)


def scores(ix, question, k1=1.5, b=0.75):
    """Index.rank's scores, kept instead of thrown away."""
    n = len(ix.keys)
    avg = sum(ix.len) / n
    terms = set(run.P.hybrid._words(question))
    df = {t: sum(1 for tf in ix.tf if t in tf) for t in terms}
    out = {}
    for i, k in enumerate(ix.keys):
        tf = ix.tf[i]
        out[k] = sum(math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) * tf[t] * (k1 + 1)
                     / (tf[t] + k1 * (1 - b + b * ix.len[i] / avg)) for t in terms if tf[t])
    return out


def main():
    rt = json.loads((HERE / "routes.json").read_text())["routes"]
    hand = json.loads((HERE / "hand.json").read_text())
    qs = run.questions()
    ix = run.index(run.library())
    ratio = {}
    for key, q in qs.items():
        best = {}
        for (d, _), s in scores(ix, q["q"]).items():
            best[d] = max(best.get(d, 0.0), s)
        s1, s2 = sorted(best.values(), reverse=True)[:2]
        assert max(best, key=best.get) == rt[key]["routed"], key
        ratio[key] = s2 / s1 if s1 else 1.0
    right = {a: {k: hand[f"{a}/{k}"]["verdict"] == "correct" for k in qs} for a in ("top1", "top2")}
    miss = {k for k in qs if not rt[k]["routed_right"]}
    print("cut-off  sent top2  of them misrouted  right  (top1 alone 304, top2 alone 242)")
    for cut in (1.01, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.6, 0.5):
        gated = {k for k in qs if ratio[k] >= cut}
        n = sum(right["top2" if k in gated else "top1"][k] for k in qs)
        print(f"  {cut:4.2f}   {len(gated):5}      {len(gated & miss):5}           {n}")
    print("misrouted questions' ratio: " + ", ".join(f"{k} {ratio[k]:.2f}" for k in sorted(miss)))
    (HERE / "gated.json").write_text(json.dumps({"about": "gated.py: second paper's best BM25 page score over the "
                                                          "first's, per question", "ratio": ratio}, indent=1) + "\n")


if __name__ == "__main__":
    main()
