# A fresh paper enters the 120-paper library: results

Run 2026-11-01 under the frozen plan (`PLAN.md`, `frozen.sha256`). 10 ChemE papers no earlier test had seen, each
added alone to the big-library test's 120 papers, 80 new questions written before any answer. Llama 3.1 8B, one run,
graded blind (`grade.py`; rules `GRADING.md`, `GRADING-settled.md`; grades hashed in `graded.sha256` before unsealing).

## Adding a paper (no question yet)

| paper | pages | ingest | clause base | Jev calls | values (of them labels) | tables found / printed | text tokens | facts tokens |
|---|---|---|---|---|---|---|---|---|
| gasification | 14 | 14 s | 61 s | 1,144 | 375 (67) | 1 / 2 | 18,493 | 5,320 |
| techno-economic | 20 | 22 s | 61 s | 1,120 | 313 (133) | 0 / 11 | 23,026 | 3,851 |
| catalytic | 12 | 6 s | 37 s | 747 | 264 (97) | 1 / 1 | 11,555 | 4,136 |
| adsorption | 13 | 15 s | 50 s | 1,053 | 434 (73) | 0 / 4 | 12,840 | 3,274 |
| pyrolysis | 10 | 12 s | 44 s | 883 | 329 (81) | 4 / 8 | 12,929 | 4,749 |
| co2-capture (review) | 19 | 17 s | 59 s | 1,029 | 293 (106) | 0 / 10 | 31,006 | 6,094 |
| wastewater-treatment (review) | 24 | 16 s | 37 s | 628 | 196 (109) | 8 / 8 | 30,676 | 7,768 |
| crystallization | 11 | 12 s | 41 s | 837 | 280 (97) | 0 / 1 | 14,388 | 4,121 |
| reactor (review) | 16 | 11 s | 47 s | 894 | 290 (168) | 1 / 1 | 23,144 | 6,399 |
| mass-transfer | 20 | 22 s | 54 s | 1,055 | 321 (96) | 0 / 2 | 26,982 | 7,129 |
| **total** | **159** | **147 s** | **491 s** | **9,390** | **3,095 (1,027)** | **15 / 48** | **205,039** | **52,841** |

About a minute a paper (15 s ingest, 49 s clause base), ~940 Jev calls, every paper on the first try. Nothing about
the other 120 papers changes. Tokens are characters / 3.6. Ugrc's extractor found 15 of the 48 tables these papers
print (the 120 library papers: 212 of 402); none at all in 5 papers, all ACS Omega. The facts form still carries
those tables' rows as lines of text, see below.

## Finding the paper (no model)

- **80 of 80** questions route to their own paper over 121 papers, and over all 130 at once.
- **The old questions are undisturbed:** with the 10 fresh papers in, 1 of the 388 big-library questions changes paper
  (bench/nanolett-6b05172/A1, now to its own: 382 right against 381); none goes to a fresh paper.
- Search's unsure score reaches 0.85 for 1 question (routed right).

So the `oracle` arm (the right paper's facts+prose) had nothing to answer: its prompt is top1's for every question.

## Answers

| arm | right of 80 | partial | wrong | prompt tokens (mean / max) |
|---|---|---|---|---|
| **search picks the paper, then its facts+prose** (top1) | **63** (79%) | 1 | 16 | 6,724 / 9,965 |
| the right paper handed over as facts+prose (oracle) | 63 (= top1) | | | |
| the right paper's whole PDF text pasted (pdf) | 50 (62%) | 4 | 26 | 20,575 / 34,864 |

- **top1 - pdf: +13** (17 better, 4 worse, 59 equal), exact paired sign-flip **p = 0.0072**.
- **top1 - oracle: 0**; routing costs nothing here.
- **Recounts** (counting `[hedge]`, `[label]` and the rule-25 slip right): top1 68, pdf 53. N2 (a table that disagrees
  with itself) gave both answers the same grade.
- One pdf answer (pyrolysis/H1) ran to the 4,096-token cap in a loop; it was wrong.

By category (right, top1 / pdf):

| | lookup | binding | table | computation | chained | false premise | absence |
|---|---|---|---|---|---|---|---|
| top1 | 12 / 12 | 10 / 10 | 13 / 18 | 5 / 10 | 5 / 10 | 8 / 10 | 10 / 10 |
| pdf | 11 / 12 | 8 / 10 | 9 / 18 | 3 / 10 | 5 / 10 | 5 / 10 | 9 / 10 |

- **Table questions** where ugrc found no table: top1 6 of 9, pdf 5 of 9. Where it found one: top1 7 of 9, pdf 4 of 9.
- **By paper** (top1 / pdf): crystallization 8 / 7, gasification 7 / 5, co2-capture 7 / 6, mass-transfer 7 / 4, reactor
  7 / 3, catalytic 6 / 7, pyrolysis 6 / 4, wastewater-treatment 6 / 6, techno-economic 5 / 3, adsorption 4 / 5.

## What it says

- **A new paper costs about a minute and needs nothing from the rest of the library.**
- **The setup did as well on unseen papers and unused questions as on the old ones:** 79% here, against 78% (304 of
  388) on the 120-paper library and 75% (cheme2, facts+prose, one paper in view).
- **It beat the whole pasted PDF** by 13 of 80 from a third of the prompt.
- **It still fails on:**
  - computation, where the commonest miss is saying a printed input is not there (pdf 4 times, top1 twice;
    catalytic/X1 in both);
  - chained lookups, mostly the second link from the wrong row (adsorption/H1, pyrolysis/H1, techno-economic/H1).

## Caveats

- **Sample size:** 10 papers and 80 questions, one run.
- **Questions:** Claude wrote and graded them, as in every earlier test.
- **Easier routing than real use:** the questions carry subject phrases, as the big library's did. Short questions
  without them routed 360 of 388 there, against 381.
- **One fresh paper at a time:** each question's library had 121 papers. All 130 at once was checked for routing only.
