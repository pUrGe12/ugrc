# The big-library test: frozen plan

Written 2026-10-31 and frozen by hash (`frozen.sha256`: this plan, `GRADING.md`, `run.py`, `reworded.json`,
`questions.json`, `papers.json`, `routes.json`) before any answer of this test existed. `run.py answer` refuses to run if
any of them, or the library or routed test's frozen files, changed.

## The question

The routed test (`experiments/routed/`): keyword search picks one paper from a 10-paper library, then the model gets
only that paper's facts+prose form. It got 184 of 246 right, as many as with the right paper handed over (181), from a
7k-token prompt. But its libraries held 10 ChemE papers on mixed topics and the questions carry subject words, so search
found the right paper 244 times of 246. The user asked for more papers and more mixed topics. Two questions:

1. Does search-then-one-paper hold on a library of 120 papers, with several papers per topic and other fields?
2. Where search misses, does sending its top 2 papers recover the answer, and what does the longer prompt cost?

## The library

Every paper below whose ingest and clause base exist (`papers.json`, `run.py papers`): 120 papers, 1,964 pdftotext
pages, about 2.06M tokens of text.

| set | papers | questions | what | run |
|---|---|---|---|---|
| `cheme`, `cheme2` | 28 | 246 | ChemE, RSC Adv / ACS Omega 2025-26, 19 topics | `runs/cheme`, `runs/cheme2` |
| `new6` | 6 | 54 | sugar-refinery entrainment, Aspen transesterification, teak pyrolysis, lamb nutrition, agave genomics, ATLAS top quark | `runs/new6-v5` |
| `bench` | 11 | 88 | 10 battery papers (one group of authors), 1 siRNA delivery review | `runs/bench-v5` (new) |
| `arxiv` | 30 | 0 | arXiv battery materials, the 30 `scaling-more` used | `runs/arxiv` |
| `mixed` | 10 | 0 | from `~/Downloads`: ML (4), chip packaging, hardware reverse engineering, maths (2), bacterial sensing, biomanufacturing | `runs/mixed` (new) |
| `cheme3` | 35 | 0 | the next RSC Adv / ACS Omega papers of cheme2's own search hits, up to 2 per topic (`fetch.py`) | `runs/cheme3` (new) |

- **Close topics on purpose.** cheme3 puts 2-3 papers on each ChemE topic (a second transesterification paper next to
  aspen-transest and biodiesel, a second and third distillation paper). arxiv puts 30 more battery papers next to the 10
  asked about; three of those 10 discuss the same NFA cathode. Membrane separation and process simulation had no
  further eligible paper, fluidized bed one; one fermentation candidate failed to download three times and was skipped.
- **New ingests** use extractor v5 (frozen, `../cheme/extract.sha256`) and Jev's clause base, as cheme2. The bench
  papers are re-ingested with v5 (`runs/bench-v5`); `runs/bench`, used by the earlier bench tests, is untouched. The
  arxiv runs are the older extractor's, as ingested for `scaling-more`.
- **Dropped:** none; every ingest and clause base of the new papers succeeded.

## Questions

388 frozen questions (`questions.json`, `run.py build`), keys unchanged:

- **246 cheme / cheme2** questions in the library test's wording (`../library/reworded.json`).
- **54 new6 and 88 bench** questions (`../new6/probes.json`, `../bench-leads/probes.json`), reworded in
  `reworded.json` by the library test's rules before any answer of this test existed: table, figure and section
  numbers removed; "the paper", "the review", "the authors" replaced by a subject phrase from the title or the
  question's own words; a subject phrase added where the question would otherwise fit other library papers.
- **History.** The bench questions were used to design earlier setups (the short prompt, the hybrid), cheme ones to
  design the prose form; cheme2 and new6 were not used to design it. Results are reported by set.

## Router

As the routed test, over the whole library: every pdftotext page of every library paper, headed `=== <title>, page N
===`, ranked by the hybrid's BM25 on the question; the question goes to the paper of the top-ranked page. No model.
`run.py` tokenizes each page once instead of per question; on the routed test's 10-paper libraries it gives the same
route and the same top page for all 246 questions.

