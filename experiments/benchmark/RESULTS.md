# The benchmark: results

Run 2026-11-01 under the frozen plan (`PLAN.md`; every hash in `frozen.sha256` still matches). Llama 3.1 8B answered
in every arm, on our own vLLM server on Modal. Claude graded every answer blind to arm, mode and run (`grade.py`; rules
in `GRADING.md` and `GRADING-settled.md`). The grades were hashed in `graded.sha256` before unsealing. Jev was not
used: it has no credits. The full printout is `report.txt`.

## Part 1: one question at a time over 130 papers (160 questions, one run)

| arm | what Llama gets | right | partial | wrong | right, rounding slips and table labels forgiven | prompt tokens (mean) |
|---|---|---|---|---|---|---|
| **ours** | search picks the paper; that paper's facts+prose | **119** | 1 | 40 | **126** | 6,335 |
| pdf | the right paper handed over, whole text | 101 | 3 | 56 | 106 | 18,879 |
| chunks | ours' paper choice, then that paper's best 200-word chunks | 96 | 4 | 60 | 99 | 5,447 |
| rag | the best 200-word chunks from all 130 papers | 84 | 11 | 65 | 86 | 6,481 |

**Paired tests on right / not right (exact sign-flip):**
- ours − pdf: +18 (28 better, 10 worse), p = 0.005
- ours − chunks: +23, p = 0.0001
- ours − rag: +35, p < 0.0001
- chunks − rag: +12, p = 0.04

With the strict rounding and table-label rules relaxed, ours still leads: +20 over pdf (p = 0.002), +27 over chunks
and +40 over rag.

**By source (right):** on the fresh test's 80, ours 61, pdf 49, chunks 46, rag 45. On 80 drawn from the
big-library test, ours 58, pdf 52, chunks 50, rag 39.

**By question type (right: ours / pdf / chunks / rag):**

| absence | lookup | binding trap | false premise | chained | table | computation |
|---|---|---|---|---|---|---|
| 19 / 20 / 18 / 16 of 20 | 24 / 23 / 24 / 21 of 25 | 18 / 18 / 18 / 16 of 21 | 18 / 17 / 17 / 13 of 21 | 11 / 9 / 8 / 6 of 17 | **22 / 9 / 5 / 7 of 37** | 7 / 5 / 6 / 5 of 19 |

### What part 1 shows

- **The lead comes from tables.** On the 37 table questions, ours got 22 right; no other arm got more than 9. On the
  other 123 questions: ours 97, pdf 92, chunks 91, rag 77. The clause base writes each table row out as a sentence.
  pdftotext and 200-word chunks run a table's cells together, and Llama then reads the wrong row or column.
- **RAG does not fail at finding the paper.** Every rag prompt held chunks of the right paper (88% of its chunks, on
  average), and only one rag answer took its values from another paper. It fails at finding the right passage.
  Limiting the same retrieval to the right paper (chunks) gains 12 questions; the clause base gains 23 more.
- **Search picked the right paper for 159 of 160 questions.** On the one miss (aenm-2022/X1, sent to adma-2020),
  every arm was wrong.
- **The instructions do not explain the PDF gap.** This test gave the PDF arm ours' instructions; earlier tests gave
  it a shorter prompt. On the same 80 fresh questions it scored 49, against 50 before.
- **Ours scored 61 of 80 on the fresh questions,** the same as the door test's regrading of that setup (61). The
  result holds from one test to the next.
- **The commonest error type is the false hedge:** "not explicitly stated", then a value. It made 8 of ours' wrong
  answers, 9 of rag's, and 12 each of chunks' and pdf's.

## Part 2: a 16-question conversation on one paper (3 runs)

The paper is `cheme3/adsorption-2`. Its 16 questions are in `conversation.json`.
- **chat:** the 16 questions asked in order in one conversation.
- **solo:** each question spelled out and asked alone.

| arm | solo, right of 16 (runs) | chat, right of 16 (runs) | chat − solo (48 pairs) | context at the last turn | prompt tokens for all 16: chat / solo |
|---|---|---|---|---|---|
| ours | **14.3** (14, 14, 15) | 12.3 (11, 12, 14) | −6, p = 0.18 | 16.6k | 216k / 147k |
| pdf | 12.3 (11, 14, 12) | **13.0** (13, 14, 12) | +2, p = 0.77 | 24.6k | 377k / 361k |
| chunks | 12.3 (13, 12, 12) | 10.3 (10, 12, 9) | −6, p = 0.18 | 16.7k | 207k / 84k |
| rag | 11.0 (11, 11, 11) | 8.3 (9, 8, 8) | −8, p = 0.08 | 33.3k | 336k / 100k |

