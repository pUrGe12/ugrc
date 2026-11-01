# The door on the winning setup: results

Run 2026-11-01 under the frozen plan (`PLAN.md`, `frozen.sha256`). The fresh test's 80 questions, search's routes
(80 of 80 to the right paper), Llama 3.1 8B on the Modal vLLM server, one run per arm. Graded blind (`grade.py`; rules
`GRADING.md`, `GRADING-settled.md`; grades hashed in `graded.sha256` before unsealing). No live judge: Jev's credits
ran out, so the pairing gate checked only what the stored clause base already gives (`PLAN.md`).

## Answers

| arm | delivered | right | partial | wrong | no answer | of delivered: right / wrong |
|---|---|---|---|---|---|---|
| **free answer from facts+prose** (`top1`, graded again) | 80 | **61** | 3 | 16 | 0 | 76% / 20% |
| the door, leads and SQL (`door`) | 68 | 16 | 3 | 49 | 12 | 24% / 72% |
| the door with facts+prose and ids (`door-facts`) | 61 | 21 | 4 | 36 | 19 | 34% / 59% |

- **door-facts − top1: −40** (3 better, 43 worse, 34 equal), exact paired sign-flip p < 0.0001. door − top1: −45
  (p < 0.0001). door-facts − door: +5 (p = 0.27).
- **The decision rule says no:** the door does not come back on the winning setup. Pointers stay after the answer
  (`../pointers/`).
- **Not as an abstaining mode either:** the door does not hold wrong answers back. It delivers more of them (59–72% of
  what it delivers, against 20%).
- **The missing judge does not explain it:** the pairing gate can only refuse an answer, never make one right, so with
  Jev the door could have had at most 16 and 21 right. Few answers named what a value is `of` anyway (24 pairings in
  68 door answers; 1 in 61 for door-facts).
- **Grader drift:** top1 was 63 right in the fresh grading and 61 now. Two answers that print a table without stating
  the asked values moved from correct to partial, by the existing rule.

## By question type (right: top1 / door / door-facts)

| lookup | binding | table | computation | chained | false premise | absence |
|---|---|---|---|---|---|---|
| 12 / 4 / 7 of 12 | 10 / 7 / 7 of 10 | 11 / 5 / 5 of 18 | 5 / 0 / 0 of 10 | 5 / 0 / 0 of 10 | 8 / 0 / 1 of 10 | 10 / 0 / 1 of 10 |

## Why it fails

- **The door pushes the model to deliver a number.** Absence questions: top1 said "not given" on all 10. Through the
  door, Llama quoted some number from the paper as the answer on 8 (door) and 6 (door-facts), such as 150 °C as a
  switching time or "0.5 wt% m^2/g" as a surface area. The door proves a quote's characters are in the paper; it
  cannot tell that they answer the question.
- **False premises go through:** 0 and 1 of 10 corrected, against 8. The door's sentence-per-value form ("X was
  <quote>") restates the question with a quoted number.
- **Computation and chained questions: 0 of 20** in both door arms. A computed number has to be a SQL query the machine
  runs. Llama rarely wrote one that passed (3 computed numbers in 68 answers).
- **The protocol costs turns:** 616–621 refused submissions per arm. The commonest rules were a number typed in the
  text, citations out of order, and a quote not found at the atom named. 12 and 19 questions ran out of 20 turns with
  nothing accepted.
- **Garbled output:** 15 of 68 and 15 of 61 accepted answers reproduce the question as their first sentence. Some run values
  together ("5718" for 57 and 18). The door joins the runs the model submits, and the 8B model often puts no spaces
  between them.
- **Facts+prose helps a little and costs a lot:** +5 right, at 3.2 times the input tokens (113,000 against 35,000 a
  question) and 97 s against 55 s.

## What it says

For an 8B model, the door is the wrong place for pointers. It turned 61 right of 80 into 16–21. The bench said the
same with no routing (34 of 154, against 107 for the pasted PDF). With the winning prompt in view, the door still
loses 40 of 61 right answers. The way to keep "every number points into the paper" on this setup is to let the model
answer freely, then attach pointers after the answer: code points 91% of numbers at a passage that prints them
(`../pointers/RESULTS.md`). A judge then checks the binding: the Jev checker, once credits return.

## Caveats

- One run per arm. The 40-answer gap is far beyond run-to-run noise (up to 4 of 33 on the bench).
- One grader, Claude, who wrote the questions. Door answers are terser and were sometimes recognisable, though their
  arm was not shown.
- The door's prompt is the short one written for a small model on the bench. A different prompt or a larger model
  could do better; Haiku through the same door did much better on the bench.
- The first door-facts start failed on a code bug before any model call; it was fixed and rerun (`PLAN.md` note).
