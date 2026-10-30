"""Blind grading and the frozen test for the clause-reasoning plan (PLAN.md), with bench-cross/jev-pick/blind.py's
tools pointed at this directory: two arms, one run.

    python experiments/clause-reasoning/grade.py sheet [--paper P] [--limit N] | record | progress | unseal | report
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0] / "bench-cross" / "jev-pick"))
import blind  # noqa: E402

blind.HERE = HERE
blind.GRADES = HERE / "grades.json"
blind.STAGES = {1: ("llama-clauses", "llama-clauses-text")}
blind.RUNS = (1,)
blind.SIGN = "(Claude, 2026-10-22, blind to arm)"

if __name__ == "__main__":
    cmd = sys.argv[1]
    {"sheet": blind.sheet, "progress": blind.progress, "unseal": blind.unseal, "report": blind.report,
     "record": blind.record_grades}[cmd](1)
