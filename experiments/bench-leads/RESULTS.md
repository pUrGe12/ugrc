# Leads on 11 more papers: Haiku, two arms, three runs each

**Question.** Do leads and measure runs (door v4) help a weak answering model on papers they were never tuned
on? The first test (`experiments/leads`) used the 71 questions the leads' recall was measured on, one run per
arm, and could not separate the arms from run-to-run noise.

**Setup.**
- **Papers:** the 10 battery papers, each on its own (the clause bases of `experiments/jev-bench/runs/v8`), and
  paper 1 (Cai, a review with 795 table cells; its clause base built here: 1,236 Jev calls, ~$0.03, clause
  receipt GREEN). None of them was used to build or tune the leads.
- **Probes:** 8 per paper, 88 in all (`probes.json`), written from each paper's extracted text, not from its
  clause base, before any run, and frozen by hash (`frozen.sha256`; `run.py` refuses to run if it changed).
  Mix: 24 lookups, 19 binding traps, 15 table, 11 false premises, 11 absences, 7 computations, 1 figure.
- **Arms:** `plain` is the substrate with no clause base beside it; `leads` is the same substrate with its
  clause base (leads with each question, measure runs, pairing gate). `claude-haiku-5-5`, effort high, three
  runs of each arm: 528 answers, $1.01 in all. Receipt GREEN for all 528 (the leads arm's against each
  clause base's seal).
- **Grading** (`grade.py`): an automatic check against each probe's key, then by hand every answer the check
  failed (20) and a seeded 15% sample of the ones it passed (78): `hand.json`. All 78 sampled passes were right,
  so the check gave no false passes in the sample. 12 of its 20 failures were right answers worded differently
  from the key ("recruitment" for "recruiting"). Partial means an asked value or fact does not reach the
  reader. Format gaps (a hidden citation where the reader expects words) are counted by `gaps.py`, which agreed
  with the hand grades of the first test on 71 of 71 answers.

## Results

| arm | run | correct | partial | wrong | answers with a format gap | refused submissions | mean tools | cost |
|---|---|---|---|---|---|---|---|---|
| plain | 1 / 2 / 3 | 86 / 86 / 86 | 1 / 2 / 2 | 1 / 0 / 0 | 5 / 6 / 7 | 109 / 102 / 108 | 5.1 | $0.52 |
| leads | 1 / 2 / 3 | 88 / 87 / 86 | 0 / 1 / 2 | 0 | 5 / 8 / 4 | 110 / 118 / 118 | 4.9 | $0.49 |

- **The arms do not differ.** Per probe, counting correct runs out of three: leads better on 4, worse on 1,
  equal on 83 (sign test p = 0.38).
- **Both arms are near the ceiling: 519 of 528 answers correct, one wrong.** Every false premise (66 answers)
  and every absence (66) was handled in both arms, including two traps in the papers themselves: aenm-2022's
  sentence that contradicts its own heat-release numbers, and nanolett-6b05172's G/D peak assignment printed in
  reverse. These probes are too easy to separate the arms. That is a finding about ugrc as much as about the
  leads: with every number a checked pointer, Haiku produced one wrong answer on 11 new papers, and that one
  is a computed value scaled twice (below).
- **Correction (after `experiments/bench-multistep`).** plain-r1 nanolett-6b05172-X1 shows "5,286%" for
  370/700 = 52.9%: its sql multiplies by 100 and `fmt: pct1` multiplies again. The automatic check passed it
  (the key's "50" matched the paper's "over 50%"), and it was outside the hand sample. It was found by
  scanning every pct computation, after the multi-step bench showed the same error 8 times. First reported
  as 0 wrong.
- **The 8 partials:** 5 are one table cell that wraps onto the next printed row (cai2026 Table 1, NBF-006's
  status "Phase 1 / Completed"; both arms, 3 + 2). The door never joins printed rows, so the answer shows only
  "Phase 1". The other 3 are asked values hidden in support citations (2 plain, 1 leads).

## What the leads changed

- **Measure runs were used in 123 of 264 answers, with no `measure:*` refusal.** 21 leads answers (8%) came
  from the leads alone, with no search; no plain answer did. Mean tool calls fell only from 5.1 to 4.9, and the
  leads add tokens (median 29.8k read per answer against 26.6k).
- **Refusals rose (346 vs 319), and the cause is the leads.** 13 of the leads arm's 30 `quote:absent`
  refusals (in 10 answers) put a sentence or measure id (`p8.L26:32#181`) where a quote run needs a line id.
  The other 17 match the plain arm's 17. Fix: let the door resolve a sentence or measure id in a quote's
  `atom` to that sentence's lines, recorded as `relocated_from`.
- **The pairing gate refused 7 times, and was right only twice.** Right: "4 mA/cm² of the carbon nucleation
  layer" (the value is the test current, not a property of the layer), twice. Wrong: "35 [wt%] of sulfur"
  (four times; the clause base itself gives it for "wt % sulfur") and "600 °C for the cathode powder" (its
  calcination temperature). Every refused answer was fixed and accepted, so this cost turns, not
  correctness. In the first test all 6 of its refusals were right. Its false refusals are where a judge with
  better calibration (Laya) could be measured directly.
- **Format gaps did not change:** 18 plain answers, 17 leads answers.

## What follows

1. Resolve sentence and measure ids given as a quote's `atom` (the 13 extra refusals).
2. Join a table cell with the printed rows it wraps onto when they are one cell (the 5 partials).
3. The format gap is the same in both arms: fix it in the door (refuse a text run that leads into a hidden
   quote), as `experiments/leads/RESULTS.md` proposed.
4. To compare arms, the probes need to be harder: multi-hop, cross-section and table-heavy questions, and
   papers whose values sit mostly in tables.
5. A judge swap (Jev → Laya) can be tested on the pairing gate's verdicts here: 207 checked pairings, 7 refusals,
   5 of them wrong.

## Files

`probes.json` + `frozen.sha256`, `run.py`, `grade.py` (`sheet` / `report`), `gaps.py`, `hand.json`,
`answers/<arm>-r<k>/` (528 records), `run.log`, `clauses/cai2026/` (Cai's clause base and its log).
