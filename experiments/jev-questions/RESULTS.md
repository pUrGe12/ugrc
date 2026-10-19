# Better questions for Jev (clause v6 / v7)

**Goal.** Ask the judge better questions so the clause base, read once per paper, binds each value to
what it is about more often and binds it wrongly less often; and push more of the reading onto the cheap
judge instead of the LLM.

**Test design.** Paper 2's gold (95 values) was used to develop v1–v5, so it is the dev set. Paper 3 got
a new gold (`paper3-gold.json`, 156 values, 84 of them quantities), written from the extracted sentences
**before any v6 question was asked on it**: that is the held-out test. v6 was frozen by hash
(`frozen.sha256`) before it ran on paper 3. v7 holds two fixes found on paper 3, so its paper-3 numbers
are post-hoc and reported separately.

## Results (jev-latest; `grade.py`)

| | v5 (before) | v6 (frozen) | v7 (post-hoc fix) |
|---|---|---|---|
| **paper 3, held-out:** every slot right | 25/84 | **55/84** | **63/84** |
| subject right | 35/84 | 65/84 | 73/84 |
| no wrong subject | 54/84 | 84/84 | 82/84 |
| wrong bindings (all slots) | 35 | 15 | 18 |
| role right | 116/156 | 151/156 | 151/156 |
| property right | 74/84 | 83/84 | 83/84 |
| paper 2, dev (amended gold): every slot | 55/79 | 59/79 | 58/79 |
| paper 2: wrong bindings | 29 | 13 | 13 |

jev-preview gives the same picture (paper 3, v5 24/84 → v6 54/84). A whole paper costs 625 Jev calls,
~392k input tokens: about **$0.02 at $0.042/M**, against ~$0.08 per *question* for the Claude loop.

`paper2-gold-amended.json` only adds tolerated items where v6 names a quantity or method by a phrase the
old gold could not anticipate (v1–v5 never offered phrases); every amendment is listed in the file. The
original gold is reported alongside in the run log.

## What changed in the questions

| v5 asked | v6 asks | why |
|---|---|---|
| "How is T related to [[v]]?" for every term: about / measured by / unrelated | each named term's **kind once per paper** (organism, material or thing, method, measure, other); per value one competitive choice per slot, offering only spans of that kind, plus "none of these" | independent per-term questions over-bound (LOD, OD600 and CD as subjects: the X1 false pairs) |
| 14 property options | options **narrowed by the unit** (°C is a temperature, decided; nm is size or wavelength) | fewer, concrete options |
| a 5-option role question | "quantity or label?" (only when there is no unit) + "measured / chosen / cited?" | two easy questions |
| previous + current sentence | the one sentence, candidates from the value's own clause first | fewer distractors |
| — | layout decides: `65 mM [NaCl]`, `320 μL of [the above solution]`, `[N] signals`, `X, Y … respectively`, `9.2 × 10^7 CFU/mL ([P. aeruginosa])`, `[NaCl] from 65 to 95 mM`, `Phase [1]` is a label | never ask what the sentence's structure says |
| — | each judge choice is asked again as a yes/no; kept only if both agree, else withheld and flagged | catches confident wrong picks |

Candidates also grew: strain and part codes (R82, H32, P6), defined abbreviations, nominal phrases
("the above solution", "these bacteria", "fed-batch fermentation"), each phrase typed once in its own
sentence. Mentions were fixed: units read `g L^(cid:0) 1` (no phantom "1"), chemical locants (`2,3-BD`,
`1,8-cineole`) are not values, a unit printed once after a list applies to the whole list, months/years
are units.

## v7: two fixes found on the held-out paper

1. The organism question asked "is 11.4 g/L **the concentration of** R82?". Jev picked R82 correctly and
   then (correctly) answered *no* to the confirmation: the titer is of prodigiosin, made by R82. Now asked
   as "reported for (measured in, made by, or given for)". Recovered R82, H32, HBQA7, PG-6 ×2, SK4–72,
   SN3, UCP 1549. Cost: two new wrong picks (`isolates` for the pan-genome gene counts, *B. subtilis* for
   a titer where it is only the gene source).
2. "using" (5 letters) escaped the verb rule, so "geraniol using two-phase fermentation" was one phrase.

## What is left wrong (paper 3, v7)

Mostly misses, not wrong picks: values whose subject is outside the sentence or is a generic noun
("Native products", "genome", "library"), and some method/quantity phrases the gold does not list.

## Files

`clauses_v5.py`, `clauses_v6.py` frozen copies; `run.py` builds one base (`v5|v6|v7`, any judge URL);
`grade.py` grades against either gold format; `runs/` holds every base.
