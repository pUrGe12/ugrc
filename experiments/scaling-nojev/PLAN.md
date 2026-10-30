# Do we need Jev, or ugrc, for the condensed form? Frozen plan

Written 2026-10-22 and frozen by hash (`frozen.sha256`, with `forms.py` and `run.py`) before any answer of this test
existed. `run.py` refuses to run if any of them changes.

## The question

In the scaling test (`experiments/scaling/`), a condensed clause base answered 95 of 140 questions right at a
10-paper library, against 74 for the papers' PDF text. Two things built that form:

- **ugrc's code:** it cut the sentences, found the values, dropped the reference list and wrote tables row by row.
- **Jev:** one filter. A sentence was dropped when Jev (or a layout rule) read every value in it as a label, not a
  quantity. That dropped 249 of 729 value-bearing sentences, 189 of them on Jev's call.

Is either needed?

## Arms

All at the 10-paper library, with the same documents in the same order and the same target slot as
`llama-scale-facts-L10` (`experiments/scaling/libraries.json`). Prompt, model and sampling are as in the scaling test.
Only the form sentence in the system prompt and the documents differ.

| arm | form | judge | ugrc | about |
|---|---|---|---|---|
| `llama-scale-facts-L10` | the scaling test's facts form | Jev's label filter | yes | 32k tokens |
| `llama-scale-code-L10` | ugrc's sentences with any value, tables row by row, figure facts | none | yes | 43k tokens |
| `llama-scale-pdf-L10` | pdftotext sentences that hold a digit, reference list cut | none | no | 69k tokens |

The forms are in `forms.py`.
- **code:** exactly the facts form without Jev's filter.
- **pdf:** uses no ugrc at all. Tables come as pdftotext prints them, column by column.

`llama-scale-facts-L10`'s answers are not rerun. They are graded again, blind, beside the new arms, so all three are
graded in one pool. The earlier grades stay as they are, and agreement between the two gradings is reported.

## Grading

- **By hand, blind:** each question's 3 answers under letters in a seeded order, under the rules of
  `bench-cross/jev-pick/GRADING.md` and `scaling/GRADING.md` (9-12).
- **Sealed before unsealing:** the grades are hashed (`graded.sha256`) before the arms are unsealed.
- **Stored separately:** the regrades of `llama-scale-facts-L10` are not written into `hand.json`.

## Test

- **Primary, is Jev's filter needed:** per question d = right(facts) − right(code). Exact two-sided sign-flip test,
  α = 0.05, with a 95% interval for the difference in right answers.
  - The filter helps if p < 0.05 and the sum is positive; it hurts if p < 0.05 and the sum is negative.
- **Decision for the next step (more papers):** use the code form unless the filter helps, since the code form
  needs no judge and no clause base.
- **Secondary, reported but not deciding:**
  - code against pdf (does ugrc's reading matter?), and facts against pdf;
  - totals by category, table questions in particular;
  - prompt tokens;
  - the scaling test's PDF-text arm at 10 papers (74) as a reference.

## Limits known in advance

- **One run per arm.**
- **Unequal sizes:** the code form is a third larger than the facts form (43k against 32k tokens) and still fits easily at 10 papers. At 40 or
  more papers the difference in size would matter, and this test does not measure that.
