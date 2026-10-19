# Full pipeline on paper 3: a review article with three large tables

**Paper.** Wang et al., *Serratia marcescens as an environmentally robust non-model chassis for green
biomanufacturing of natural products*, Chem. Eng. J. 549 (2026) 182355. 17 pages, 3 tables, 7 figures.

This is the first **review** the pipeline has been run on. Papers 1 and 2 were research articles. A review
is a harder case in one specific way: most of its numbers live in large tables, attributed to other
people's work, and the prose paraphrases the tables, so text and table can disagree.

**Probes.** 29 questions with expected answers and traps, written from my own reading of the extracted
atoms and the figure images, **before any answer was generated** (`probes.json`).

## What ran

| stage | result | model |
|---|---|---|
| ingest (PDF to atoms) | 1,560 lines, 3 table parts, 385 cells, 7 captioned figures + 3 uncaptioned images, nothing declined; 24 s | none |
| OCR | 210 lines from 7 figures | tesseract |
| figure reading | 264 facts, 84 OCR-confirmed | claude-opus-5-5 |
| clause base (Jev) | 385 sentences, 156 measures, 26 aliases; 541 calls, 421k input tokens, 36 s | jev-1.13.0 |
| 29 probes | 170 tool calls (median 5 per answer), 34 door refusals, all recovered | claude-opus-5-5 |
| receipt | **GREEN**: substrate re-extracted from the PDF, all 29 answers re-render and all 343 citations re-resolve | none |
| clause receipt | **GREEN** | none |

**Cost:** $3.05 for the 29 answers (~$0.105 each), $0.018 for the whole clause base at $0.042/M input.

## Grading: 27 of 29 fully correct

| category | n | result |
|---|---|---|
| controls | 7 | 7 correct |
| binding (value whose subject sits elsewhere) | 4 | 4 correct |
| table superlatives and aggregation | 5 | 3 correct, 2 with a wrong secondary claim |
| false premises | 4 | 4 rejected |
| absence | 3 | 3 correct |
| figure-only facts | 3 | 3 correct |
| cross-source consistency | 3 | 3 correct |

**Zero invented values, zero altered quotes, zero accepted false premises, zero false absences.**

### The 343 citations

| kind | n | what it means |
|---|---|---|
| quote | 198 | verbatim span, located by the machine |
| support | 93 | a sentence of the model's own words pinned to a source line |
| table | 17 | a named table cell |
| computed | 20 | a value produced by SQL with row-level lineage |
| figure | 11 | a vision-model reading, labelled as such |
| search | 4 | an absence claim backed by a search over all 2,446 atoms |

### The two errors

Both are the **same class**: a comparison or aggregate stated in prose, or computed by SQL whose
semantics don't match the table's layout. Neither is an invented fact; both are visible in the citations.

1. **T1 — a wrong ranking.** The answer correctly identified the highest titer in Table 2 ((−)-α-bisabolol,
   SMB19, 102,300 mg/L, fed-batch, 110 h) with the maximum computed by SQL. It then added that "the
   next-highest entries are (E)-nerolidol at 70,500 and acetoin at 75,200". The true second-highest is
   **89,810** ((2R,3R)-2,3-butanediol, ΔslaC-bdhA), which it skipped. The primary claim was computed; the
   secondary ranking was prose with quote citations, and nothing checked it.

2. **T3 — a right count with a wrong share.** The counts were computed by SQL and are correct: 15
   fed-batch, 10 shake flask. The medians it computed (32,500 vs 7,240, a 4.5× ratio) are also correct. But
   it then reported fed-batch as "52%" of entries. The SQL counted *cells*, and the two whole-cell
   biocatalyst entries occupy two cells each ("whole-cell" / "biocatalyst" on separate printed lines), so
   the denominator was 29 instead of 27. The true share is 55.6%. **The receipt reproduces this exactly** —
   it is a faithful re-run of a query whose semantics were wrong.

   This is worth stating plainly: *the receipt proves a number re-runs from its sources; it does not prove
   the query asked the right question.* That is the verifier's half of the job, and it isn't built here.

### Three real findings in the paper

These weren't planted. The pipeline surfaced them:

1. **B1 — a text/table contradiction.** The text says strain R82 reached 11.4 g/L "in 5 L fed-batch
   fermentation" (p9.L20). Table 2's row for the same strain and the same titer (11,400 mg/L) records the
   cultivation mode as **shake flask**, 48 h. The answer reported the disagreement and did not try to
   resolve it. Confirmed by hand.
