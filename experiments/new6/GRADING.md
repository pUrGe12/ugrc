# Grading rules for the new6 test

All 324 answers were graded blind to arm (`grade.py sheet`: a question's 6 answers under shuffled letters), on
2026-10-30, by one grader (Claude), before `unseal`. The verdicts and rules are those of `bench-llama/HANDOFF.md`,
`bench-cross/jev-pick/GRADING.md` (1-8) and `scaling/GRADING.md` (9-12). Settled while grading this test, before
unsealing:

13. **teak-pyrolysis-X1's wording is ambiguous.** "The bio-oil model's total sum of squares" can be read as the Model
    row (361.40, giving 88.7%) as well as the Cor Total the key uses (372.02, 86.2%). Both count as right.
14. **Half of a two-part table cell** (one of the two ploidy levels Table 1 gives 'Espadín') is partial.
15. **"The documents do not hold the answer" to a false-premise "why" question** neither accepts nor corrects the
    premise: partial, `[bare]`, as rule 9. "The document does not explain why X kept increasing" restates the false
    premise as fact: wrong (rule 5).
16. **An answer that first states a false value and then concludes right** is wrong (anything false), noted
    `[selfcorrect]` so it can be recounted.
17. **A garbled method sentence** around a computation that is shown in full and right is correct; the note says so.
18. **Page headers the model writes** ("=== page 2 ===" for a one-page paper) are page numbers: not checked (rule 8).
    Table labels are (rule 3, `[label]`).

Notes that carry a tag, so the result can be recomputed: `[label]` (7), `[hedge]` (2), `[bare]` (5), `[selfcorrect]`
(1), `[render]` (1).
