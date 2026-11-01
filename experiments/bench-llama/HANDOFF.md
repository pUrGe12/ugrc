# Handoff: Llama 3.1 8B against ugrc (updated 2026-10-30)

Results, numbers and reasoning live in the methodology doc, not here:
https://claude.ai/code/artifact/efe49cff-4c52-4f7f-9eb9-180920121aa6. This file is how to pick the work up.

## Where it stands

All runs are done and hand-graded. Llama 3.1 8B, one run per arm unless noted; Haiku 3 runs.

| Setup | Single-paper (154), right | Cross-paper (33), right |
|---|---|---|
| ugrc + Jev, short prompt | 34 | 4 |
| PDF / BM25-picked papers pasted into the prompt | 107 | 10 |
| **hybrid** | **119** | **24, 20, 21** (three runs) |
| clause base in the prompt, one free reply: with / without Jev's readings | 117 / 122 | — |
| condensed clause base, 140 corpus questions: 1 / 3 / 10-paper library (PDF text: 103 / 88 / 74) | 109 / 102 / 95 | — |
| 40-paper library, 140 corpus questions: BM25-picked PDF pages / picked condensed pages / condensed all | 103 / 84 / 67 | — |

The hybrid (`experiments/bench-cross/hybrid.py`) is an experiment script, not a ugrc mode:
- **Pages:** code picks pages (Jev's lead pages first, then BM25, up to 24k tokens; a paper that fits goes whole).
  They are rendered from ugrc's atoms, with tables row by row and figure facts as text.
- **Answer:** Llama answers in one free reply.
- **Pointers:** code points every number at the atom that prints it. No door, nothing refused.

**Jev's page picking is settled: no gain.** A frozen, blind-graded test (`bench-cross/jev-pick/`, 2026-10-22) ran the
single-paper questions over the 10-paper corpus, on the 114 where leads and BM25 pick different pages, 3 runs each:
245 vs 249 of 342 right (p = 0.76; 95% interval −6.8 to +4.5 points). Stage 2 (leads without Jev's readings) was not
run, as the plan required. One run moves by up to 4 of 33, so single-run gaps are noisy.

**Jev's readings don't help Llama reason either.** `experiments/clause-reasoning/` (2026-10-22, frozen, blind): the
whole clause base plus tables and figure facts, one free reply, no tools. 117 of 154 with Jev's marks and readings, 122
with the bare sentences (p = 0.47). Removing the protocol is what took ugrc + Jev from 34 to ~120.

**Jev as a checker works, partly.** `experiments/jev-check/check.py` (built on the 308 clause-reasoning answers, frozen,
run once on 838 hybrid answers): code finds where the paper prints each number, Jev judges the binding, code redoes the
arithmetic. Delivering passed and no-number answers: 85% right, 8% wrong, against 73% and 19% for all; 27% of right
answers held back. It misses true facts that don't answer the question (superlatives, false absences, premises).

**A condensed clause base beats PDF text as the library grows.** `experiments/scaling/` (2026-10-22, frozen, blind,
980 answers, about $1):
- **Setup:** 140 corpus questions, libraries of 1, 3 and 10 papers.
- **Condensed form:** the clause-base sentences that print a non-identifier value, plus tables row by row and figure
  facts; about 3k tokens a paper.
- **Right answers:** condensed 109/102/95 against PDF text 103/88/74; text at 10 papers holds only 7 to 9 papers in
  120k tokens. p = 0.006 at 10 papers.
- **Post hoc:** tables explain part of the gap (table questions 16/13/13 against 7/6/3). On prose alone, text leads
  with one paper (96 against 93) and trails from 3 papers on.
- **Jev's readings alone:** 24 of 140.
- **Against picking pages:** the hybrid's BM25 pages still beat the condensed form at 10 papers (about 83 against 76
  on 114, an earlier test graded separately).

**Jev's label filter is what makes the condensed form work.** `experiments/scaling-nojev/` (2026-10-22, frozen, blind,
10-paper library, 140 questions):
- **With Jev's filter:** 95 right (32k tokens).
- **Without Jev:** 83 right (43k tokens). These are ugrc's sentences with any value, plus the same tables.
- **Without ugrc:** 79 right (69k tokens). These are the pdftotext sentences with a digit.
- **Significance:** the filter is worth +12 (p = 0.017). ugrc's code alone is not reliably better than the regex
  (p = 0.58).
- **Post hoc:** most of the gap is on the table questions (13 against 8), even though both forms carry the same tables.
- **Untested:** whether a random drop of as many sentences would do as well.

**At 40 papers, picking PDF pages beats condensing.** `experiments/scaling-more/` (2026-10-22, frozen, blind):
- **Setup:** 30 arXiv battery papers added as unasked papers, giving libraries of 20 and 40 papers.
- **Condensing everything degrades:** 95 right at 10 papers, 84 at 20, 67 at 40 (where only 29–33 of the 40 papers fit
  in 120k tokens).
