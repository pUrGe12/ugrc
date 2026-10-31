# Facts plus prose on 20 more papers: plan

Written 2026-10-30, before any of these papers was fetched or read. Asked by the user: "get more PDFs, let's try this
out in bigger numbers to see if the result scales". The result is `experiments/prose`: on 148 questions, the
condensed clause base plus the few number-free sentences that best match the question (facts+prose) got 330 of 444
right, against 298 for the condensed form alone (p = 0.018) and, graded earlier, 294 for the pasted PDF. That method
was designed after reading those questions' losses. This test runs it, unchanged, on new papers and new questions.

## What is compared

Three arms, each Llama 3.1 8B on the Modal server with the same sampling as every bench run, one free reply, no tools:

- **prose:** `experiments/prose/run.py`'s `document()` and `prompt()` unchanged (up to 30 sentences, 5,000 characters,
  BM25 against the question).
- **facts:** the condensed clause base alone, `experiments/cheme/run.py`'s facts arm unchanged.
- **pdf:** the PDF's `pdftotext` with `bench-llama/direct.py`'s prompt, `experiments/cheme/run.py`'s pdf arm unchanged.

Three runs per arm. Atoms from extractor v5 (`ugrc/extract.py`, still the hash in `../cheme/extract.sha256`), clause
bases built with Jev as for the ChemE papers.

## The new papers

Chosen by rule, not by reading them, by `fetch.py`: the ChemE test's rule (Europe PMC,
`TITLE:"<topic>" AND (JOURNAL:"RSC Advances" OR JOURNAL:"ACS Omega") AND OPEN_ACCESS:y AND PUB_YEAR:[2025 TO 2026]`,
newest first, the first candidate that passes every filter), over 20 topics:

- the ChemE test's 10 topics again (distillation, adsorption, reactor, pyrolysis, CO2 capture, membrane separation,
  crystallization, heat transfer, techno-economic, fluidized bed), skipping the papers that test already took;
- 10 new ones: gasification, biodiesel, wastewater treatment, hydrogen production, solvent extraction, drying, mass
  transfer, process simulation, catalytic, fermentation.

A paper taken for an earlier topic is skipped. Filters, as in the ChemE test: (1) the PDF is in PMC's open-access
dataset; (2) 5 to 25 pages; (3) `pdftotext` gives at least 15,000 characters; (4) a `pdftotext` line starts with
"Table 1"; (5) `ugrc ingest` (v5) and the clause base build without error (a paper failing 5 is replaced by the next
candidate). A topic with no paper passing gives none; the test then has fewer than 20.

## Questions

Written from each paper's `pdftotext` (plain and `-layout`) only, not its clause base, not ugrc's atoms, not any
document an arm builds, and before any answer exists. 8 a paper, in the earlier categories: one lookup (C), one binding
trap (B), two table (T), one computation (X), one chained lookup (H), one false premise (F), one absence (A). Where a
paper prints fewer than two usable tables, the second T becomes a second C. Frozen by hash with this plan
(`frozen.sha256`) before the first run.

## Grading

Every answer blind to arm: a question's 9 answers (3 arms x 3 runs) under letters shuffled by a fixed seed, graded
correct / partial / wrong by the rules in force (`../cheme/GRADING.md` and those it points to, `../prose/GRADING.md`
24-25); any rule settled while grading is written to `GRADING.md` here before unsealing; grades hashed before unsealing.

## Reported

- Primary, two paired sign-flip tests over the questions, right answers summed over the three runs: prose against pdf
  (does it beat pasting the paper?) and prose against facts (does the earlier gain replicate?).
- Then: by category (from the earlier test, expected: prose ahead of facts on chained and lookup questions, behind on
  computation), by paper, by topic group (old topics against new), prompt sizes, Modal cost.
- Pooled with the ChemE questions (prose's earlier 148, graded in `../prose`) only as a description, not a test.

These papers and questions can later serve a many-papers-in-one-prompt test, the other sense of "scales"; that is not
part of this plan.
