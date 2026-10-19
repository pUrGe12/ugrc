"""Grade the Laya-built clause bases against Jev v8 on the same papers, with the answer keys and rules of
experiments/jev-bench (10 battery papers) and experiments/jev-questions (papers 2 and 3).

    python grade.py [CHECKPOINT]      # default english; grades every paper whose Laya base exists
"""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
sys.path.insert(0, str(EXP / "jev-questions"))
import grade as G  # noqa: E402

SPLIT = json.loads((EXP / "jev-bench" / "split.json").read_text())
PAPERS = [(p, "held_out") for p in SPLIT["held_out"]] + [(p, "tuning") for p in SPLIT["tuning"]] + \
         [("paper2", "chemistry"), ("paper3", "chemistry")]
GOLD = {**{p: EXP / "jev-bench" / "gold" / f"{p}.json" for p in SPLIT["held_out"] + SPLIT["tuning"]},
        "paper2": EXP / "jev-questions" / "paper2-gold-amended.json", "paper3": EXP / "jev-questions" / "paper3-gold.json"}
JEV = {**{p: EXP / "jev-bench" / "runs" / "v8" / p for p in SPLIT["held_out"] + SPLIT["tuning"]},
       "paper2": EXP / "jev-questions" / "runs" / "p2-v8-jev-latest", "paper3": EXP / "jev-questions" / "runs" / "p3-v8-jev-latest"}
COLS = (("role ok", "values"), ("property ok", "quantities"), ("about ok", "quantities"), ("about safe", "quantities"),
        ("by ok", "quantities"), ("quantity ok", "quantities"), ("every slot", "quantities"))


def cell(t, k, n):
    return f"{t[k]}/{t[n]}"


def run(ck):
    totals = {}
    print(f"{'paper':18} {'split':9} {'judge':6} {'role':>7} {'prop':>6} {'about':>6} {'safe':>6} {'by':>6} {'qty':>6} {'every':>6} {'wrong':>6}")
    for p, split in PAPERS:
        laya = HERE / "runs" / ck / p
        if not (laya / "clauses.duckdb").exists():
            continue
        for judge, run_dir in (("jev", JEV[p]), ("laya", laya)):
            t, _, _ = G.grade(GOLD[p], run_dir)
            totals.setdefault((split, judge), Counter()).update(t)
            print(f"{p:18} {split:9} {judge:6} " + " ".join(f"{cell(t, k, n):>6}" for k, n in COLS) + f" {t['wrong items']:>6}")
    print()
    for (split, judge), t in sorted(totals.items()):
        print(f"ALL {split:9} {judge:5} " + "  ".join(f"{k.replace(' ok', '')} {cell(t, k, n)}" for k, n in COLS)
              + f"  wrong bindings {t['wrong items']}  not extracted {t['not extracted']}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "english")