- **Picking pages:** BM25 over all 40 papers' pages, with the paper's title in the query, up to 24k tokens.
  - PDF pages, rendered as in the hybrid: **103** right, as many as the paper's own text alone.
  - Condensed pages: 84 (p = 0.003 for the difference).
- **Lesson:** prompt length drives Llama 8B. The condensed form won at 10 papers only by being short, so pick pages
  rather than condense.
- **arXiv set:** PDFs are in `~/Desktop/papers-arxiv/`, ingested with clause bases in `runs/arxiv/<id>`.
- **Ingest bug:** 2 of 34 arXiv PDFs crash ingest: a figure box of zero size fails at `ugrc/extract.py:529`
  (`cannot write empty image`). The fix is to skip empty boxes; not done.

**On 6 held-out papers the hybrid ties the pasted PDF.** `experiments/new6/` (2026-10-30, frozen, blind, 3 runs):
- **Setup:** 6 new PDFs (`~/Desktop/papers-new6/`, `runs/new6/<key>`), 54 questions hashed before any run.
- **Right answers:** hybrid 110, PDF pasted 111 of 162 (p = 1.0). It wins only on long papers (ATLAS 19 vs 14).
- **Hybrid flaw:** 7 answers credit a right value to the wrong table, all the hybrid's, mostly where the extractor missed
  tables (teak Tables 1 and 3). Jev as checker: 23% wrong → 17% passed, 35 of 110 right held back.

**On 9 ChemE papers, hybrid, condensed facts and pasted PDF tie.** `experiments/cheme/` (2026-10-30, frozen, blind):
- **Setup:** extractor v5 frozen (`extract.sha256`); 9 ACS Omega / RSC Adv 2026 papers picked by rule (`fetch.py`,
  `~/Desktop/papers-cheme/`, `runs/cheme/<key>`); new6 re-ingested with v5 (`runs/new6-v5/<key>`); 94 + 54 questions.
- **Right of 444 (148 questions × 3 runs):** hybrid 286, facts 297, pdf 294; no pair differs (p ≥ 0.55).
- **Split:** the hybrid leads on tables + computation, trails on plain lookups, mostly through made-up table labels
  (32 `[label]` wrongs against 8 facts, 1 pdf). Facts leads on false premises, trails on chained lookups.
- **Extractor v5:** finds only 12 of the 50 tables the 9 papers print; on new6 the hybrid scores 110 with v5 as with v4.
- **Run:** `run.sh` (all arms, ~19 min, about $1 of Modal); `grade.py sheet|record|progress|unseal|report`;
  rules 19-23 in `cheme/GRADING.md`; `check.py run|report` (Jev checker).

**Facts + prose beats them all on the same 148 questions (not held out).** `experiments/prose/` (2026-10-30, frozen,
blind against facts): facts form + up to 30 number-free sentences (5,000 chars) picked by BM25 on the question.
- **Right of 444:** 330 against facts 298 (p = 0.018); pdf 294 and hybrid 286 from their ChemE grades. Gains on chained
  and lookup questions, loses 9 on computation. About 8k tokens a prompt against the PDF's 17k.
- **Caveat:** designed after reading these questions' losses; held out in `cheme2` below.
- **Run:** `run.sh`, `run.py check|sizes|show`; `grade.py` (6 letters a question); rules 24-25 in `prose/GRADING.md`.

**Held out, facts + prose wins bigger.** `experiments/cheme2/` (2026-10-30, frozen, blind, 9 letters a question):
19 new ACS Omega / RSC Adv papers by `fetch.py` (`~/Desktop/papers-cheme2/`, `runs/cheme2/<key>`), 152 new questions.
- **Right of 456:** prose 340, facts 288, pdf 273; prose beats both at p < 0.0001; facts vs pdf p = 0.33.
- **Where:** tables +29 over facts. In 12 of 37 table questions the facts form never prints "Table N" (16 facts
  `[label]` wrongs); BM25 pulls in a sentence citing it. Without table questions prose still leads (p = 0.003, 0.013).
- **Run:** `prepare.sh`, `run.sh`, `run.py check|sizes`; `grade.py`; rules 26-29 in `cheme2/GRADING.md`.

**The library test.** `experiments/library/` (2026-10-31, frozen, blind; `PLAN.md`). The question names no paper; the
model gets a 10-paper library and must find the right one. 28 papers (cheme + cheme2), 246 questions reworded without
table numbers, 3 libraries. Right of 246: prose 132, pages 128, facts 113 (prose - pages p = 0.71, prose - facts p =
0.03); pages' prompt is 22k tokens against 61k. Wrong-paper answers 5 of 738; BM25 ranks the right paper first for 244
of 246 (offline). With one paper in view the same questions got prose 181, facts 156, PDF 152, so the cost is the long
prompt, not finding the paper. Results are in the methodology doc.

