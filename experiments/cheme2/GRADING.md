# Grading rules for cheme2

Every answer graded blind to arm (`grade.py sheet`: a question's 9 answers, 3 runs each of prose, facts and pdf, under
shuffled letters), by one grader (Claude), before `unseal`. Rules: `../cheme/GRADING.md` (1-23, with those it points to)
and `../prose/GRADING.md` (24-25). Any rule settled while grading this test is added below before unsealing.

Rule 25 was applied to every computation here as in `../prose`: a shown result that is not the right rounding of its
own inputs ("20.4 / 2.96 = 6.88", it is 6.892; "(139 / 169) x 100 = 82.5%") is wrong, even within 0.5% of the key.
Graded so for every letter; notes say "(rule 25)" so they can be recounted.

26. **On a false-premise question, saying the paper does not mention the subject at all** when the paper's mention of
    it is the contrary fact is false: wrong. fermentation-F1 asks why butyric acid was higher in poor silages; the
    paper says butyric acid was not detected in any sample. "The document does not mention butyric acid" is wrong;
    "does not state that butyric acid was higher" is a bare rejection (rule 9). Where the paper names the subject only
    in passing, unrelated to the question (solvent-extraction-A1: "extremely low permeability" of shale matrices in
    general), "permeability is not mentioned" stays correct.
27. **On a chained question, "the document does not explicitly state X" where X is the chained quantity** ("the CH4
    from the resin that decomposed most easily") is literally true, as rule 22 has it for a computed X; with the right
    answer after it and nothing false, correct. Saying a link of the chain is not stated when it is printed ("does not
    directly state polyurethane's CH4 at 500 °C") stays a false hedge (rule 10).
28. **process-simulation pairs 10 MJ/kg two ways.** The abstract has energy demand falling "from 26 to 10 MJ/kg as
    feed concentration increased" over a 1-4.3 wt % range; sec. 3 gives "approximately 10 MJ/kg" at "higher
    concentrations near the lower explosive limit (3.4 wt %)". For B1 (the demand at the highest concentration
    studied), 10 MJ/kg with either concentration follows the paper (rule 24): correct.
29. **A wrong unit beside a right value is false: wrong** (co2-capture-T1 k3r "1.00 × 10^7 s^-1" for L mol^-1 s^-1;
    wastewater-T2 Kid "1.07 min^-1"). The unit the paper's text prints is right (rule 24), even where its typesetting
    may have lost a superscript (wastewater-T2 "mg·g−1·min−1").
