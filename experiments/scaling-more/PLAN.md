# More papers: frozen plan

Written 2026-10-22 and frozen by hash (`frozen.sha256`, with `papers.json`, `libraries.json` and `run.py`) before any
answer of this test existed. `run.py answer` refuses to run if any of them changes.

## The question

At 10 papers a condensed clause base gets 95 of 140 right, against 74 for PDF text, and Jev's label filter is part of
why (83 without it). Two questions:
- **Does the condensed form keep holding as the library grows past 10 papers?**
- **When the library is too big to give the model everything, which pages should go in?** Picking the hybrid's PDF
  pages and picking condensed pages are the two candidates. The second is the untested step of the proposed
  pipeline.

## The added papers

- **Source:** arXiv, fetched by `fetch.py` from two searches (`query.xml`, `query2.xml`):
  - abstract has "lithium-ion", "cathode" and "capacity";
  - abstract has "lithium-ion battery", "electrode" and "electrochemical".
- **Order:** each search in arXiv's relevance order, the first search before the second. Only these first categories
  count: cond-mat.mtrl-sci, physics.chem-ph, physics.app-ph.
- **Selection:**
  - A paper is kept when its PDF downloads and has 5 to 30 pages; 34 were kept (`fetched.json`).
  - Each kept paper is ingested and given a clause base by Jev (`prepare.sh`).
  - `papers.json` is the first 30 for which both steps succeed. No paper was chosen or dropped by hand.
- **Role:** no question is about them. They are the library's other papers, beside the 9 other corpus papers, as a
  real library is mostly papers a given question is not about.

## Libraries

- **Order:** for each of the 10 corpus papers, the other 9 corpus papers in the scaling test's order, then the 30
  arXiv papers in an order drawn by a seed (`libraries.json`).
- **Sizes:** L20 is the paper plus the first 19 of that order; L40 is the paper plus all 39.
- **Prompt order:** drawn by a seed.
- **Fit:** a library whose condensed form exceeds 120,000 tokens keeps the question's paper and drops papers from the
  end of its order until it fits. `libraries.json` records what each one holds.
- **Measured:** L20 holds 20 papers, 63k to 82k tokens condensed. All 40 papers condensed come to 157k tokens, so
  the condensed form of L40 holds 29 to 33 papers (111k to 119k tokens). The two picking arms search all 40.
- **Reference:** L10 is the scaling test's `llama-scale-facts-L10` (95 right), graded earlier.
- **Ingest:** two of the 34 kept papers failed to ingest (`ValueError: cannot write empty image`, a figure cropped to
  zero size) and were skipped by the rule above.

## Arms

| arm | what the prompt holds |
|---|---|
| `llama-more-facts-L20` | every L20 paper in the condensed form |
| `llama-more-facts-L40` | the L40 papers in the condensed form, as many as fit (29 to 33) |
| `llama-more-pages-L40` | pages picked by BM25 from all L40 papers' pages as the hybrid renders them (tables row by row), up to 24k tokens |
| `llama-more-factpages-L40` | pages picked by BM25 from all L40 papers' condensed pages, up to 24k tokens |

- **The picking:** BM25 (the hybrid's own) over every page, with the query "About the document "TITLE": QUESTION". The
  best pages go in, in order, until 24,000 tokens, and are shown in library order. A page's header names its paper.
- **The condensed form:** the scaling test's facts form, with Jev's label filter.
- **Everything else:** prompt wording, model and sampling as in the scaling test (Llama 3.1 8B Instruct, temperature
  0.6, top_p 0.9, one reply). One run per arm: 560 answers.

## Grading

- **By hand, blind:** each question's 4 answers under letters A–D in a seeded order, under the rules of
  `bench-cross/jev-pick/GRADING.md` and `scaling/GRADING.md` (1–12).
- **Sealed before unsealing:** the grades are hashed (`graded.sha256`) before the arms are unsealed.

## Test

- **Primary, beyond the window:** per question, d = right(factpages-L40) − right(pages-L40). Exact two-sided
  sign-flip test, α = 0.05, with a 95% interval.
- **Secondary, reported but not deciding:**
  - facts-L40 (all) against factpages-L40 and against pages-L40;
  - the trend facts-L10 → L20 → L40 (L10 graded earlier, so not blind with these);
  - how often the question's own paper got any page picked, and the right answers when it did and when it did not;
  - totals by category; prompt tokens.

## Limits known in advance

- **One run per arm.**
- **Unasked papers:** the added papers are asked nothing, so this measures distraction, not cross-paper answering.
- **Mixed-in papers:** arXiv preprints are laid out differently from the corpus's journal PDFs, and some are about
  anodes or models rather than cathodes.
