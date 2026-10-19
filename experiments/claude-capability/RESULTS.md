# What the answers owe to Claude's capability

**Question.** The answering LLM (Claude Opus 5.5 today) will be replaced by a weaker open model. Which of
today's correct answers rest on Claude being a strong reasoning model, and what part of that work could
the cheap judge (Jev) or plain code take over?

**Run.** The 60 existing probes, written with expected answers and traps before any run: 31 independent
probes on paper 2 (`experiments/hallucination-paper2/probes.json`), 29 on paper 3
(`experiments/paper3/probes.json`). Each in a fresh conversation, `claude-opus-5-5`, effort high, door v3.
Every answer now carries a `trace` (each SQL query, figure view and refused submission).

## Results

- **58 / 60 correct, 2 partial, 0 wrong.** Paper 2: 31/31. Paper 3: 27/29.
- Every false premise rejected (11/11), every absence right (7/7), the planted wrong figure reading
  (berberine) never used, figure estimates labelled as estimates.
- Receipt GREEN for all 60 (every pointer re-resolves, zero model).
- **$4.89** in all, $0.08 per answer, 4.9 tool calls on average.

The two partials are **format** errors, not wrong facts:
- p3-T4: the longest run's product and strain went into hidden `support` citations instead of `quote`
  runs, so the text reads "the [5] run with strain [6]".
- p3-X1: a computed share rendered "1,620.5%" (percent format applied to a number already in percent).

## What each answer needed (`mark.py`, `MARKS.md`)

Marks are read off the record, not judged: the SQL written, values computed, pages and atom kinds cited,
refusals recovered, figures viewed, the probe's category, and claims in prose no pointer checks.

| what the model had to do | answers | what could do it instead |
|---|---|---|
| recover from a refusal by reading the feedback (26 of them: it typed a number in its own words) | 30 | the machine builds quotes and citations itself |
| make claims in its own words that no pointer checks | 29 | Jev yes/no: does the cited atom support this sentence? |
| resolve a trap (binding, false premise, cross-source) | 28 | Jev yes/no on each claimed binding and premise |
| write non-trivial SQL (regex 19, aggregates 9, joins 8) | 27 | code retrieves candidates with fixed queries; Jev picks |
| combine several places (pages, or text with tables/figures) | 23 | Jev selects atoms per sub-question; code assembles |
| run a long search (≥7 tool calls or ≥6 turns) | 14 | retrieval by code |
| read a figure | 12 | the stored figure readings are atoms Jev can select |
| compute a value in SQL | 12 | fixed query templates over the clause base |
| decide "the paper does not say" | 6 | Jev asks of the retrieved candidates whether any says it |

| capability level | answers | correct |
|---|---|---|
| high (≥4 marks, or ≥2 of compute / trap / synthesis / prose) | 36 | 34 |
| medium (2–3 marks) | 10 | 10 |
| low (0–1 marks: a direct lookup) | 14 | 14 |

**Reading.** The 44 correct medium/high answers are the ones whose correctness may be owed to Claude's
capability; the 14 low ones are plain lookups a weaker model should manage. The single most common
burden is not reasoning but the answer **format**: half the answers were refused at least once before
being accepted, and both partials are format slips. A weaker model will hit that wall first, which is
the strongest argument for having the machine, not the model, assemble the quotes and citations.

## Files

`run.py` (re-runnable; skips answered probes), `answers/` (60 records with traces), `grades.json` (hand
grades with notes), `mark.py` → `marks.json`, `MARKS.md` (one row per answer).
