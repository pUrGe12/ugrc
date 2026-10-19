# Multi-step questions on the 11 papers: Haiku, two arms, three runs, door v5

**Question.** `experiments/bench-leads` was too easy to tell the arms apart (520 of 528 right). Do questions
that need two or more facts from different places, or a value computed from them, separate the arms, and
what do they break?

**Setup.** The 11 papers and two arms of `experiments/bench-leads` (`plain`: the substrate alone; `leads`: the
same substrate with its clause base). 66 probes, 6 per paper (`probes.json`), written from each paper's
extracted text before any run and frozen by hash (`frozen.sha256`). Mix: 21 chained lookups (H), 23
computations (X), 9 multi-step table questions (T), 2 count / cross-table (K), 11 false premises inside a
multi-step question (F). Door v5 (clause-base ids as a quote's atom, quotes down a wrapped cell, cut cells and
lead-in words refused). `claude-haiku-5-5`, effort high, three runs per arm: 396 answers, $1.23. Receipt
GREEN for all 396. Graded as before (`grade.py`): the automatic check, then by hand every answer it failed
(22) and a seeded 15% sample of its passes (53, all right): `hand.json`. Then every computed percentage in
both benches was read, which found what the check and the sample had missed (below).

## Results

| arm | run | correct | partial | wrong | answers with a format gap | refused submissions | median tools | cost |
|---|---|---|---|---|---|---|---|---|
| plain | 1 / 2 / 3 | 65 / 65 / 65 | 0 | 1 / 1 / 1 | 0 | 88 / 93 / 97 | 5–6 | $0.64 |
| leads | 1 / 2 / 3 | 64 / 61 / 63 | 2 / 2 / 2 | 0 / 3 / 1 | 0 | 104 / 92 / 94 | 5 | $0.59 |

- **The arms still do not differ significantly,** but this time the leads look worse: per probe, leads better
  on 1, worse on 5, equal on 60 (sign test p = 0.22). All 6 partials are in the leads arm. In three of them,
  aenm-2022-X3, Haiku took the review's "nearly eightfold" DOE figure for the 2008–2020 cost factor, or gave
  no factor. In two, nanolett-6b05172-H2, it gave the general "<1 nm" micropore limit (the confinement
  requirement) instead of the measured ~0.5 nm. In one, cai2026-F1, the status and company sat in support
  quotes behind nouns ("status [2] and company [3]"), a gap the lead-in rule does not catch. Two of these
  look like anchoring on a lead sentence, as prof-T1 did in `experiments/leads`.
- **Every wrong answer has one cause: a percentage scaled twice.** The sql multiplies by 100 and `fmt: pct1`
  multiplies again, so the reader sees "8,270.3%" for 82.7%, "3,333%" for 33.3%, "41.67%" for 0.42%. That
  is 7 answers (3 plain, 4 leads), and all 9 pct-formatted computations in the two benches have it: Haiku
  never used `pct` correctly. Its right percentages came from `fixed1` over a `* 100`. Every pointer resolves
  and the receipt is GREEN, because the door checks where a number came from, not what it means. One of the
  9 is in `experiments/bench-leads` (plain-r1 nanolett-6b05172-X1, "5,286%"), which was first reported with 0
  wrong answers; its RESULTS.md is corrected.
- **Format gaps are gone:** 0 answers, against 35 of 528 in `experiments/bench-leads`. The door refused 52
  submissions for lead-in words (29 leads, 23 plain), and every one was fixed.
- **Wrapped cells:** 44 `quote:wrapped` refusals (27 leads, 17 plain); 36 accepted quotes run down a wrapped
  cell. The cell that caused the earlier partials (Cai Table 1, "Phase 1 / Completed") is now shown whole in
  every answer about it.
- **Clause-base ids as addresses:** 7 quotes were placed by a sentence or value id. `quote:absent`
  refusals are now 14 in each arm, where the leads arm had 30 against 17.
- **The pairing gate (Jev) refused 23 times** in the leads arm (7 in the 11-paper bench). These verdicts are
  part of the judge comparison in `experiments/laya-bench`.
- **Computation is the weak spot:** X is the only category below 95% in either arm (plain 66/69, leads 62/69).
  Counting (K) and multi-step table questions (T) were all right, and so were the false premises (F, 65/66).
- **A smaller door gap** was seen in passing: a quote may start at the beginning of a line whose previous line
  ends in a hyphen ("bility product Ksp" from "solu-" / "bility"), which shows half a word.

## What follows

1. **Done (door v6):** a `pct` run whose sql already multiplies by 100 is refused (`sql:pct-scaled`), with the
   moves "keep the * 100 and use fmt fixedN, or drop the * 100". Replayed over the 924 answers of both benches,
   it refuses exactly the 8 answers holding the 9 double-scaled computations, and nothing else.
2. Extend the hidden-citation rule to support quotes that hold the asked value behind a noun ("status [2]"),
   e.g. a support quote that is a whole table cell or holds a number.
3. Refuse a quote that starts mid-word at a line start after a hyphenated line end.
4. Leads: the two anchoring partials argue for showing table rows in the leads (the clause base has no cells).

## Files

`probes.json` + `frozen.sha256`, `run.py`, `grade.py` (`sheet` / `report`), `hand.json`, `answers/<arm>-r<k>/`
(396 records), `run.log`.
