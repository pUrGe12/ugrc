# Baseline: the whole PDF in Claude's prompt, no ugrc

**Question.** Is ugrc better than simply giving the model the whole PDF(s)? Same 71 questions as the ugrc
runs: the 60 probes on papers 2 and 3 (`experiments/claude-capability`) and the professor's 11 questions
over his 10 papers (`experiments/prof-rag`). Same model and effort (`claude-opus-5-5`, effort high). Each
PDF sent whole through the Files API as a cached document block; plain instruction: answer only from the
papers, give the page, say when they do not answer. One call per question, no tools. `run.py`, `compare.py`.

## Results

| | paper 2 (31) | paper 3 (29) | 10 papers (11) |
|---|---|---|---|
| **whole-PDF: correct** | **31/31** | **29/29** | **11/11** |
| ugrc: correct | 31/31 | 27/29 + 2 partial (format) | 11/11 |
| whole-PDF prompt per question | 34,104 tokens | 74,856 | **405,820** |
| ugrc prompt at its largest (≈, median) | ~5.9k | ~10k | ~21k |
| ugrc tokens read per question, all turns (median) | 18.4k | 33.9k | 96.1k |
| whole-PDF cost (cache on) | **$0.69** | **$1.09** | $3.15 ($2.05 of it the first question's cache write) |
| ugrc cost | $1.74 | $3.15 | $2.03 |
| whole-PDF seconds per answer (median) | 8.4 | 12.9 | 17.6 |

Grading by the assistant against each probe's expected answer and trap, written before any run (the
professor's three counting questions against references he has not yet confirmed); `grades.json`.
Every false premise, absence, binding trap and table count was handled. Numbers in the whole-PDF answers
that are printed nowhere in the papers: 9, in 5 answers, all labelled calculations or unit conversions
(sums, differences, 15,630 mg/L as 15.63 g/L, an estimate marked "my own estimate"). No invented value
was found.

## What this says

- **With a strong model, ugrc is not more accurate than the whole PDF.** On these questions the whole-PDF
  answers were as good, and on paper 3 slightly better (ugrc's two partials were formatting slips). The
  whole-PDF answers even caught a text/table disagreement the expected answer missed (p3-B1).
- **ugrc's prompt is far smaller** (5–20× at its largest), but with Claude that did not make it cheaper:
  a cached PDF is re-read at $0.20/M tokens, and one call costs less than ugrc's several turns. ugrc was
  cheaper only on the 10-paper set, and only because of the one 406k-token cache write; once warm, a
  whole-corpus question costs about $0.11 against ugrc's $0.18.
- **Where the size difference does matter:** the 10 papers fill 41% of Opus's 1M window, so about 25
  papers is the limit of the whole-PDF approach on any model; a small open model at a 32k window cannot
  take even paper 2 (34k) as a PDF. ugrc's largest prompt here was ~21–30k.
- **What ugrc guarantees that the baseline does not:** every number is a pointer a machine re-checks with
  no model (the receipt). The whole-PDF answers cite pages, but nothing checks them; here they happened to
  be right.

## Page citations of the whole-PDF answers (`cite_check.py`)

Every number on an answer line that names a page, looked up on that page: Opus 290 of 312 found there,
Haiku 185 of 191. Of the 28 flagged, read by hand, one is a real wrong page (Haiku p3-C4 cites page 8 for
a sentence on page 7); the rest are computed values or lines that name a figure page and a text page.

## A weaker model: Claude Haiku 5.5, both arms

Same 71 questions, same setup, `claude-haiku-5-5`, effort high (`answers-haiku/` in all three
experiments; `grades-haiku.json`).

| | correct | partial | wrong | cost |
|---|---|---|---|---|
| whole-PDF, Haiku | **67** | 2 | **2** | $0.57 |
| ugrc, Haiku | 58 | 13 | **0** | $0.26 |
| whole-PDF, Opus | 71 | 0 | 0 | $4.93 |
| ugrc, Opus | 69 | 2 | 0 | $6.92 |

- **Whole-PDF Haiku's errors are reasoning errors:** it called the two limonene/nerolidol pairs a
  conflict and said a cited sentence had no citation (p3-X2, the trap), and it missed the 23-row
  comparison table on the 10-paper set (prof-T1). Nothing in that setup catches either.
- **ugrc Haiku was never wrong, but 10 of its 13 partials are format:** the number sits only in a hidden
  support citation, so the reader sees "the UV–vis LOD was OD600 = [3]". The facts are right and
  checked, but they don't show. That is fixable in the machine (render a supported number as a quote, or
  refuse a text run that ends where its number should be). The other 3 are content: a wrong "next lowest"
  (p3-T2), a weaker study attribution (p3-X2), and "not covered" for the lithium-free cathodes while
  naming both sodium cells (prof-G4).
- Haiku needed more help at the door: 88 refusals over 71 answers (Opus 42), median 6 tool calls and 5
  turns (Opus 5 and 4), at most 13 turns. No answer ran out of turns.
- Haiku is not the open-model case: it has a 1M window and reads long PDFs well. A small open model with
  a 32k window cannot run the whole-PDF arm at all, so the real comparison there is ugrc against
  chunked retrieval (the professor's RAG).

## Caveats

- 71 questions, graded by the assistant, not blind. The 60 probes were written to trap ugrc's failure
  modes, not the whole-PDF approach's.
- Small numbers: 2 wrong vs 0 wrong is suggestive, not significant.

## Files

`run.py`, `compare.py`, `cite_check.py`, `answers/` and `answers-haiku/` (71 each), `grades.json`,
`grades-haiku.json`, `run.log`, `run-haiku.log`. `files.json` holds the uploaded file
ids (they expire after two days).
