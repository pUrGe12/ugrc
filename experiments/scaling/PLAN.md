# The scaling test: frozen plan

Written 2026-10-22 and frozen by hash (`frozen.sha256`, with `questions.json` and `libraries.json`) before any answer
of this test existed. `run.py answer` refuses to run if any of the three changes.

## The question

Asked by the user: is there a point, as the material grows, where a clause base does better than putting more and
more PDF text into the prompt? What was known before this test:

- **PDF text degrades with length:** one paper alone, 107 of 154; buried among other bench papers, about 92 at 32k
  and 64k tokens, 78 at 118k. Past about 8 papers it does not fit Llama's 131k-token window.
- **The whole clause base is not a compression:** 117k tokens for the 10 corpus papers, against 155k of PDF text.
  Jev's readings in the prompt did not help (117 vs 122 of 154).
- **A condensed clause base is a compression:** the sentences that state a value, with the tables and figure facts,
  come to 32k tokens for the 10 papers (155k of PDF text). The values with Jev's readings and no sentences come to
  20k. Token counts are the model's own (`libraries.json`).

This test measures how PDF text and the condensed forms hold up as the library grows from 1 to 3 to 10 papers.

## Forms of a paper

- **text:** its `pdftotext`, exactly as `bench-llama/direct.py` gives it.
- **facts:** page by page, the clause-base sentences that print at least one value Jev did not read as an identifier.
  Left out: a sentence with no value, and one whose values are all identifiers (a reference, a journal line). Then its
  tables row by row (caption and column headers first) and its figure facts, as the hybrid renders them. The system
  prompt says other sentences are left out.
- **readings:** page by page, each of those values with Jev's reading (role; property; what it is of; by what method;
  what it measures) and no sentence, then the same tables and figure facts. The system prompt says the readings can
  be wrong and that the sentences are left out.

## Libraries

- **Order:** for each corpus paper, the other 9 are shuffled by the seed `scaling:<paper>` (`libraries.json`,
  `order`).
- **Sizes:**
  - **1 paper:** the paper alone.
  - **3 papers:** the paper and the first 2 of its order.
  - **10 papers:** all 10. All 10 papers' text does not fit, so text at this level holds the paper and, in order, every
    other paper that still fits in 120,000 tokens of documents (the budget of `llama-direct-ctx120k`). That is 7 to 9
    papers, 112k to 120k tokens. Text keeps the one paper the question is about, which favours text.
- **Placement:** the target paper's place among the documents is drawn by a seed. At 1 and 3 papers, text and facts
  get the same documents in the same order.
- **Prompt:**
  - Each document is wrapped in `<document title="...">`.
  - The system prompt names the target's title, says what form the documents are in, and asks for a brief answer
    that shows any calculation, says when the question assumes something the document contradicts, and says when the
    document does not hold the answer.
  - The question comes last and names the title.
  - Only the form sentence and the documents differ between arms.
- **Recorded:** every document list, slot and token count is in `libraries.json`, and every answer record carries
  its own.

## Arms

| arm | form | library |
|---|---|---|
| `llama-scale-text-L1` | text | 1 paper |
| `llama-scale-text-L3` | text | 3 papers |
| `llama-scale-text-L10` | text | the paper + as many of the other 9 as fit in 120k tokens |
| `llama-scale-facts-L1` | facts | 1 paper |
| `llama-scale-facts-L3` | facts | 3 papers |
| `llama-scale-facts-L10` | facts | 10 papers |
| `llama-scale-readings-L10` | readings | 10 papers |

The model and sampling are the same as for every Llama arm: Llama 3.1 8B Instruct, bf16 on vLLM (Modal), temperature
0.6, top_p 0.9, at most 4,096 output tokens. One reply; no tools, no SQL, no door, no pointers. One run per arm: 980
answers, about $2.

## Questions

`questions.json` holds the 140 single-paper questions (bench-leads, bench-multistep) on the 10 corpus papers.
cai2026's 14 are left out, since it is not in the corpus.

## Expectations, written before the run

- **Text** loses accuracy as the library grows, as it did from 107 to 78 before.
- **Facts start below text at one paper.** They drop the sentences without values, which several false-premise and
  qualitative questions need. Of the 116 questions whose keys cite lines, 14 have no cited line in the facts form and
  11 have only some; 8 of the 14 are false-premise questions.
- **Facts lose less than text** from 1 to 10 papers.
- **Readings alone do worse than facts** at 10 papers.

## Grading

- Every answer is graded by hand, blind to arm, under `bench-cross/jev-pick/GRADING.md`'s rules. `grade.py sheet`
  shows each question's 7 answers under letters A–G in a seeded order.
- A "the document does not say" about something the paper says is wrong, whichever form hid it.
- The grades are hashed (`graded.sha256`) before the arms are unsealed. Answers that give away their form ("the
  condensed text…") are counted.

## Test

- **Primary:** at 10 papers, per question d = right(facts-L10) − right(text-L10), one of −1, 0 or 1. Exact two-sided
  sign-flip test, α = 0.05.
  - If p < 0.05 and the sum of d is positive, the condensed clause base beats PDF text at 10 papers.
  - If p < 0.05 and the sum is negative, PDF text beats it.
  - Otherwise there is no decision.
- **Secondary, reported but not deciding:**
  1. **Loss with library size:** per question, s = [right(facts-L1) − right(facts-L10)] − [right(text-L1) −
     right(text-L10)], with an exact sign-flip test; likewise from 1 to 3 papers.
  2. **The cost of condensing, at one paper:** facts-L1 against text-L1.
  3. **readings-L10 against facts-L10.**
  4. **Totals:** right, partial and wrong per arm and by category; numbers printed nowhere in the paper; how many
     papers text-L10 held; prompt tokens.
  5. **Reference only** (graded earlier, other runs, not blind together with these):
     - `llama-hybrid-corpus-bm25` r1–r3 (BM25-picked pages, at most 24k tokens, from the same 10 papers) on the 114 of
       these questions it ran;
     - `llama-direct-r1` and `llama-clauses-text-r1` (the paper alone) on all 140.
- **The tipping point** is read off the right counts per library size, where the facts line meets the text line. No
  model is fitted to three points.

## Limits known in advance

- **One run per arm:** single-run totals move by several answers.
- **Too few papers for the far end:** only these 10 papers have both a clause base and questions in one corpus. The
  range where only a condensed form fits (30 or more papers) is extrapolated, not measured.
- **Text-L10 gets the benefit of the doubt:** it always keeps the paper the question is about. A system holding more
  papers than fit could not know which to keep; it would have to retrieve, as the hybrid does.
- **Blinding can leak:** the form may show in an answer. Such leaks are counted.