**Search picks the paper, then one paper.** `experiments/routed/` (2026-10-31, frozen, blind between its 2 arms;
`PLAN.md`): BM25 over the library's pages picks the paper of the top page (244 of 246 right), then the one-paper
prompts. Right of 246: facts+prose 184 (one-paper reference 181), pasted PDF 145; +52 over the library's prose (p <
0.0001) at 7.2k tokens instead of 61k. This is the pipeline to build: route, then the one paper's facts+prose form.
Untested: libraries of close topics, where routing misses more.

## Constraints from the user

- **Don't run anything against Haiku** (too costly at this scale). Jev can be used freely.
- **Modal credit:** about $3.20 of the $30 monthly free credit left on 2026-10-30 (after cheme2) (`modal billing summary`). An L40S
  costs about $2 an hour; 684 hybrid answers cost $1.25.
- **Never print keys:** `~/.jev_key`, `~/.ugrc_vllm_key`, `~/.modal.toml`, env vars `API_KEY` and `OPENROUTER_API_KEY`.
- **Keep this file short.** Results go in the methodology doc (Claude Docs connector, doc id above).

## Repo state

- **Committed and pushed through `9f01ce0`** (the library test); `experiments/routed/` is uncommitted.
- **ugrc code touched:**
  - `ugrc/llm.py`: the OpenAI-compatible path, retries, host pinning, `one_call_per_turn`.
  - `ugrc/ask.py`: `SYSTEM_SMALL` / `prompt="small"`, and `_small_corpus`, its corpus form.
  - `ugrc/lineage.py`: `explore` describes tables by `PRAGMA table_info`.
- **Tests:** 231, all passing (`.venv/bin/python -m pytest -q`, ~2 min, no model calls).
- **README:** section 11 covers the open-model path; section 12 has a short summary of these results.

## Files (under `experiments/`)

- `bench-llama/run.py`: ugrc arms (`llama-plain`, `llama-leads`, `-sp` = short prompt, `llama-corpus-leads-sp` = the
  10-paper corpus).
- `bench-llama/direct.py`: the PDF's text pasted (`--context N` buries it among other papers; text cached in
  `direct-text/`).
- `bench-cross/probes.json`: 33 cross-paper questions, frozen (`frozen.sha256`).
- `bench-cross/run.py`: corpus ugrc arms and `llama-direct-fill`.
- `bench-cross/hybrid.py cross|bench [--pick bm25] [--runs 1,2,3] [--papers a,b]`; `run-pick.sh` reruns the
  leads-vs-BM25 test. `hybrid.py corpus --stage N --ways ...` runs the jev-pick plan's frozen questions.
- `bench-cross/retrieval.py`: which pages each way of picking hands the model, at several budgets (no model).
- `scaling-more/`: `fetch.py` (the arXiv selection, `fetched.json`), `prepare.sh ID...` (ingest + clauses),
  `run.py libraries|show ARM KEY|answer`, `run.sh`, frozen `PLAN.md` + `papers.json` + `libraries.json` + `run.py`,
  `grade.py` (blind, 4 arms).
- `scaling-nojev/`: `forms.py PAPER code|pdf` (prints a form), `run.py`, `run.sh`, frozen `PLAN.md`, `grade.py`
  (3 arms; its `unseal` writes only the two new arms, the facts regrades stay in its `grades.json`).
- `scaling/`: `run.py libraries|show PAPER FORM|answer [--arms ...]`, `run.sh`, frozen `PLAN.md` + `questions.json` +
  `libraries.json`, `grade.py sheet|record|progress|unseal|report` (blind, 7 arms), `GRADING.md` (rules 9-12).
