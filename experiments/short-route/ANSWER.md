# Short questions: how many answers does it cost? Frozen plan

Written 2026-11-01, after `route.py` and before any answer to a short question. Frozen by hash (`answer.sha256`: this
plan, `GRADING.md`, `answer.py`, `routing.json`) before `answer.py answer` runs; `answer.py` also checks `frozen.sha256`
and the big-library test's frozen files.

## The question

`route.py` found that search sends 360 of the 388 short questions to their own paper, against 381 for the long ones.
That counts routes, not answers. Here the model answers the short questions, so the cost is measured:

1. How many right answers does the short form lose against the long form, both routed by search (big-library `top1`)?
2. How much of that is routing (another paper) and how much is wording (the right paper, fewer words)?

## Arms

| arm | question text | paper |
|---|---|---|
| `long` | the long form | search on the long form: the big-library test's `top1` answer, reused as it stands |
| `short` | the short form | search on the short form, top paper (`routing.json`, `short.routed`) |
| `short-oracle` | the short form | the question's own paper |

- **Prompt:** the routed test's prose prompt (`routed/run.py prompt("prose", question, paper)`), as big-library `top1`:
  the paper's facts+prose form, with its 30 sentences chosen by BM25 on the question text the arm uses.
- **Unchanged questions (131):** the short form is the long one, so search picks the same paper and the prompt is
  `top1`'s byte for byte (`answer.py check` verifies every one). No new answer: `short` is big-library `top1`, and
  `short-oracle` is big-library `oracle` (3 questions, all misrouted in both forms) or `top1`.
- **New answers:** `short` for the 257 changed questions, `short-oracle` for the 25 of them search sends elsewhere: 282.
  Elsewhere `short-oracle`'s prompt is `short`'s, and `short`'s answer stands for it.
- **Model and sampling:** as every Llama arm: Llama 3.1 8B Instruct, bf16 on vLLM (Modal, L40S), temperature 0.6,
  top_p 0.9, at most 4,096 output tokens, one reply, no tools. One run.
- **Spend:** about 10 minutes of server time plus a 4-minute cold start, near $0.30 of Modal; the app is stopped after.

## Grading

- **Blind:** for each of the 257 changed questions, the `long` answer (graded before in the big-library test, graded
  again here), the `short` answer and, where search misroutes the short form, the `short-oracle` answer, under letters
  in an order drawn by `short-route:<key>`. Which arm a letter is stays in code until `grade.py unseal`; grades are
  hashed (`graded.sha256`) before unsealing.
- **The sheet** shows the long and the short form of the question, its paper's title, the expected answer, the trap,
  and the papers any of the question's prompts held, sorted by name (not by arm).
- **Rules:** big-library's (`../big-library/GRADING.md`, `GRADING-settled.md`) and Q1-Q2 in `GRADING.md` here.
- **Grader:** Claude. Unchanged questions are not graded again; their big-library grades stand.

## What gets reported

- **Main, on the 257 changed questions:** right per arm; `short - long`, `short-oracle - long` (wording),
  `short - short-oracle` (routing): sum of per-question differences, better / worse counts, exact paired sign-flip p.
- **All 388:** each arm's total, adding the unchanged questions' big-library grades (the same for `long` and `short`).
- **Misrouted short questions (28):** right for `short` and `short-oracle`; absence questions apart.
- **By set and category.**
- **Grader drift:** this test's `long` grades against the big-library test's grades of the same answers.
- **Post hoc, descriptive:** asking the user when search is unsure (`unsure.json`, cut-offs 0.8, 0.85, 0.9): flagged
  questions take `short-oracle` (the user picks the right paper), the rest `short`.
- **Expected:** from route counts and the big-library grades of misrouted answers, about 16 fewer right of 388 than
  `long`. One sample per arm, so single questions flip by chance either way; the paired test counts that. No outcome is
  excluded.
