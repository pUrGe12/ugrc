# Grading rules for the jev-pick test

The verdicts and rules of `bench-llama/HANDOFF.md` (correct / partial / wrong; a computed value within 0.5% of the key
counts as right; anything false makes an answer wrong), applied blind to arm with `blind.py sheet`. Rules settled
while grading, so every answer is judged the same way:

1. **A bare right value** ("3.5 cm^-1") is correct when the question asks only for the value (as earlier grades did).
2. **Degenerate output** (hundreds of lines of a model counting) around a right answer, with nothing false, is
   correct; the note says so.
3. **A made-up source for an asked value** (a "Table 2", "Row 1 of Table 2c" or figure that does not exist or does not
   print it, given as where the paper states the value) is a false side claim: wrong. Such notes start with
   `[label]`, so the result can be recomputed with them counted as correct. A wrong label on something the question
   did not ask about (an aside naming "Table S7" for the paper's "Figure S7") is not counted.
4. **A non-answer** that talks around the question and says nothing false is partial.
5. **A false premise answered as posed** (computing the asked "how far behind" without saying the premise is false)
   is wrong, even when the numbers used are right.
6. **The paper's own figure replaced by the model's computation** (a loss of 8% computed where the paper states
   ~5%, when the question asks what the paper gives) is partial; a computation beside the paper's figure is fine.
7. **The question names its paper**, so a value or claim taken from another paper is wrong.
8. **Page numbers in an answer are not checked** (a PDF page and a printed page number differ, and a sentence can run
   over a page break); table and figure labels are, under rule 3.

Tables the corpus papers print (captions in the PDF text): adma-2020, cssc-2020 and ensm-2020 Table 1 only; ensm-2021
Tables 1-6; acsnano-7b02404, aenm-2022, mattod-2020, nanolett-6b05172, nanolett-6b05174 and susmat-2020 none.