2. **X2 — self-contradictory wording.** One sentence reads "...efficient biosynthesis of various terpenoids
   in shake flasks, with limonene and nerolidol reaching 14.12 and 32.33 g/L, respectively, **in 5-L
   bioreactors**" (p10.L48–p11.L2). The answer flagged the tension rather than picking one.
3. **X3 — a strain-naming mismatch.** The text calls a strain "PG" (p8.L82); Table 2 calls the same entry
   (same strategy, reference, titer 5830 mg/L = 5.83 g/L) "SMCH". The answer matched the row by strategy,
   reference and titer, converted the units with the canon constant, and reported that the names differ and
   the paper reconciles them nowhere.

### Noteworthy good behaviour

- **C7** was asked how 235 ATCC strains split between biosafety levels. The paper gives 208 BSL-1 and 10
  BSL-2 and never accounts for the rest. The answer computed the residue (**17**) in SQL and said plainly
  that the text leaves them unaccounted for.
- **F4** asked for a squalene titer. "Squalene" is hyphen-broken across lines as "squa-" / "lene" and a
  naive search finds nothing. The flow-joining rule found it, and the answer correctly reported it as a
  future target, not a result.
- **F2** backed "no CRISPRi system exists" with both a quote ("CRISPRi and CRISPRa are lacking") and a
  search for `dCas9` returning 0 matches across all 2,446 atoms.
- The figure reading of Fig. 2 was checked panel by panel against the image: **every value correct**
  (μ = 59.74%, r = 0.57, p < 0.001, all three pan-genome definitions, all six plasmid host-range
  percentages, all three habitat isolate counts).

## Two new defects, both caused by this paper's typesetting

The journal renders the exponent minus sign as an unmapped glyph: `mg L^(cid:0) 1` is `mg L⁻¹`, and
`((cid:0) )-α-bisabolol` is `(−)-α-bisabolol`.

1. **Unit truncation in the clause base.** 35 of 156 measures have a unit cut off at the glyph: `102.3 g`
   instead of `102.3 g/L`, `119.8 g` instead of `119.8 g/kg`, `15,420.9 mg` instead of `15,420.9 mg/L`. The
   *values* are right and the pointers are right, but the units are incomplete, so any cross-row comparison
   over clause units would be comparing bare numbers. Papers 1 and 2 had clean units (μM, nm, OD600), so
   this never appeared before.
2. **It leaks into rendered answers.** Several answers print "47.5 g L" or "5.8 g L". The underlying quote
   is correct and the receipt re-resolves it; the rendering drops the exponent.

Neither causes a wrong value. Both should be fixed by teaching the extractor that `^(cid:N) 1` after a unit
is an exponent, the same way the door already handles a `(cid:N)` before a number as an unknown sign.

## The clause base does not cover tables

(Worked side by side with a question the clause base *does* answer, in `docs/jev-worked-examples.md`.)

**0 of 156 measures come from a table cell** — `clauses.py` reads only the `lines` relation. For paper 2
that cost nothing, because paper 2 has no tables. For this paper it means Table 2's 27 titers, the richest
numeric content in the article, are absent from the clause base. The Claude loop reads them fine (17 table
citations, 20 SQL computations), but the deterministic clause route cannot answer T1–T5 at all.

Other clause observations:
- **Modality is informative.** 184 of 385 sentences were judged `background`, against 42 `result` — the
  right shape for a review, which mostly reports other people's work. Paper 2, a research article, was the
  opposite.
- **Definition checking works.** Of 26 aliases, Jev accepted PTS = phosphotransferase system, LPMO, MAP and
  MBC, and rejected bad ones the pattern matcher proposed (ChiA = "chiti-nases", PigP = "Positive
  regulators").
- 104 of 156 measures carry at least one door flag, much higher than paper 2 — consistent with prose where
  subjects are common nouns the candidate generator doesn't offer.

## What this run says

- **The guarantees held on a new document type.** Everything the design promises — no invented value, no
  altered quote, every number traceable, honest absence — held across 29 answers, and the receipt is green
  with zero model calls.
- **The failure mode is exactly the predicted one.** Both errors are unchecked reasoning *over* checked
  values: a ranking asserted in prose, and a query whose semantics didn't match the table. This is the gap
  the claim/ALU step was meant to close.
- **Tables are where a review's facts are, and the clause route can't see them.** That is the most useful
  single thing to fix next for this document type.
- **Extraction is the floor.** The `(cid:0)` exponent is a reminder that a typesetting quirk silently
  degrades everything above it. The values survived; the units didn't.

## Files

| file | contents |
|---|---|
| `probes.json` | 29 probes with expected answers and traps, written before the run |
| `run.py` | the runner |
| `answers/*.json` | every answer record: runs, rendered text, citations, refusals, usage |
