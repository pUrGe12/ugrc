# The library test: frozen plan

Written 2026-10-31 and frozen by hash (`frozen.sha256`: this plan, `GRADING.md`, `reworded.json`, `questions.json`,
`libraries.json`, `run.py`) before any answer of this test existed. `run.py answer` refuses to run if any of them
changes.

## The question

Asked by the user: every test so far handed the model the one paper a question is about. "If we know which pdf has the
answer then why even bother." Here the model gets a library of 10 papers, the question does not say which paper it is
about, and it has to find the right one. Which way of giving it the library does best: the clause base (facts form),
the clause base with prose sentences, or pages of the PDFs?

What was known before this test:

- **One paper, held out** (`cheme2`, 152 questions, 3 runs): facts+prose 340 of 456, facts 288, pasted PDF 273.
- **Libraries, earlier corpus** (`scaling`, `scaling-more`, the question naming its paper's title): at 10 papers the
  facts form beat as much PDF text as fits (95 vs 74 of 140); at 40 papers BM25-picked pages (24k tokens) beat the
  facts form of the 29-33 papers that fit (103 vs 67). Prompt length drives the 8B model.
- **Ten whole PDFs do not fit:** the 10-paper libraries below come to 176k-194k tokens of pdftotext, against Llama 3.1
  8B's 131k window. The user chose BM25-picked PDF pages as the PDF arm.

## Papers and libraries

- **The 28 chemical-engineering papers** with frozen questions: the 9 of `cheme` and the 19 of `cheme2`. Ids are
  `cheme/<topic>` and `cheme2/<topic>`; nine topics occur in both sets with different papers.
- **Drawn by a seed** (`run.py build`, `libraries.json`): the 28 ids, sorted, shuffled by `library:draw`. L1 is the
  first 10, L2 the next 10, L3 the last 8 plus 2 papers drawn from L1 and L2 by `library:L3-extra` (no L3 question is
  about those 2). Each question is asked once, in the library of its paper.
- **Prompt order:** each library's papers in an order drawn by `library:<name>:order`, the same for every question and
  arm of that library.
- **Measured** (characters / 3.6): facts form of a library 54k / 57k / 64k tokens; its pdftotext 182k / 194k / 176k.

## Questions

- **The 246 frozen questions** of the 28 papers (`cheme` 94, `cheme2` 152), same categories: C lookup, B binding trap,
  T table, X computation, H chained lookup, F false premise, A absence.
- **Reworded for a library** (`reworded.json`), from each original question, its expected answer and the paper's
  pdftotext only, before any answer of this test existed:
  - table, figure and section numbers removed ("According to Table 2, ..." becomes a question about the quantity);
  - "the paper", "the study", "this work", "the review" replaced by a subject phrase;
  - a subject phrase (material, process, system) added where the question would otherwise fit more than one of the 28
    papers. 47 questions needed no change.
- **The answer keys are the originals,** unchanged (`questions.json` holds both wordings).
- **What this makes easy:** the questions carry the subject words a user would type, so keyword search finds the right
  paper. Measured before any answer: BM25's 24k tokens of pages include the question's paper for all 246 questions
  (about 13 of the roughly 20 pages picked are from it); its 30 sentences include about 24 from it.

## Arms

Every arm holds the same 10-paper library and the same question. Only what goes in the prompt differs.

| arm | what the prompt holds | tokens |
|---|---|---|
| `facts` | every library paper in the facts form (the clause base condensed, as in `cheme` and `cheme2`) | 54k-64k |
| `prose` | the same documents, then the number-free clause-base sentences of the 10 papers that best match the question | 56k-66k |
| `pages` | pdftotext pages of the 10 papers picked by BM25 on the question, up to 24,000 tokens | 24k |

- **facts:** `<document title="...">` per paper, in library order, then the question.
- **prose:** the facts arm's documents, then a `<sentences>` block. The sentences are the facts form's left-out
  sentences (no value Jev did not read as an identifier), pooled over the 10 papers, ranked by BM25 on the question,
  best first until 30 sentences or 5,000 characters (the prose test's limits), shown by paper in page order. Unlike the
  one-paper prose arm, the sentences come after the documents instead of among them: then every question on a library
  shares the documents' prefill, which keeps this arm about ten times cheaper.
- **pages:** every pdftotext page of the 10 papers (split at form feeds), headed `=== <title>, page N ===`; the
  hybrid's BM25 on the question; best first while the total stays under 24,000 tokens (characters / 3.6); shown in
  library order, then page order. This is `scaling-more`'s winning arm on pdftotext pages instead of the hybrid's
  rendering, and the question alone as the query (it no longer names the title).
- **System prompt** (all arms): a library of 10 documents; the arm's one-sentence description of the form; the
  question does not say which document it is about, so find it and name it; answer briefly, show any calculation, say
  when the question assumes something the documents contradict, say when no document holds the answer.
- **Model and sampling:** as every Llama arm: Llama 3.1 8B Instruct, bf16 on vLLM (Modal, L40S), temperature 0.6,
  top_p 0.9, at most 4,096 output tokens, one reply, no tools.
- **One run per arm:** 246 x 3 = 738 answers. More questions buy more than more runs of the same ones.
- **Spend:** about $3.24 of the month's Modal credit is left on 2026-10-31. L1 runs now; L2 and L3 run after the
  credit renews (2026-11-01 UTC). The order of running changes no prompt.

## Grading

- **Blind:** each question's 3 answers under letters A-C in an order drawn by `library:<key>`; which arm a letter is
  stays in code until `grade.py unseal`. Grades are hashed (`graded.sha256`) before unsealing.
- **Rules:** `../cheme/GRADING.md` (1-23), `../prose/GRADING.md` (24-25), `../cheme2/GRADING.md` (26-29), and the
  library rules L1-L5 in `GRADING.md` here (an answer taken from the wrong paper is wrong, tag `[paper]`).
- **Recorded by the runner, not graded:** whether the question's paper was in the prompt (always, for facts and
  prose; for pages, whether any picked page is from it), how many picked pages or sentences are from it.

## What gets reported

- **Right of 246 per arm,** and the paired comparisons prose - pages, facts - pages, prose - facts: sum of
  per-question differences, better / worse counts, exact paired sign-flip p (`blind.exact_p`).
- **By library, by category, by set** (`cheme2` questions were not used to design the prose arm; `cheme` ones were).
- **Wrong-paper answers** (`[paper]`) per arm, and wrongs where the right paper was not in the prompt.
- **Reference, descriptive only:** the same questions with one paper in view (`cheme`, `prose`, `cheme2` grades,
  original wording), per run.
- **Expected,** from the earlier tests: prose at or above facts; pages strong, as the right paper's pages are nearly
  all in its prompt and its prompt is shorter. No outcome is excluded.
