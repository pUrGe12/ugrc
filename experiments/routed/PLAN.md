# The routed test: frozen plan

Written 2026-10-31 and frozen by hash (`frozen.sha256`: this plan, `GRADING.md`, `run.py`, `routes.json`) before any
answer of this test existed. `run.py answer` refuses to run if any of them, or the library test's frozen files, changed.

## The question

The library test (`experiments/library/`) gave the model 10 papers and a question that names none of them. The model
seldom used a wrong paper (5 of 738 answers), and keyword search ranks the question's paper first for 244 of 246
questions. What cost accuracy was the long prompt: with 10 papers, facts+prose 132 of 246, picked pages 128, facts 113;
with the one paper in view, the same questions in their original wording got 181, 152 (pasted PDF) and 156 (mean per
run). So: let search pick one paper and give the model only that paper. Does that recover the one-paper results?

## Known before any answer

- **Routing** (`run.py route`, `routes.json`, no model): 244 of 246 questions go to their own paper. The 2 misses:
  `cheme2/fluidized-bed/B1` goes to `cheme/reactor` (its own paper ranks 2nd); `cheme2/distillation/A1`, an absence
  question, goes to `cheme/distillation` (its own paper ranks 4th).
- **Prompts:** given the original wording, all 492 prompts are byte-identical to those of the earlier one-paper tests
  (prose: `experiments/prose` for `cheme`, `experiments/cheme2`; pdf: the `llama-direct` arms of `cheme` and
  `cheme2`, run 1). Only the question's wording differs, and for 2 questions the paper.
- **Sizes** (characters / 3.6): prose mean 7.4k tokens, max 12.1k; pdf mean 18.5k, max 32.1k.

## Questions and libraries

The library test's 246 reworded questions and its 3 libraries, answer keys unchanged (`experiments/library/
questions.json`, `libraries.json`; their hashes are checked before answering).

## Router

Every pdftotext page of the question's 10 library papers, headed `=== <title>, page N ===` (the library test's pages
arm), ranked by the hybrid's BM25 on the question. The question goes to the paper of the top-ranked page. No model.

## Arms

| arm | what the prompt holds | tokens |
|---|---|---|
| `prose` | the routed paper in the facts+prose form: `prose/run.py`'s `document()` and `prompt()`, as cheme2's prose arm | 7.4k |
| `pdf` | the routed paper's pdftotext with `bench-llama/direct.py`'s prompt, as cheme2's pdf arm | 18.5k |

- **Model and sampling:** as every Llama arm: Llama 3.1 8B Instruct, bf16 on vLLM (Modal, L40S), temperature 0.6,
  top_p 0.9, at most 4,096 output tokens, one reply, no tools.
- **One run per arm:** 246 x 2 = 492 answers, as the library test's one run per arm.
- **Spend:** about 10 minutes of server time, near $0.35 of the $1.64 Modal credit left on 2026-10-31.

## Grading

- **Blind** between the two arms: each question's 2 answers under letters A-B in an order drawn by `routed:<key>`;
  which arm a letter is stays in code until `grade.py unseal`. Grades are hashed (`graded.sha256`) before unsealing.
- **Rules:** the library test's (`../library/GRADING.md`: 1-29 and L1-L5) and R1 in `GRADING.md` here.
- **Grader:** Claude, as in the library test. The library test's answers were graded and unsealed earlier the same day,
  so comparisons with its arms cross grading sessions.

## What gets reported

- **Right of 246 per arm,** and prose - pdf: sum of per-question differences, better / worse counts, exact paired
  sign-flip p (`blind.exact_p`).
- **Against the library test's arms,** paired by question (graded in another session): routed prose - library prose,
  routed prose - library pages, routed pdf - library pages.
- **Against one paper in view** (the earlier tests' grades, original wording, mean per run), descriptive.
- **By category and by set;** the 2 misrouted questions; mean prompt tokens.
- **Expected:** routed prose near its one-paper result and above every library arm; routed pdf near its one-paper
  result. No outcome is excluded.
