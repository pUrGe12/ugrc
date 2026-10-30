# Llama reasoning on the clause base: frozen plan

Written 2026-10-22 and frozen by hash (`frozen.sha256`, with `questions.json`) before any answer of this test existed.
`run.py` refuses to run if either file changes.

## The question

Through ugrc's protocol (search by SQL, answer in pointer runs the door checks) Llama 3.1 8B gets 34 of the 154
single-paper questions right; reading text and answering in its own words it gets 107 (pdftotext) to 119 (the hybrid).
The protocol is the obstacle. Here it is removed entirely: Llama gets the paper's clause base, what Jev read from its
prose, and answers in one reply. Does reasoning on Jev's readings make it more accurate than reasoning on the same
sentences without them?

## Arms

- **`llama-clauses`:** every sentence of the paper's clause base in reading order, marked with Jev's modality (result,
  method, interpretation, possibility, background, other) and polarity, and under it every value the sentence prints
  with Jev's reading: role, property, what it is of, by what method, what it measures. The system prompt says what the
  marks and readings are, and that they can be wrong.
- **`llama-clauses-text`:** the same sentences, in the same order, with nothing of Jev's.
- **Both:** every table row by row (caption and column headers first) and every figure fact, page by page, as the
  hybrid renders them, since the clause base reads prose only. All 526 lines the answer keys cite lie inside
  clause-base sentences. Same model and server as every Llama arm (Llama 3.1 8B Instruct, bf16, vLLM on Modal),
  temperature 0.6, top_p 0.9, at most 4,096 output tokens, one reply, no tools, no SQL, no door, no pointers.

## Questions and runs

- `questions.json`: all 154 single-paper questions (bench-leads 88, bench-multistep 66), each asked of its own paper's
  whole clause base (5k to 48k tokens).
- One run per arm (308 answers, about $1.20). This is a first look: it can show a large difference, not a small one.
  Any further runs are reported separately, never merged into this test.

## Grading and test

- Every answer by hand, blind to arm (`grade.py sheet`: each question's two answers under letters in a seeded order),
  under `bench-cross/jev-pick/GRADING.md`'s rules. The grades are hashed before the arms are unsealed.
- **Primary:** per question, right with readings minus right without (−1, 0, 1); exact two-sided sign-flip test,
  α = 0.05. Jev's readings help if p < 0.05 and the sum is positive.
- **Also reported, not for the decision:** totals by category and paper; numbers printed nowhere in the paper; the
  same questions' earlier grades for the hybrid (`llama-hybrid-r1`, 119) and the pasted PDF (`llama-direct-r1`, 107),
  which were graded earlier, not blind, so only as a rough reference.
