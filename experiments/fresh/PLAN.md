# A fresh paper enters the 120-paper library: frozen plan

Written 2026-11-01 and frozen by hash (`frozen.sha256`: this plan, `GRADING.md`, `run.py`, `grade.py`, `fetch.py`,
`papers.json`, `questions.json`, `routes.json`, `intake.json`) before any answer of this test existed. `run.py answer`
refuses to run if any of them, or the big-library test's frozen files, changed.

## The question

The best setup so far for Llama 3.1 8B over a library: keyword search (BM25 over every page) picks one paper, then the
model gets only that paper's facts+prose form. On the 120-paper library it got 304 of 388 right, as many as with the
right paper handed over. But every paper in that test had been ingested, and most of its questions had been used in
earlier tests. The user asked: describe the setup for a fresh paper entering an already large corpus, run it, and give
numbers. So:

1. What does it take to add a new paper (time, model calls, what the stores hold)?
2. Do its questions find it among 120 others, and do the new papers pull any old question away?
3. How many questions about it does the setup answer right, against the paper handed over and against its whole PDF?

## The papers

`fetch.py`, run once before any paper was read: cheme2's Europe PMC search (RSC Advances or ACS Omega, open access,
2025-26, newest first) re-run on 2026-11-01 for cheme2's 20 topics, in an order drawn by the seed "fresh-paper". Per
topic, the newest hit in none of the library's ChemE sets that passes cheme2's filters (5-25 pages, at least 15,000
characters of text, a line starting "Table 1"), until 10 papers. Fluidized bed had no eligible paper. All 10 ingested
with extractor v5 (frozen, `../cheme/extract.sha256`) and got a Jev clause base on the first try (`prepare.log`).

| key | paper | published |
|---|---|---|
| gasification | carbide slag-assisted steam gasification of sewage sludge | 2026-10-15 |
| techno-economic | stacking-learning proxies for CO2-WAG optimization | 2025-03-03 |
| catalytic | Ni–Ag/rGO for 4-nitrophenol reduction | 2026-10-15 |
| adsorption | coal permeability and adsorption capacity after oxidation | 2026-10-12 |
| pyrolysis | corn straw–oil sludge composite pellet fuel | 2026-10-12 |
| co2-capture | review: hydrate-based CO2 capture | 2025-10-31 |
| wastewater-treatment | review: magnetic iron oxide nanoparticles in mixed matrix membranes | 2026-04-07 |
| crystallization | Sn-incorporated GST thin films for terahertz sensing | 2026-06-01 |
| reactor | review: lithium-mediated ammonia electrosynthesis | 2026-07-02 |
| mass-transfer | Pd/Cu on TiO2 and g-C3N4 for photocatalytic ozonation | 2026-10-13 |

Every topic already has 2-4 papers in the library (cheme, cheme2, cheme3), so each fresh paper lands among close
neighbours.

## Questions

80 (`questions.json`), 8 a paper in the earlier categories: lookup (C), binding trap (B), two table (T), computation
(X), chained lookup (H), false premise (F), absence (A). Where a paper prints one usable table, the second T is a second
lookup (catalytic, crystallization). Written by Claude from each PDF's pdftotext (plain and `-layout`) only, before any
answer, never from ugrc's atoms, the clause base or a prompt. Worded as the big library's questions were: no table,
figure or section numbers, no "the paper"; a subject phrase naming the paper's subject wherever the question would fit
another library paper.

## The library and the router

For each question, the library is the big-library test's 120 papers (`../big-library/papers.json`) plus that
question's fresh paper: 121 papers. The router is unchanged: BM25 over every pdftotext page, headed `=== <title>, page
N ===`, the question goes to the paper of the top page (`run.py route`; the big library's tokenizer and formula, with
the page scores kept). Also recorded, no model: routing over all 130 papers at once, search's unsure score (second
paper's best page score over the first's), and whether the 388 old questions change paper with the 10 fresh papers in
(`run.py old`).

Known before freezing (no model): all 80 questions route to their own paper over 121 papers and over 130, so the
`oracle` arm has nothing to answer (its prompt is top1's for every question). Of the 388 old questions, one changes
paper with the 10 fresh papers in (bench/nanolett-6b05172/A1, now to its own paper: 382 right against 381), none to a
fresh paper (`old-routes.json`).

## Arms

| arm | prompt |
|---|---|
| `top1` | the winning setup: the routed paper's facts+prose form (`routed/run.py prompt("prose")`) |
| `oracle` | the question's own paper's facts+prose form; answered only where top1 picks another paper (elsewhere it is top1's prompt, byte for byte) |
| `pdf` | the question's own paper's whole pdftotext, pasted (`routed/run.py prompt("pdf")`): the right paper handed over as a whole PDF |

Llama 3.1 8B Instruct, bf16 on vLLM (Modal, L40S), temperature 0.6, top_p 0.9, at most 4,096 output tokens, one reply,
no tools, one run per arm: 80 + 80 + misrouted answers. The app is stopped right after the run.

## Grading

- **Blind:** each question's answers (2, or 3 with oracle) under letters in an order drawn by `fresh:<key>`; which arm
  a letter is stays in code until `grade.py unseal`. Grades are hashed (`graded.sha256`) before unsealing.
- **Rules:** `GRADING.md`.
- **Grader:** Claude, who also wrote the questions.

## What gets reported

- **Intake:** per paper and in total, ingest and clause-base seconds, Jev calls, tables found against tables printed,
  pages, and prompt sizes.
- **Routing:** right paper first over 121 papers, in the top 2, over 130; old questions moved.
- **Right of 80 per arm**, and top1 - pdf (primary), top1 - oracle (what routing costs), oracle - pdf: sum of
  per-question differences, better / worse counts, exact paired sign-flip p (`blind.exact_p`).
- **By category and by paper.** Descriptive: asking the user when search is unsure (unsure ≥ 0.85, as short-route),
  with flagged questions taking oracle's answer.
- **Expected:** from the big library (78% right, routing ~98%) and cheme2 (facts+prose 75% against the PDF's 60%),
  top1 near 60 of 80 and ahead of pdf. No outcome is excluded.
