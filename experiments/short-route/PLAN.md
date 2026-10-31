# Short questions: does search still find the paper?

Written 2026-11-01, before any short question existed. `short.json` is written by hand under the rules below, then
hashed with this plan in `frozen.sha256` before `route.py` runs search on any short question.

## The question

In the big-library test (`../big-library/`) BM25 over every page of 120 papers sent 381 of 388 questions to their own
paper, and search-then-one-paper got as many answers right as the right paper handed over (304 of 388). But the
questions were reworded for a library: a subject phrase was added wherever a question could fit more than one paper,
often in the paper's title words ("In the direct recycling of lithium-ion battery electrodes by solvent recovery, what
Ra values ..."). A user who has read the paper would type less ("What Ra values are given for EG and NMP?"). How often
does search still pick the right paper then?

## Short questions

Each of the 388 questions (`../big-library/questions.json`, field `q`) gets one short form: what someone who knows the
paper might type, without naming the paper.

- **S1. Drop the subject phrase:** words that name the paper's field, process, system or topic ("In the direct
  recycling of lithium-ion battery electrodes by solvent recovery,", "For ammonia co-firing with pulverized coal",
  "in the hydroquinone-catechol vacuum distillation", "for siRNA delivery"), unless the question cannot be read
  without them.
- **S2. Keep what picks out the value:** the sample, material or species the value belongs to (FeCoNiCrMn@CNTs,
  NFA 811, EG, SPIONs; "catechol mass fraction"), the conditions and numbers that select it (at 20% NH3, after 100
  cycles, at C/3), the quantity asked and its unit, and a cited author ("Gao et al."). A test or method name stays
  only where it tells two values of the paper apart ("measured in the drop-tube test" against "the simulation").
- **S3. Abbreviation over spelled-out name.** Where the question gives both ("lithium iron aluminum nickelate (NFA)"),
  keep the abbreviation. A name given only spelled out stays as written.
- **S4. Nothing added.** Only words of the question (a word's form may change: "optimized" to "optimization"),
  dropped or reordered, with articles, prepositions and "and" as grammar needs.
- **S5. False premises stay in,** as written.
- **S6. When unsure, drop.** A question that cannot be cut keeps its wording, and is counted as unchanged.

Written by Claude from the question alone (the key, the trap and the paper's title not consulted for wording). The
grader already knows which long questions search missed; the rules are there so that does not steer the cuts.

## What gets measured (no model)

`route.py`, with the big-library test's BM25 router unchanged (`../big-library/run.py`: `index`, `rank`,
`paper_order`):

- for short and long questions: the right paper ranked 1st, in the top 2, the top 5, on the whole 120-paper library,
  on the 45 papers asked about, and on the library test's 10-paper libraries (ChemE questions);
- by set and by category; word counts of the two forms;
- the questions whose route changes.

**Next, only if routing drops** (decided with the user, not here): answer the short questions with search-then-one-paper
and the right paper handed over, as in the big-library test, to see what the misroutes cost.
