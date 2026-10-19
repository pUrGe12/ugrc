# The professor's questions: ugrc vs the RAG system

**Setup.** The professor's 11 questions (8 general, 2 table-based, 1 figure-based) over his 10 papers
(`~/Desktop/papers`), with the answers another system (a RAG pipeline) gave and his verdict on each
(`questions.json`). ugrc answered the same questions, worded exactly as he wrote them (typos included),
over the same 10 papers read as one corpus (`runs/papers-corpus`): Claude Opus 5.5 in the question
loop, every number a checked pointer. Receipt GREEN for all 11. Cost $2.03 ($0.18 per question).

For the three counting questions the professor's sheet says only "Expected a number". The reference
numbers below were derived from the papers **before** ugrc was run, and need his confirmation.

| # | question | RAG answer (his verdict) | ugrc answer | ugrc vs reference |
|---|---|---|---|---|
| G1 | max strain of V2O5 | <2% prestrain; DFT ±2% (correct) | <2% prestrain; measured max ~1.66% in-plane tensile (0.5% out-of-plane compressive, Poisson 0.3); DFT ±2% | right, more precise |
| G2 | battery passport possible in India? | BIGP concept + challenges; "possible in India if…" (correct) | the papers do not cover India (searched); the BIGP concept, mechanisms and obstacles from mattod-2020 | right; no unsupported conclusion |
| G3 | EG + PEG to extract critical materials from magnets? | not found (correct) | no; EG alone delaminates cathodes (cssc-2020), PEG appears only in a PANI-PEG coating | right, with context |
| G4 | lithium-free cathodes? | cobalt-free yes; lithium-free "not covered in the corpus" (correct) | **yes**: the sodium-sulfur cathode (nanolett-6b05172) and the pyrite cathode of the anode-free sodium battery (nanolett-6b05174) contain no lithium | right; **the RAG missed two papers** |
| G5 | max Poisson's ratio of V2O5 | 0.3 assumed; oxides 0–0.5 (correct) | same | right |
| G6 | sodium-ion electrolytes in lithium-ion batteries? | not found (correct) | not tested in these papers; shows each chemistry's own electrolytes; inference labelled as such | right |
| G7 | "copacity fo costal three battories" | read as cobalt-free; LNO 275 theoretical; "NFA practical values not given" (correct) | read as cobalt-free / the three NFA variants: **≈205, 199, 192 mAh/g** (adma-2020); NMM/NMT/NMA >200; LNO 275 theoretical | right; **the RAG said these values are absent** |
| G8 | references in the Materials Today paper | not found (**wrong**) | **156**, [1]–[156] without gaps | matches reference (156) |
| T1 | cathodes compared in the review articles | "at least four classes" (**wrong**) | **23** coated/uncoated comparisons in ensm-2021 Table 4 (computed by SQL), fewer distinct cathodes; also aenm-2022 Fig. 7 (NM82, NMT, NMM, NMA) | matches reference (23 entries, ~12 distinct) |
| T2 | references on DRX cathodes in the reviews | "at least five" (**wrong**) | **11**, [34]–[44] in aenm-2022; [27] left out as a general cathode reference; no DRX references in the other reviews | consistent with reference (9 in the section text, 12 with the figures and [27]) |
| F1 | flat voltage profiles for cobalt-free cathodes? | not flat, sloping (reasonable) | no; DRX profiles slope; the papers call no cobalt-free cathode flat | right |

## Summary

- **RAG, by the professor's grading:** 7/8 general, 0/2 table, figure "reasonable".
- **ugrc, by the references above:** 11/11, including all three counting questions the RAG could not
  answer, and two answers where the RAG's "correct" answer missed facts the corpus states.
- **Every number ugrc shows is a pointer** into a specific paper, page and box, with the DOI. The receipt
  re-checks all 11 with no model.

## What made the difference

- **Counting is computed, not guessed:** the reference list, Table 4's rows and the DRX citations are
  counted by SQL over extracted lines and table cells, and the count is traced to the atoms it read.
- **Tables are read as tables** (after the extraction fixes below), so "compared in the review" lands on
  the review's comparison table.
- **"Not in the papers" is a search,** shown with its terms, not a retrieval miss: G4 and G7 show the RAG
  answering "absent" for facts its retriever did not surface.

## Extraction fixes this needed (extractor v4)

Found on these 10 papers; the three earlier Chem. Eng. J. papers re-extract byte for byte:
- words glued together on pages with no space glyphs (7 of 10 papers, up to 80% of lines);
- Wiley rules drawn as touching pieces; one-column tables; rules between row groups; a rule above the
  caption: tables found 1/10 papers → 4/10 (all tables present);
- margin download notices set rotated (thousands of junk one-letter lines) skipped, by name;
- "FIGURE 1" captions in the margin (Materials Today: 0 → 5 figures).

Still open: ensm-2021 Table 4's columns (no drawn column rules, dense text: rows are right, columns are
not); ChemSusChem's margin line numbers are read as lines.

## Caveats

Graded by the assistant, not the professor. The three counting references, and the G4 and G7 judgments
(where ugrc disagrees with an answer he marked correct), are for him to confirm.

## Files

`questions.json` (questions, RAG answers, his verdicts, references), `run.py`, `answers/` (11 records
with traces).
