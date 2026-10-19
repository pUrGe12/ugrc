# Does it hallucinate under many probes and long tasks? — results on paper 2

**Question.** The design makes it impossible to invent a value or a quote. Does it still hallucinate when you
ask many questions, adversarial ones, or long synthesis tasks, or when the history accumulates?

**Setup.** Paper 2 (Liu et al., Chem. Eng. J. 549 (2026) 182243), `claude-opus-5-5` at effort high.

| arm | what | answers |
|---|---|---|
| independent | 31 probes, each in a fresh conversation | 31 |
| session | 15 of the probes asked one after another in ONE conversation (history kept) | 15 |
| long | 2 synthesis tasks with many entity/value pairings | 2 |

**The probes**, all in `probes.json`:

| kind | how many | example |
|---|---|---|
| controls | 8 | plain facts from the methods |
| binding | 6 | a value whose strain sits on a different line from it |
| false premise | 7 | an LOD the paper never reports; blind tests on mixtures that were never run; 120 μM chosen when the paper chose 165 |
| absence | 4 | cost per test, shelf life, comparison with PCR, cohort size |
| figure | 4 | two have a planted wrong reading: the vision model's "berberine" for BA, and its ~592 nm peak estimate |
| comparison | 2 | CD vs UV–vis LODs; fully vs partly discriminated strains |

**Grading.** The answer key, including the trap each probe invites, was written before any run. Every atomic
claim was then graded by hand against the paper, and figure claims against the figures themselves.

## Results

| error type | count |
|---|---|
| invented value or quote | **0** (structurally impossible; 48/48 answers re-resolve under the receipt) |
| wrong pairing (a real value attached to the wrong entity) | **0**, including the 35 strain/field pairings of L1 and the value-before-strain line layout of B2/B3 |
| accepted false premise | **0** of 12 (7 independent, 5 in the session) |
| wrong figure reading carried into an answer | **0**: "berberine" never appeared; G1 answered from the text, and G2 gave the text's 585/790 nm with the figure estimates labelled |
| false absence ("not in the paper" when it is) | **0** |
| narrow or mismatched absence search (claim true, but the search proves less than it seems) | **2** |
| wrong inference in prose | **1** (hedged) |
| imprecision caused by the door | **1** |

All 48 answers are correct on their facts. The four flaws:

1. **F6 (independent): a narrow search.** It claims "no detection limit for S. typhimurium in serum", backed by a
   search for "detection limit". The paper writes "limit of detection", so that search could never have found
   it. The claim is true, but the citation proves less than it seems.
2. **A2 (independent): a mismatched search.** The claim is that the monitoring duration isn't stated, backed by a
   search for "shelf/storage/long-term". The claim is true, but the search doesn't cover it.
3. **B4 (session): a wrong explanation for a real finding.** The answer found a genuine inconsistency: Fig. 4
   shows 1:1 binary mixtures that the text's ratio list ("1:0, 1:4, 1:8, and 0:1") omits. It then guessed,
   hedged, that "1:0" may be a typo for 1:1. That guess is wrong, because 1:0 and 0:1 are the pure strains,
   which the figure also shows; the text simply omits 1:1. The fresh-context run of the same question didn't
   notice the inconsistency at all.
4. **L2 (long): a dropped locant.** To get past the digit ban on "4-MPBA", the model wrote "mercaptophenylboronic
   acid" and dropped the "4-" locant, which names a specific isomer. The door's false positive on names that
   start with a digit pushed the model into this imprecision.

The door refused one or more submissions in 27 of the 48 answers, mostly for number words and for SQL values
with no FROM. Every refused answer recovered on resubmission.

**Cost:**

| arm | cost |
|---|---|
| independent | $1.70 |
| session | $0.81 |
| long | $0.38 |
| **total** | **$2.89** |

## What this says

- **What the structure guarantees held under every kind of pressure:** no invented value, no altered quote, no
  number that can't be traced.
- **What it doesn't guarantee also held this time, but only empirically:** zero wrong pairings, zero accepted
  false premises, zero propagated bad readings, across 48 answers. That reflects the model's behaviour plus the
  design (a model that can't type facts is pushed to look them up), not a proof.
- **The errors that did occur are the predicted kind:**
  - searches narrower than the claims they back;
  - a hedged inference in prose;
  - an imprecision the door itself induced.

  None is an invented fact, and every one is visible in the citation metadata.
- **The session arm (history kept) was not worse than fresh contexts.** It made the same zero pairing errors,
  and it found a real inconsistency in the paper that the fresh run missed. Its one error was the explanation
  of that inconsistency.

**Limits of this test:**
- one paper, one model, 48 answers;
- graded by one reader (me) against an answer key I wrote from the same reading;
- the planted bad reading was only one fact;
- sessions of 15 questions are not very long.

A stronger test would use several papers, a second grader, sessions of 50+ questions, and probes written by
someone who hasn't read the answers.

## Follow-up: door v3

Two of the four flaws were mechanical, so they were fixed in the door:

| flaw | fix in door v3 | effect |
|---|---|---|
| F6's narrow search ("detection limit") | an absence term whose words all occur together within two consecutive lines is refused (`absent:near`), pointing at the place: p6.L58 "…lower limit of detection" | F6 is now refused |
| L2's dropped "4-" | a refused digit-led token that the document writes the same way comes back as a ready quote run ("never shorten it"); a single-word or name quote resolves to its first occurrence | quoting "4-MPBA" costs nothing |

**Re-checked under door v3:** 47/48 answers are identical, and F6 is refused.

**Not fixable mechanically, and still open:**
- A2's search terms not covering its claim (a semantic mismatch);
- B4's wrong inference in prose.

## Files

| file | contents |
|---|---|
| `probes.json` | probes, answer key and traps (written before running) |
| `run.py` | the runner |
| `review.py` | prints each answer beside its key |
| `answers/*.json` | every answer record: runs, rendered text, citations, refusals, usage |
| `review-independent.txt`, `review-session.txt`, `review-long.txt` | what was graded |