- `clause-reasoning/`: `run.py --ways clauses,text` (arms `llama-clauses`, `llama-clauses-text`; `--show PAPER` prints
  both renderings), `run.sh`, frozen `PLAN.md`, `grade.py` (jev-pick's `blind.py` pointed at this directory).
- `bench-cross/jev-pick/`: the frozen plan (`PLAN.md`, `questions.json`, `frozen.sha256`), `run.sh`, blind grading
  (`blind.py sheet|record|unseal|report`, `grades.json` sealed in `graded.sha256`) and its rules (`GRADING.md`).
- **Grading:** `bench-llama/grade.py report|sheet|modes`; `bench-cross/grade.py report|sheet [ARM]|pick|pick-sheet`.
  Hand grades in each `hand.json` override the automatic check. The check is not trusted for Llama: read every answer.
- **Answers:** `<bench>/answers/<arm>-r<k>/…`. A record that exists is skipped, so delete bad records before
  rerunning.
- **Kept apart, not in any table:** `answers-crashed-describe/` (pre-fix crashes) and `answers-smoke-openrouter/`.
  `*.log`/`*.out` are run logs.
- **Corpus:** `runs/papers-corpus` (10 battery papers; cai2026 is not in it). `runs/papers-corpus-plain` has no
  clause base (it is symlinks).

## How to run

- **Server:** `bench-llama/modal_vllm.py` (vLLM 0.21.0, bf16, one L40S, 131k context, scales to zero after 10 idle min).
  - `ARMS=a,b ./experiments/bench-llama/run-modal.sh [RUNS] [WORKERS] [run.py flags]` wakes it, runs and reports.
  - The `bench-cross/*.sh` scripts do the same for their arms.
  - By hand: `LLAMA_URL=<endpoint>/v1 LLAMA_KEY="$(cat ~/.ugrc_vllm_key)"`.
  - Stop: `.venv/bin/modal app stop ugrc-llama`.
- **Cold start** is about 4 min. Modal sometimes moves the container mid-run (503 "no upstreams available", a hung
  request): kill the run by PID and resume with `UGRC_LLM_TIMEOUT_S=900` (300 is too short).
- **Watch for stalls:** with a dead container each request hangs 900 s for each of its 7 tries, so a run can sit idle
  for ~105 min (it did on 2026-10-21). Alert on a log that stops growing for 8 min, then kill and resume.
- Don't watch runs with `pgrep -f`/`pkill -f`: they match the watcher's own command line.

## Grading rules in use

- **Verdicts:**
  - **correct**;
  - **partial**: nothing false, but an asked part is missing, or the answer only prints a table row without
    stating it;
  - **wrong**: anything false. That includes a wrong value, binding or paper attribution, an accepted premise, a
    false "not in the paper" (even "not in the provided text"), and a right value with a false side claim.
- A computed value within 0.5% of the key counts as right.
- Notes end "(Claude, 2026-10-21)"; a new grader should sign their own.
- Rules added in the jev-pick test (`bench-cross/jev-pick/GRADING.md`): a made-up table or figure given as where a
  value comes from is wrong (notes start `[label]`); a computation in place of the paper's own figure is partial.
- In ctx32k/64k only answers whose check changed against the paper-alone run were read; the rest carry that grade
  (`"carried": true`).

## Open threads (in the order I would take them)

1. **Facts form: print each table's caption ("Table 6. ...") with its rows** (`scaling.condensed` /
   `_tables_and_figures`), then rerun facts and prose on cheme2's 152 questions (answers exist; regrade blind).
   Also test table questions that do not name the table. Then make facts + prose a ugrc mode.
2. **Make routing + facts+prose a ugrc mode** (the pipeline to build on, `experiments/routed/`: BM25 over every page
   picks the paper, then that paper's facts+prose form, a free answer, then the Jev checker). First test routing where
   it is hard: done on 120 papers (`experiments/big-library/`): search-then-one-paper 304 of 388, as the right paper
   handed over; sending the top 2 papers is worse (242), even only when search is unsure (`gated.py`). Short
   questions without subject words (`experiments/short-route/`, search only): right paper 360 of 388 instead of
   381; answered (`answer.py`, `grade.py`): 287 right against 303 (p = 0.02), all of it routing (the short form on
   its own paper: 301). Asking the user to pick between the top 2 titles when the score gap is small (0.85, 1
   question in 7) would give 299 (post hoc). Unseen papers (`experiments/fresh/`): 10 added to the 120, search
   found all 80 questions' paper, 63 right against the PDF's 50. Next: build that ask step into the routed mode.
3. **Extend the checker** (`jev-check/`; `check.py dev|test`, `report SET`; Jev answers cached in `jev_cache.jsonl`,
   whose last line can be cut short if a run is killed). It misses superlatives (recompute over the table column by
   code) and false absences (search the paper); its Jev question false-alarms on 27% of right answers. Changes need a
   new held-out set: `test` has been used.
4. **Computing without SQL** (discussed 2026-10-21): code re-checks the arithmetic an answer writes out (in the
   jev-pick answers, 5 of 6 answers to aenm-2022-X2 multiplied 7 × 0.7 × 0.4 wrong); counts (K, wrong in 17 of 18 runs)
   from a menu of code-run operations that the model or Jev picks from.
5. **Page picking at scale:** test questions that need several papers at once on the 40-paper library (the 33
   cross-paper questions only cover the 10 corpus papers); chained lookups and false premises trail the pasted PDF.
6. **Door v7 candidates:**
   - refuse absence terms of 4+ words (no Haiku answer uses one);
   - the cai2026-T1 hole: two `submit_answer` calls in one turn, and a bare "placeholder" was accepted.
7. **Parked:** Laya (2 of 12 papers rebuilt, `experiments/laya-bench`); the laptop setup (abandoned, see memory).
