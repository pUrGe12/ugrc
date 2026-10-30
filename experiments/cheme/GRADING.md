# Grading rules for the ChemE test

Every answer graded blind to arm (`grade.py sheet`: a question's 9 answers under shuffled letters), by one grader
(Claude), before `unseal`. The verdicts and rules are those of `bench-llama/HANDOFF.md`,
`bench-cross/jev-pick/GRADING.md` (1-8), `scaling/GRADING.md` (9-12) and `new6/GRADING.md` (13-18). Settled while
grading this test, before unsealing:

19. **A numbered table heading the model puts over its own tabulation** ("=== table 1 ===") in a paper that prints no
    such table is a label (rule 3, `[label]`), as "under a 'Table 3' heading" was in new6. An unnumbered one ("table
    from page 1", "Table of causes") is not.
20. **distillation's two recoveries are printed both ways.** The abstract gives 98.5% hydroquinone and 97.8% catechol
    recovery; sec. 5.7 gives 98.5% catechol and 97.8% hydroquinone. Either attribution is right. Sec. 5.7 states the
    optimum as 10 kPa, reflux ratio 3.143 and feed tray 11 (the abstract adds 16 plates and D/F 0.092): an answer
    giving sec. 5.7's set is complete.
21. **Arithmetic shown false** (915.0 x 0.232 = 211.88) is false even beside a right result, as rule 16; a final value
    within 0.5% of the key, reached by arithmetic that is right, counts as right.
22. **On a computation question, "the document does not state X"** is literally true when X has to be computed: a
    non-answer (rule 4), partial. Saying the inputs are not there when they are ("does not compare simulated and
    measured NO") is wrong.
23. **Denying a table the paper prints** ("the document does not have a Table 3") is a false statement about the
    paper: wrong `[label]`, even beside right values, as a wrong table number is (rule 3). A remark on what the model
    was given ("Table 6 is not provided", "not in the given snippet") is about its input, not the paper: `[render]`,
    and the answer is graded on the rest.
