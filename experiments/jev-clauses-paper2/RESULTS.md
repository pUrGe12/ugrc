# Can a classifier write the clauses? Jev over paper 2

**Question.** The clause idea: read a paper once into formal clauses, then answer questions by deterministic
query. Can a non-generative judge (TypeSafe's Jev, which only *chooses* among options it is given) do
that reading, instead of a generative model?

**The twist that makes it possible.** A clause's arguments are spans of the paper: the value, its unit, the
thing it is about, the method. So writing a clause becomes a series of *choices among spans that already
exist*, and choosing is what a selector does. Jev cannot invent an argument. It can only pick a wrong one.

**Setup.** Paper 2 (Liu et al., Chem. Eng. J. 549 (2026) 182243), `jev-latest` (served as `jev-1.13.0`),
`ugrc/clauses.py`.

## The pipeline

| stage | what | who |
|---|---|---|
| sentences | body, abstract and captions cut into sentences; furniture, references and heading numbers out; every character maps back to its line atom | code |
| mentions | every quantity: text, interval, unit, `KEY =` prefix. Figure refs, citations, links, names with digits ("4-MPBA", "OD600") are not quantities. An unmapped glyph before a number makes its sign unknown | code |
| candidates | named terms (species, abbreviations, materials, methods) of the sentence and the one before; phrases beside a value ("160 μL of [each bacterial suspension]", "[an average length] of 90 nm", "4 [signals]") | code |
| definitions | "limit of detection (LOD)", "(4-MPBA, BA)", matched letter by letter (Schwartz–Hearst) | code |
| structure | the layout decides what it can: the words before "of VALUE" and the key of "KEY =VALUE" name the quantity; a coordinated list shares it; a term in parentheses right after the value is bound to it; a term printed inside the value is its unit | code |
| judgments | per value: role (result / setting / count / background / identifier), property kind, which words name its quantity. Per value × term: about / measured by / unrelated. Per sentence: modality, polarity; per definition: right or wrong | **Jev** |
| door | hedge words vs modality, negation words vs polarity, structure vs judge, one subject with two values, bindings across sentences: all **flagged**, never corrected | code |

Every request and response is pinned in `clauses.duckdb` with a seal. 298 calls per paper (203 sentences,
95 values; 1,138 questions, at most 12 in one call). About 262k input and 62k output tokens, around 2
minutes with 8 workers. I don't know Jev's price.

## Results

**Gold:** written by hand for all 95 values before any Jev call (`gold.json`). Bindings are graded for the
79 that are quantities. The other 16 are dates, postcodes, grant and version numbers, and the "1 s" of
"B 1 s peak".

| decision | v1 | v5 (final), run 1 | v5, run 2 |
|---|---|---|---|
| role | 93/95 | 93/95 | 93/95 |
| property kind | 76/79 | 76/79 | 76/79 |
| subject ("about") | 53/79 | **65/79** | 63/79 |
| method ("measured by") | 74/79 | **76/79** | 75/79 |
| quantity | 63/79 | **74/79** | 74/79 |
| every slot right | 41/79 | **57/79** | 55/79 |
| strict: subject / method / quantity, no tolerance list | – | 45 / 70 / 71 | 43 / 71 / 71 |

The lenient grade accepts a predicted binding that the gold lists as tolerable for that value (`ok`), in any
slot. The strict row drops that list: it is the lower bound.

**What it got right that matters:**
- All 7 viable cell counts went to the right strain.
- All 4 detection limits got the right strain and the right method.
- Both nanorod lengths went to the right material.
- The 16 non-quantities were all classed as identifiers, except two settings read as results.

**Where the errors come from:**

| cause | values | example |
|---|---|---|
| the true subject is not among the candidates | 28 | "Cys", "the tube", "the mixtures", "four strains", "these bacteria" |
| extra subjects added (Jev) | most of the rest | "CD" as what a concentration is about; "LOD" and "OD600" as subjects of the "versus" values |
| counts | 3 | "4 signals × 7 bacteria × 5 replicates": property read as signal/amount/other, noisy bindings |

When the true subject was not offered, Jev bound nothing wrong in 24 of the 28 cases. The candidate
generator, not the judge, is the larger gap.

**What changed from v1 to v5,** all from the same pinned answers (v2 onward) with zero new calls, by
`clauses.replay`:

| version | change | why |
|---|---|---|
| v1 | four relation labels per term, including "names the quantity" | Jev almost never chose that label: "LOD" and "average length" came back as "about" |
| v2 | the quantity becomes one choice among the candidates | the forced choice rarely picks "none"; for "65 mM NaCl" it named NaCl, and letting it win deleted NaCl as the subject |
| v3 | a quantity choice that names a term judged about/measured by is withheld | two judgments that disagree are not reconciled by preferring the forced one |
| v4 | the layout decides the quantity where it can | "an LOD of", "an average length of", "OD600 =", lists share it: no judgment needed |
| v5 | a term printed inside the value is its unit | "CFU" in "9.2 × 10^7 CFU/mL" was listed as a subject, which broke one-subject queries |

The lesson is the one mesh keeps learning: the biggest gains came from letting structure decide and
asking the judge less, not from better wording.

## Is it reproducible?

The whole extraction was run twice per request set:

| requests | decisions identical | flipped | largest winning probability among the flips |
|---|---|---|---|
| v1 | 1,021 / 1,043 | 22 | 0.63 |
| v2 (used by v5) | 1,123 / 1,138 | 15 | 0.58 |

Every flip was a near tie. So re-running reproduces the confident decisions, and the ones that flip are
exactly the ones a margin would mark as uncertain. `ugrc clauses-check --rerun` asks every pinned question
again and lists each flip with its pinned margin.

The zero-model receipt (`ugrc clauses-check`) checks four things, and is green on both runs:
- the seal covers the rows;
- the base was built on this substrate;
- re-planning asks exactly the pinned questions;
- re-deciding from the pinned answers reproduces every row.

On a copy with one subject edited (L. monocytogenes → E. coli), two lines fail: the seal, and the
re-decided measures.

## Answering probes from the clause base alone

These answers use plain SQL over `measures` (`queries.py`, `queries-run1.txt`), with no model reading the
paper. I wrote the SQL by hand, standing in for a question-to-query step that is still undecided. Every row
carries its line atoms.

| probe | answer from clauses | |
|---|---|---|
| B1 CD LOD for L. monocytogenes | 0.0123 (p6.L61) | ✓ |
| B2 strain with 7.6 × 10^7 CFU/mL | E. sakazakii (p3.L32) | ✓ |
| B3 highest / lowest viable count | P. aeruginosa 9.2 × 10^7; S. typhimurium 6.4 × 10^7 | ✓ |
| B6 concentration range | OD600 = 0.02–0.2 (body p6.L50 and Fig. 3 caption p6.L79) | ✓ |
| C2 average lengths | AuNRs 90 nm, HGNRs 126 nm | ✓ |
| C4 feature matrix | 4 signals, 7 bacteria, 5 replicates (noisy extra bindings) | ✓ |
| C6 NaCl added | 30 μL, to 65 mM | ✓ |
| F2 UV–vis LOD for E. coli | no clause | ✓ (not reported) |
| F4 blind-test accuracy on ternary mixtures | the only accuracy clause is 100% about nothing named; none mentions mixtures | ✓ premise unsupported |
| F5 why 120 μM 4-MPBA | 165 μM is the chosen setting (p4.L14); 120 μM is the top of a tested range "0 to 120 μM" | ✓ premise false, visible |
| C3 variance shares of the two factors | 99.9% and 0.1%, plus an unrelated 95% from another LDA sentence | partial: needs the sentence to tell them apart |
| X1 CD lower than UV–vis for every strain? | P. aeruginosa 0.0034 vs 0.0066 (×1.94) and L. monocytogenes 0.0123 vs 0.0125, correct; **plus two false pairs with "OD600" as the subject**, one saying CD is *not* lower | ✗ an extraction error became a query error |

X1 is the risk predicted for any one-time extraction: a wrong binding is inherited by every query, and a
naive "for every subject" aggregate would have answered "no". The bad rows are visible, because the two
values point at different lines (p6.L61, p6.L60). But nothing at the door stops them.

## What this says

- **Yes, a selector can write most of the measured-value clauses** of a paper when the code proposes every
  span and the layout decides what it can:
  - roles 98%, methods 96%, quantities 94%, subjects 82% (lenient);
  - strict: subjects 57%, methods 89%, quantities 90%.
- **It cannot invent anything,** and its uncertain decisions are the ones that flip on re-run, which makes
  the extraction re-checkable in a way a generative pass is not.
- **The weak part is the candidate generator,** not the judge. Subjects that are common nouns ("the tube",
  "these bacteria") or never defined ("Cys") are never offered.
- **Extra bindings are the judge's main error,** and they are the dangerous kind for queries (X1).

## Limits of this test

- one paper, 95 values, graded by me against my own gold;
- the strict and lenient grades differ a lot on subjects (45 vs 65);
- the five versions were developed while looking at this gold, so v5's numbers are optimistic for unseen
  papers (v1's are the clean first measurement);
- sentence modality and polarity have no gold yet: 12 sentences are flagged by the hedge and negation
  checks, unaudited;
- no table-heavy paper yet; paper 2 has no tables.

## A worked example

`docs/jev-worked-examples.md` walks one LOD question end to end — the sentence, what the layout settles,
the exact questions put to Jev with their probabilities, the clause rows, and the SQL that answers it with
no model at answer time. It also shows the spurious `OD600` pairing that the same clause rows produce, and
pairs the case with a paper-3 question the clause base cannot answer at all.

## Files

| file | contents |
|---|---|
| `gold.json` | hand labels for all 95 values, written before any Jev call |
| `grade.py` | the grader (`python grade.py RUN [OTHER_RUN]` also compares two runs) |
| `queries.py`, `queries-run1.txt` | the probe queries and their output |
| `run1/`, `run2/` | v5 clause bases (replayed from `v2/` answers) |
| `v1/` ... `v4/` | earlier versions and their grades |