## Known before any answer

Measured with `run.py routing` and `run.py sizes` (no model):

| library | papers | right paper first | in top 2 | in top 5 |
|---|---|---|---|---|
| the library test's 10-paper libraries (cheme questions only) | 10 | 244 of 246 | 245 | 246 |
| the 45 papers asked about | 45 | 383 of 388 | 387 | 388 |
| + the 35 cheme3 papers | 80 | 382 | 387 | 387 |
| + the 30 arxiv and 10 mixed papers | 85 | 383 | 387 | 388 |
| **the whole library** | **120** | **381** | **386** | **387** |

- **By set, whole library:** cheme + cheme2 243 of 246, new6 54 of 54, bench 84 of 88.
- **The 7 misrouted questions:** 5 absence questions (`cheme2/distillation/A1` own paper 6th, `cheme2/techno-economic/A1`
  3rd, `bench/nanolett-6b05172/A1`, `bench/ensm-2020/A1`, `bench/mattod-2020/A1` 2nd), `cheme/adsorption/C1` (sent to
  cheme3's ZIF-67 photocatalysis paper, own 2nd) and `bench/aenm-2022/X1` (sent to adma-2020, which runs the same
  BatPaC analysis; own 2nd). Only 2 of the 7 go to one of the 75 added papers.
- **Against the routed test:** 243 of the 246 cheme top1 prompts are byte-identical to the routed test's prose
  prompts. The 3 others changed paper: `cheme2/fluidized-bed/B1` now goes to its own paper,
  `cheme2/techno-economic/A1` and `cheme/adsorption/C1` no longer do.
- **Prompt sizes** (characters / 3.6): top1 mean 7.0k tokens, max 23.6k; top2 mean 13.4k, max 35.4k; oracle (7
  prompts) mean 7.1k.

## Arms

| arm | what the prompt holds |
|---|---|
| `top1` | the routed paper in the facts+prose form: the routed test's prose prompt (`routed/run.py prompt("prose")`) |
| `top2` | the two papers search ranks first, each in the facts+prose form with its own 30 best sentences, best-ranked first, under a system prompt that says search picked them and the question does not name its paper |
| `oracle` | the question's own paper in the facts+prose form: the routed test's prose prompt on the right paper |

- **oracle** is answered only for questions top1 sends to another paper. Everywhere else its prompt is top1's, byte for
  byte, and top1's answer stands for it. So oracle - top1 is what routing costs.
- **Model and sampling:** as every Llama arm: Llama 3.1 8B Instruct, bf16 on vLLM (Modal, L40S), temperature 0.6,
  top_p 0.9, at most 4,096 output tokens, one reply, no tools.
- **One run per arm:** 388 + 388 + 7 = 783 answers.
- **Spend:** about 15 minutes of server time with the cold start, near $0.50 of the $1.35 Modal credit left on
  2026-10-31; the app is stopped right after the run.

## Grading

- **Blind:** each question's answers (2, or 3 with oracle) under letters in an order drawn by `big-library:<key>`;
  which arm a letter is stays in code until `grade.py unseal`. Grades are hashed (`graded.sha256`) before unsealing.
- **Rules:** the library test's (1-29, L1-L5), the routed test's R1, and B1-B3 in `GRADING.md` here.
- **Grader:** Claude.

## What gets reported

- **Right of 388 per arm**, and top1 - top2, top1 - oracle, top2 - oracle: sum of per-question differences, better /
  worse counts, exact paired sign-flip p (`blind.exact_p`).
- **Misrouted questions:** right per arm, and how many had their own paper in search's top 2.
- **By set and by category.**
- **Against the routed test** (10-paper libraries), the 246 cheme questions, paired: top1 - routed prose (graded in
  another session; descriptive).
- **Post hoc, descriptive:** a gated rule (top2 only when search is unsure) computed from both arms' grades.
- **Expected:** with 7 misroutes, 5 of them absence questions, top1 stays within a few answers of oracle; top2 can
  recover at most the 5 misses whose paper is second, and may lose routed-right questions to the longer, two-paper
  prompt. No outcome is excluded.
