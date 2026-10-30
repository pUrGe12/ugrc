# The ChemE held-out test: plan

Written 2026-10-30, before any of these papers was fetched or read. Asked by the user: fix table extraction, try the
clause form from before, run more papers, compare all.

## What is compared

Three arms, each Llama 3.1 8B (the Modal server, same sampling as every bench run), one free reply, no tools:

- **hybrid:** `experiments/bench-cross/hybrid.py` unchanged: pages rendered from ugrc's atoms (tables row by row),
  Jev's lead pages first, then BM25, up to 24k tokens (a paper that fits goes whole); code points each number at the
  atom that prints it.
- **facts:** the condensed clause base of the scaling test, the paper alone (`llama-scale-facts-L1` there): page by
  page the clause-base sentences that print a value Jev did not read as an identifier, then the tables row by row,
  with the scaling test's system prompt for that form.
- **pdf:** the PDF's `pdftotext`, with `bench-llama/direct.py`'s prompt (`llama-direct`).

Three runs per arm. Atoms come from extractor v5 (`ugrc/extract.py`, hash in `extract.sha256`, frozen before any
paper below was fetched): the 6 papers of `experiments/new6` re-ingested into `runs/new6-v5`, and the new papers into
`runs/cheme`. The pdf arm does not depend on the extractor, so on new6 its three runs are reused from
`experiments/new6/answers/llama-direct-r*` (same server, model, prompt and sampling).

## The new papers

Chosen by rule, not by reading them. For each of 10 chemical-engineering topics, a Europe PMC search
(`TITLE:"<topic>" AND (JOURNAL:"RSC Advances" OR JOURNAL:"ACS Omega") AND OPEN_ACCESS:y AND PUB_YEAR:[2025 TO 2026]`,
newest first) gives candidates; the first one that passes every filter below is the topic's paper. A paper already
taken for an earlier topic is skipped.

Topics, in this order: distillation, adsorption, reactor, pyrolysis, CO2 capture, membrane separation, crystallization,
heat transfer, techno-economic, fluidized bed.

Amended after the first search, before any paper was read: the bare topic "membrane" chose a database of membrane
proteins (PMC13688505), which is not chemical engineering; the topic became "membrane separation".

Filters, in order, all on files the publisher and PMC provide (none on how ugrc reads the paper, except the last):

1. the PDF is in PMC's open-access dataset (`pmc-oa-opendata` on S3, the route PMC documents for scripts);
2. 5 to 25 pages;
3. a text layer: `pdftotext` gives at least 15,000 characters;
4. it prints a table: a `pdftotext` line starts with "Table 1";
5. `ugrc ingest` (extractor v5) and the clause base build without error.

The search results, each candidate's verdict and the chosen PMC ids are saved (`candidates.json`, `papers.json`).

## Questions

Written from each paper's `pdftotext` before any answer to them exists, in new6's categories (lookup C, binding
trap B, table T, computation X, chained H, false premise F, absent A), about 8-11 per paper; frozen by hash with this plan
(`frozen.sha256`). The new6 questions stay as frozen in `experiments/new6/probes.json`.

## Grading

Every answer blind to arm: a question's 9 answers (3 arms x 3 runs) under letters shuffled by a fixed seed, graded
correct / partial / wrong by the rules of `experiments/new6/GRADING.md`, the grades hashed before unsealing. On new6 the
pdf arm's answers are graded again blind among the others; the earlier grades of those same answers measure how
consistent the grader is.

## Reported

Right answers per arm and run; paired sign-flip tests between arms per question; by category, by paper, and new6
against the new papers; how many table questions each arm gets; the Jev checker (frozen) on every arm; Modal cost.

Outcome of the search (2026-10-30): "membrane separation" had one candidate, which prints no table, so the rule gives 9
papers, not 10 (`candidates.json`, `papers.json`).

Filter 5 (2026-10-30): all 9 papers ingest and build their clause bases (`runs/cheme`, `prepare-cheme.log`).

Seen before any run, from the stores alone: extractor v5 finds 12 of the 50 tables these 9 papers print (adsorption 3
of 3, reactor 4 of 9, distillation 2 of 15, pyrolysis, fluidized bed and CO2 capture 1 each, crystallization 0 of 6,
heat transfer 0 of 2, techno-economic 0 of 7); the 8 ACS Omega papers lose most of theirs. The extractor stays as
frozen: the test measures v5 as it is. A missed table's text still reaches the hybrid as page lines, and the facts form
as sentences, only not row by row.
