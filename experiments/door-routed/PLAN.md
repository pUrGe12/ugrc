# The door on the winning setup: plan

Written 2026-11-01, before any answer of this test. Frozen by hash with `run.py`, `grade.py` and `GRADING.md`
(`frozen.sha256`).

## The question

The winning setup (keyword search picks the paper, then Llama 3.1 8B answers freely from that paper's facts+prose
form) gave up ugrc's original promise: every number in an answer is a pointer into the paper that code checks, and an
answer with a number that does not resolve is refused. Can the door come back on the winning setup without losing
right answers? On the bench, with no routing and no facts+prose, Llama through the door got 34 of 154 right (45
questions never accepted), against 107 for the pasted PDF.

## Questions and routes

The fresh test's 80 questions (10 papers no test had seen, each added to the 120-paper library) and its routes (80 of
80 to their own paper), unchanged; `run.py` checks the fresh test's frozen files by hash before any answer. The
clause bases are the stored Jev ones; nothing is rebuilt.

## Arms

- **`top1`** (already answered): the free answer from the routed paper's facts+prose form, one reply, no tools. 63 of
  80 right in the fresh grading.
- **`door`**: ugrc's door as built, with its short prompt for a small model (bench-llama's `llama-leads-sp`, its best
  Llama arm). The question comes with its leads (the clause-base sentences code matched to it); the model has the
  `sql`, `view_figure` and `submit_answer` tools. It never types a number: each comes from a quote of a line or cell
  by id, a clause-base value by id (a measure run, which the machine quotes from its line), or a SQL query the machine
  runs. A refused submission comes back with its refusals. At most 20 turns.
- **`door-facts`**: the same, with the routed paper's facts+prose form added after the leads (the same sentences and
  tables `top1` shows, picked by the same code), each value followed by its measure id and each table cell and figure
  fact led by its atom id, so the model can point without searching. First prompt about 11,600 tokens on average
  (`door`: 3,400).

Llama 3.1 8B Instruct on the same Modal vLLM server (bf16, L40S), temperature 0.6, top_p 0.9, one run per arm.

## One difference from ugrc's door: no live judge

Jev's credits ran out (HTTP 402, 2026-11-01). The clause bases were built by Jev earlier and are used as stored, and
the leads are found by code, so neither needs Jev. The pairing gate checks a quoted value the answer says is given
`of` something in two steps: if the stored clause base already gives the value for that thing, the pairing agrees by
code, with no call; otherwise it asks Jev at answer time. `run.py` passes a judge that always fails, so the first step
runs as built and every pairing that would need the second is recorded `unchecked` and passes, as ugrc does whenever
the judge is unavailable. This tests the pointer door (every number must resolve into the paper) with only the stored
half of the binding check. The report counts pairings by verdict.

## Grading

- **Blind to arm as far as the answers allow:** each question's answers (`top1` graded again, and each door arm's
  accepted answer) go under letters shuffled by a fixed seed. Citation marks like `[1]` are removed from every answer
  before the sheet shows it. The door's terser style may still show; which letter is which arm stays in code until
  `grade.py unseal`.
- **No accepted answer:** nothing reaches the user. It is counted as not right and not graded.
- **Rules:** `GRADING.md`, which applies the fresh test's rules as settled there.
- **Grades are hashed** (`graded.sha256`) before unsealing.

## Reported

- Per arm: accepted of 80; right, partial and wrong of 80; no answer.
- `door-facts` − `top1` (primary), `door` − `top1` and `door-facts` − `door`: right answers, exact paired sign-flip test.
- What a user gets: of the answers delivered, the share right and the share wrong, per arm.
- The grader's drift: `top1`'s regrade against `../fresh/hand.json`.
- By question type. Per accepted answer: turns, refused submissions, seconds, tokens, and the pointer kinds used
  (quote, computed, search, table, figure). The door rules that refused most often.

## Decision rule, stated now

- **The door comes back on the winning setup** if `door-facts` loses no more than 4 of `top1`'s right answers (5%) on
  the regrade and the paired test does not show a loss (p >= 0.05). Every number then points into the paper by
  construction.
- **If it loses more but delivers a smaller share of wrong answers,** it is reported as an abstaining mode: right
  answers withheld against wrong ones stopped, set beside the pointers attached after a free answer (`../pointers/`:
  91% of numbers point into the paper, with no change to the answer).
- **Otherwise** pointers stay after the answer (`../pointers/`, with the Jev checker once credits return).

## Note added during the run (2026-11-01, before any door-facts answer from the model)

The first door-facts start failed on all 80 questions before any model call: `answer()` handed `use_facts` each
question's whole route record instead of its routed paper (`sizes` and `show` use another path, so they did not catch
it). The 80 crash records are kept in `answers-crashed/door-facts-r1-routes-bug/`. The one-line fix in `run.py` was
refrozen with this note; `door` was running at the time and is unaffected.

Before any grade: `grade.py`'s `delivered()` returned the answer text rather than True, which broke `progress`; it now
returns a bool. Which arms get a letter, and which letter, are unchanged (the same truth value). Refrozen.
