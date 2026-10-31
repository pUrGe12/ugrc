"""Descriptive, after route.py: does search's own confidence flag the short questions it misroutes? Confidence is the
second paper's best BM25 page score over the first's (../big-library/gated.py). No model.

    python experiments/short-route/unsure.py
"""
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("gated", HERE.parent / "big-library" / "gated.py")
gated = importlib.util.module_from_spec(_spec)
sys.modules["gated"] = gated
_spec.loader.exec_module(gated)
run = gated.run


def main():
    rows = json.loads((HERE / "routing.json").read_text())
    short = json.loads((HERE / "short.json").read_text())["questions"]
    ix = run.index(run.library())
    ratio = {}
    for key in rows:
        best = {}
        for (d, _), s in gated.scores(ix, short[key]["short"]).items():
            best[d] = max(best.get(d, 0.0), s)
        s1, s2 = sorted(best.values(), reverse=True)[:2]
        ratio[key] = s2 / s1 if s1 else 1.0
    miss = {k for k in rows if rows[k]["short"]["whole"] > 1}
    print("cut-off  flagged  of them misrouted  misrouted not flagged  (28 misrouted, 360 right)")
    for cut in (0.95, 0.9, 0.85, 0.8, 0.75, 0.7):
        flag = {k for k in rows if ratio[k] >= cut}
        print(f"  {cut:4.2f}   {len(flag):5}    {len(flag & miss):5}             {len(miss - flag):5}")
    (HERE / "unsure.json").write_text(json.dumps(ratio, indent=1) + "\n")


if __name__ == "__main__":
    main()
