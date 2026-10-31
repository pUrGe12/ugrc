# Grading the library test

Rules 1-23 (`../cheme/GRADING.md`), 24-25 (`../prose/GRADING.md`) and 26-29 (`../cheme2/GRADING.md`) apply as written,
with "the paper" read as the question's paper. Rule 25 stays strict: a shown result that is not the correct rounding
of its own inputs is wrong. Written before any answer of this test existed. The sheet shows the question's paper (its
title) with the question, the expected answer and the trap; it does not show which arm wrote an answer.

- **L1. Wrong paper.** An answer whose values or claims come from a library paper other than the question's is wrong,
  tag `[paper]`, even when it names the right paper.
- **L2. Wrong name, right values.** An answer that gives the question paper's values but names another document as
  their source is graded on the values; tag `[name]` (not itself a wrong).
- **L3. Not found.** "No document holds this" when the question's paper holds the answer is wrong, tag `[miss]`. (Whether
  that paper was in the prompt is recorded by the runner and counted separately; the verdict does not depend on it.)
- **L4. Absence.** On an A question, saying the library does not give the quantity is correct. Giving a value from
  another paper as the answer is wrong `[paper]`; an invented value is wrong.
- **L5. False premise.** Correcting the premise with the question paper's contrary fact is correct. "No document
  mentions this", when the question's paper states the contrary fact, is wrong (rule 26).
