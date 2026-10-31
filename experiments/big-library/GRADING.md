# Grading the big-library test

The library test's rules apply as written (`../library/GRADING.md`, which brings in rules 1-29 and adds L1-L5), and the
routed test's R1 (`../routed/GRADING.md`), with "the paper" read as the question's paper. The new6 and bench questions
are graded by the same rules; theirs were the first ones (`bench-llama/HANDOFF.md`, `new6/GRADING.md`). Written before
any answer of this test existed.

The sheet shows the question, its paper's title, the two papers the search ranked first (the same for every answer of a
question), the expected answer and the trap. It does not show which arm wrote an answer or which papers its prompt held.

- **B1. Two documents.** An answer that takes its values or claims from a paper other than the question's is wrong,
  tag `[paper]` (L1), whichever prompt it came from. One that gives the question paper's values but names another
  paper as their source is graded on the values, tag `[name]` (L2).
- **B2. Old line numbers.** The bench keys cite pages and lines of an older text extraction ("p3.L9-10"). A disputed
  value is checked against the paper's pdftotext (`text/bench/<paper>.txt`), not against those line numbers.
- **B3. Approximate keys.** Where the key gives a value as approximate ("~10.2 mg/cm^2", "≈192 mAh/g"), the value the
  paper prints counts as right with or without "about".
