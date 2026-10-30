# Does Jev help the hybrid pick pages? Frozen plan

Written 2026-10-21 and frozen by hash (`frozen.sha256`, with `questions.json`) before any answer of this test
existed. `hybrid.py corpus` refuses to run if either file changes.

## The question

In the hybrid (`experiments/bench-cross/hybrid.py`: code picks pages, Llama 3.1 8B answers in one reply, code points
each number at the atom that prints it), do Jev's leads pick better pages than word ranking (BM25) alone? If they do,
is it Jev's readings, or the lead search code around them?

## What is known before this test

- The earlier test (61 questions where the page budget binds, 3 runs per arm): leads 109, BM25 97 right of 183.
  Per question 14 better with leads, 6 worse: sign test p = 0.12; the exact paired test on right runs p = 0.08.
  On 17 of the 61 questions both arms were given the same pages, so their splits are noise; on the 44 whose pages
  differed, p = 0.039. That cut was chosen after seeing the results, so it is a hypothesis for this test, not a
  finding.
- With no model (`retrieval.py`): BM25 alone puts every page the answer key cites in the prompt at least as often as
  the leads do, at every budget and on every question set. If the leads help, it is through the other pages they
  add.

## Stage 1: leads against BM25

- **Questions:** `questions.json` `stage1`: the 114 single-paper questions (bench-leads, bench-multistep; cai2026 is
  not in the corpus) for which BM25 and the leads pick different pages at the hybrid's 24k-token budget on
  `runs/papers-corpus`, as `retrieval.py` computed them. On the other 26 the two arms send the same prompt, so
  they could show only run-to-run noise.
- **Asked as:** `About the document "<title>" (<key>): <question>` (`hybrid.corpus_question`, as bench-llama's
  corpus arm asks), over the 10-paper corpus. This is the setting the hybrid is meant for: a library too large for
  the prompt, where pages must be picked for every question.
- **Arms:** `llama-hybrid-corpus` (the leads' pages first, then BM25) and `llama-hybrid-corpus-bm25` (BM25 alone).
  Everything else is the hybrid as it is: the same system prompt, 24k-token budget, Llama 3.1 8B Instruct bf16 on the
  Modal vLLM server, temperature 0.6, top_p 0.9, at most 4,096 output tokens, one reply.
- **Runs:** 3 per arm. Every answer is run; nothing stops early on results. A question whose server failed is run
  again; an answer is never re-run because of its content.
- **Grading:** every answer by hand, blind to arm: `blind.py sheet` shows each question's 6 answers under letters in
  an order shuffled by a fixed seed, and the arm is unsealed only after grading. Verdicts and rules as in
  `bench-llama/HANDOFF.md` (correct / partial / wrong; a computed value within 0.5% of the key counts as right). The
  question names its paper, so a value or claim taken from another paper is wrong. One grader (Claude).
- **Primary measure:** per question, d = (runs right with leads) − (runs right with BM25), from −3 to 3. Only
  "correct" counts as right.
- **Primary test:** the exact two-sided paired sign-flip test on the sum of d, α = 0.05. The leads help if p < 0.05
  and the sum is positive; hurt if p < 0.05 and it is negative; otherwise no difference is shown.
- **Also reported, not used for the decision:** right answers per run and arm; the sign test on questions with
  d ≠ 0; d by category and by paper; the same test pooled with the earlier test's 44 questions whose pages differed.

## Stage 2: Jev's readings against the lead search code (only if stage 1 finds the leads help)

- **Arm:** `llama-hybrid-corpus-text`: the same lead search with Jev's part left out (`hybrid.JEV_OFF`: no clause-base
  readings of what each value is of, by what method, what it measures; no aliases the judge accepted), then BM25.
  3 runs.
- **Questions:** `questions.json` `stage2`: the 105 questions of stage 1 where this arm and the leads pick
  different pages. The leads' stage-1 answers are reused.
- **Test:** the same, with d = (runs right with leads) − (runs right without Jev's readings). Jev's readings help
  if p < 0.05 and the sum is positive.
- If stage 1 does not find that the leads help, stage 2 is not run, and Jev's part in page picking is reported as
  not shown.

## Cost

About $0.0037 per answer on the Modal server (the earlier test: 305 answers, $1.12). Stage 1: 684 answers, about
$2.50. Stage 2: 315 answers, about $1.20. About $11.80 of the month's credit was left before stage 1.
