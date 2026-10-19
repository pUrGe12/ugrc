"""Grade a set of clause bases (one per paper) against the bench's answer keys, by split.

    python grade.py RUNS_DIR [--errors]       # RUNS_DIR/<paper>/clauses.duckdb, e.g. runs/v7

Uses the grading rules of experiments/jev-questions/grade.py (synonyms, alternatives, tolerated items;
a non-quantity the clause base did not extract counts as right).
"""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "jev-questions"))
import grade as G  # noqa: E402

FIELDS = ("values", "quantities", "role ok", "property ok", "about ok", "about safe", "by ok", "quantity ok",
          "every slot", "wrong items", "not extracted")


def run(runs_dir, show_errors=False):
    plan = json.loads((HERE / "split.json").read_text())
    totals = {"tuning": Counter(), "held_out": Counter()}
    rows = []
    for split in ("tuning", "held_out"):
        for p in plan[split]:
            t, errors, meta = G.grade(HERE / "gold" / f"{p}.json", Path(runs_dir) / p)
            totals[split].update(t)
            rows.append((split, p, t, meta, errors))
    print(f"{'paper':18} {'split':9} {'role':>7} {'prop':>6} {'about':>6} {'safe':>6} {'by':>6} {'qty':>6} {'every':>6} {'wrong':>6} {'missed':>6}")
    for split, p, t, meta, errors in rows:
        q = t["quantities"]
        print(f"{p:18} {split:9} {t['role ok']:>3}/{t['values']:<3} {t['property ok']:>2}/{q:<3} {t['about ok']:>2}/{q:<3} "
              f"{t['about safe']:>2}/{q:<3} {t['by ok']:>2}/{q:<3} {t['quantity ok']:>2}/{q:<3} {t['every slot']:>2}/{q:<3} "
              f"{t['wrong items']:>6} {t['not extracted']:>6}")
    for split, t in totals.items():
        q = t["quantities"]
        print(f"{'ALL ' + split:28} role {t['role ok']}/{t['values']}  property {t['property ok']}/{q}  about {t['about ok']}/{q} "
              f"(safe {t['about safe']})  by {t['by ok']}/{q}  quantity {t['quantity ok']}/{q}  every slot {t['every slot']}/{q}  "
              f"wrong bindings {t['wrong items']}  quantities not extracted {t['not extracted']}")
    if show_errors:
        for split, p, t, meta, errors in rows:
            if split == "tuning" or "--all" in sys.argv:
                for e in errors:
                    print(f"  [{p}] {e}")
    return totals


if __name__ == "__main__":
    run(sys.argv[1], "--errors" in sys.argv)
