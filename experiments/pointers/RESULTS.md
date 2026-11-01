# Pointers for numbers on the winning setup: results (code part only)

Run 2026-11-01 under the frozen plan (`PLAN.md`, `frozen.sha256`), on 468 graded answers: the fresh test's 80 top1
answers and the big-library test's 388. **Only the code part ran.** Every Jev call failed (HTTP 402: Jev's credits
ran out), so the binding check, and with it the checker's passed/flagged verdicts, did not run. The raw output is
kept as `results-jev-402.json` and `run-jev-402.log`; it holds valid pointers and invalid verdicts.

## Where each number of an answer comes from

Code reads every number in an answer and looks for it in the routed paper's clause-base sentences, table rows and
figure facts.

| | fresh (80 answers) | big library (388) | all (468) |
|---|---|---|---|
| numbers | 307 | 1,282 | 1,589 (3.4 an answer) |
| printed in the paper (a pointer found) | 276 | 1,164 | 1,440 (91%) |
| derived from the answer's other numbers in one step | 24 | 66 | 90 (6%) |
| the answer's own written arithmetic gives it | 3 | 39 | 42 (3%) |
| printed nowhere in the paper | 4 | 13 | 17 (1%) |

## Against the blind grades

| answer | right | partial | wrong |
|---|---|---|---|
| every number pointed or computed | 308 | 5 | 80 |
| a number printed nowhere | 2 | 0 | 7 |
| no number | 57 | 1 | 8 |

- **Numbers that point nowhere are rare and mostly wrong:** 9 answers, 7 of them wrong. Holding those back would
  take wrong answers delivered from 95 of 468 (20%) to 88 of 459 (19%), at a cost of 2 right ones.
- **Most wrong answers have every number in the paper:** 80 of 95 have each number printed there or computed from
  printed ones. The numbers exist, but are given for another thing, row or condition. Finding the number is not enough; whether it is the number for what the answer says is
  the binding check Jev does, which did not run here.

## Not run

The Jev checker (binding check). On the bench it cut wrong answers delivered from 19% to 8%, holding back 22–32% of
right ones. It needs Jev credits; rerunning `check.py` reuses everything above.
