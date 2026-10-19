# Jev test bench: the professor's 10 battery papers

**Setup.** 10 papers (`~/Desktop/papers`), split before anything ran (`split.json`, seeded, drawn within
each publisher): **tuning** adma-2020, cssc-2020, ensm-2020, mattod-2020, nanolett-6b05174; **held out**
acsnano-7b02404, aenm-2022, ensm-2021, nanolett-6b05172, susmat-2020. Answer keys (`gold/`) for 15
values per paper drawn at random (150 values, 61 of them quantities), written from the sentences
before any Jev call on these papers. Judge: jev-latest. Grader: `grade.py` (rules of
`experiments/jev-questions/grade.py`).

## Results

| | v7 tuning | **v8 tuning** | v7 held-out | **v8 held-out** |
|---|---|---|---|---|
| quantities with every slot right | 13/26 | **18/26** | 18/35 | **19/35** |
| subject right (no wrong subject) | 18 (21) | **22 (25)** | 23 (30) | **26 (33)** |
| method right | 24 | 23 | 32 | 32 |
| quantity right | 22 | 23 | 29 | **32** |
| property right | 22/26 | **26/26** | 30/35 | 31/35 |
| role right (all values) | 68/75 | **74/75** | 67/75 | **71/75** |
| wrong bindings | 9 | **6** | 11 | **7** |
| Jev cost, all 10 papers | $0.22 | **$0.17** | | |

No regression on the earlier chemistry papers: paper 2 58 → 59/79, paper 3 63 → 63/84.

v8's changes were designed on the tuning papers' errors only; the held-out column is the honest one.
It is a small sample (35 quantities), so its +1 on "every slot" is within noise; fewer wrong bindings
(11 → 7) and more right subjects (+3) and quantities (+3) are the clearer gains.

## What v8 changed (all in code before the judge; no question wording changed)

Found on the tuning papers:
- **The reference list leaked into the prose** (ACS "■ REFERENCES"; Wiley prints no heading): 856 of
  2,421 values were citation years, volumes and pages. Now the list ends the prose whether headed or not.
- **Battery units were missing** (mAh, mA, Wh, kWh, mAh/cm², ¢/kWh, miles, metric tons…), so "12
  mAh/cm^2" read like "4 signals": a count whose subject was the unit. Added, with spaced and positive
  exponents (`g^− 1`, `cm^2`, `cm^−1`), scale words ("11 million metric tons") and hyphen ranges
  ("10-15 min"); the stray unit "d" (a bullet glyph in Materials Today) removed.
- **A label stays inside its name** ("NFA 811"), so "NFA 811, NFA-F, and NFA-A … ≈205, 199, and 192
  mAh g^−1, respectively" pairs in order.
- Battery and ChemE measure words (capacity, voltage, retention, loading, conductivity, strain …).

## Found on the held-out papers (not fixed: fixing them needs a fresh held-out set)

- "wt.%" is now a unit but not mapped to concentration, so the property question offers no
  concentration (3 values). A v8 bug.
- ACS superscript citations ("…reports.^43,48") are read as values.
- ">500 Raman spectra" is not taken as a count (the comparison sign).
- Two answer-key items are stricter than they should be (the precursor's formula VO(OC3H7)3 for
  "VTIP"; "200 million vehicles" judged a count).

## The noise this corpus showed

Of the 150 values sampled from the v7 extraction, 89 were not quantities: reference-list numbers,
author and affiliation marks, journal headers, page numbers, and phantom "1"s from `g^− 1`. Battery
papers are dominated by values the chemistry papers rarely had, and the property list still has no
kind for capacity, voltage, energy density or current density (graded as "other"/"signal" here).

## Files

`split.json`, `gold/<paper>.json`, `run_all.sh` / `run_v8.sh`, `runs/v7`, `runs/v8` (one clause base per
paper), `grade.py`.