Over all four arms, chat − solo is −18 of 192 (p = 0.02). Ours − pdf is +6 of 48 alone (p = 0.21) and −2 of 48 in
the conversation (p = 0.77). One paper is too few to separate those two.

### What part 2 shows

- **The conversation hurts every arm that retrieves, but not the whole PDF.** Three causes showed up in the answers:
  - **Vague follow-ups retrieve the wrong text.**
    - "At what temperature ... was the autoclave held during that synthesis?" sent rag to another paper's
      carbon-dot synthesis (180 °C for 12 h) in all 3 runs.
    - "How much activated biochar went into that composition" got the 10 and 20 wt% loadings instead of the masses,
      in all 6 rag and chunks conversations.
  - **Facts far back get missed.** Ours sends the paper's facts once, on turn 1; later turns add only new prose
    sentences. By turns 12 and 15, the isotherm fits (Table 5) and the comparison table (Table 6) sat about 14k
    tokens back. Llama then said "not given" or "not discussed": turn 12 right 1 of 3 in chat against 3 of 3 alone,
    turn 15 1 of 3 against 3 of 3.
  - **False premises get through.** Turn 6 claims the pristine framework adsorbed more CO2 than the best composition.
    In chat, ours, rag and chunks went 0 of 9: they restated the premise or explained it. Alone they went 9 of 9.
    The PDF arm went 3 of 3 in chat and 1 of 3 alone.
- **No error carried over.** Every arm got turn 1 right in every run, so "the best composition" always meant the
  right sample. No answer built on an earlier wrong answer of its own. The counts of "right after a right turn"
  against "right after a wrong turn" follow which questions are hard, not carry-over.
- **The context never ran out.** The largest was 33k tokens (rag), against Llama's 131k window. No turn was refused.
- **Later turns are harder in both modes.** In solo too, turns 9-16 score lower than turns 1-8: they hold the
  computations, the comparison table and the second false premise. Splitting the conversation in half does not
  isolate the effect of length.
- **Hardest question for all:** the comparison table's best adsorbent and its model (turn 15). Only ours got it
  (3 of 3 alone, 1 of 3 in chat); every other arm got 0 of 6.

## What this means

- **One question at a time, ours is the best of the four** on a 130-paper library. It is 18 ahead of the whole right
  paper handed over, and 35 ahead of standard RAG, at a third of the PDF's tokens.
- **In a conversation, ours needs two fixes** before it keeps that lead. Neither needs Jev:
  1. Each turn, re-send the facts rows that match the new question, not only those sent on turn 1.
  2. Retrieve on a stand-alone rewrite of the follow-up ("that synthesis" → "the MIL-100/110 hybrids' solvothermal
     synthesis"), not on the raw turn.

  A rerun of part 2 with both fixes, plus a second paper, would test them.

## Caveats

- **Grading:** one grader, Claude. Claude also wrote the questions and keys.
- **Runs:** part 1 is one run.
- **Part 2's size:** one paper and 16 questions.
- **Strict rules:** a wrong rounding and a "not stated, however X" hedge both count as wrong. Restating a false
  premise before correcting it also counts as wrong.
- **Changes during the run:** the part 1 client was restarted twice when the server's replies did not reach it
  (`answer.log`). Answers already saved were kept, and nothing frozen changed.

## Files

- **Frozen setup:** `PLAN.md`, `GRADING.md`, `run.py`, `run.sh`, `embed.py`, `embed_modal.py` (the dense scores on a
  Modal GPU), `grade.py`
- **Questions:** `questions.json`, `conversation.json`
- **Retrieval data:** `chunks.jsonl`, `queries.json`, `routes.json`, `dense.json.gz`, `retrieval.json`
- **Answers:** `answers/{bench,solo,chat}/`
- **Grades:** `grades-bench.json`, `grades-conv.json`, `GRADING-settled.md`, `graded.sha256`, `hand.json`
- **Report:** `report.txt`
