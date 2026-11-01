# Conclusion: what we tried, and what works for a small model over many papers

Written 2026-11-01. It covers every experiment in `experiments/`, from mid-October to 2026-11-01. Numbers come from
each folder's write-up and from the methodology doc
(https://claude.ai/code/artifact/efe49cff-4c52-4f7f-9eb9-180920121aa6). Most tests wrote their questions before any answer,
and the later ones froze them by hash. From `jev-pick` (2026-10-22) on, answers were also graded blind to which setup made them.

## In short

| situation | what works best | against the whole PDF |
|---|---|---|
| strong model (Claude), 1–10 papers | the whole PDF, or ugrc | equal accuracy (Opus: 71 vs 69 of 71). ugrc's gain is safety: Haiku's ugrc answers were never wrong (0 vs 2) |
| 8B model (Llama 3.1 8B), one paper | **facts+prose**: Jev's clause base condensed, plus the ~30 sentences that best match the question | **better**: 340 vs 273 of 456 on 19 new papers, at 7.4k tokens against 17.9k |
| 8B model, a library | **search picks one paper, then facts+prose** | whole PDFs don't fit (10 papers are 155k–194k tokens; Llama's window is 131k). Scores as if handed the right paper: 304 vs 304 of 388 on 120 papers |
| 8B model, a fresh paper added to a 120-paper library | **the same: add it (about a minute), then search, then facts+prose** | **better**: 63 vs 50 of 80 on 10 unseen papers (p = 0.007), at 6.7k tokens against 20.6k; search found the new paper for 80 of 80 questions |
| 8B model, 130 papers, against standard RAG | **search, then facts+prose** | **better**: 119 vs 101 of 160 (p = 0.005); standard RAG over all papers 84, the right paper's best chunks 96 (`benchmark`) |
| 8B model, a 16-question conversation on one paper | **facts+prose alone: 14.3 of 16;** in the conversation 12.3, the whole PDF 13.0 | about equal in a conversation; every retrieving setup lost answers to vague follow-ups and to facts sent many turns back (`benchmark`) |

## 1. The pieces, in plain words

- **Atoms.** ugrc reads a PDF with no model into atoms: every line, table cell and figure, with an id, a page and a
  box.
- **The door.** ugrc's original answer protocol. The model writes pointers (an atom id, a quote, a SQL query), never
  a number. A checker with no model copies the text, and refuses anything that does not resolve.
- **Jev.** A judge that cannot write. It only picks among options that code offers, with a probability.
- **Clause base.** Jev's one-time reading of a paper (section 2).
- **Leads.** The clause-base sentences that best match a question, handed to the model with it.
- **Pairing gate.** When an answer says a value is "of" something, Jev is asked yes or no.
- **Hybrid.** Code picks pages and renders them from atoms (tables row by row). The model answers freely, and code
  attaches a pointer to each number.
- **Facts.** A condensed paper: the clause-base sentences that hold a quantity, then the tables row by row and the
  figure facts.
- **Facts+prose.** Facts, plus up to 30 of the paper's other sentences that best match the question.
- **Routing.** BM25 keyword search over every page of every paper picks the paper.
- **Checker.** After the answer, code finds where each number is printed, and Jev judges whether the number is bound
  to the right thing.
- **Whole PDF.** For Claude, the PDF file itself (text and images). For Llama, its pdftotext, pasted into the prompt.

## 2. The Jev clause base

### What it is

The clause base is read once per paper, before any question. For every value in the paper's prose, it records:
- its role: result, setting, count, background, or identifier (a label such as a page number or "NMC 811");
- what kind of property it is;
- what it is about;
- how it was measured;
- what quantity it is.

It reads prose only, not table cells. Tables reach the model from ugrc's atoms instead.

### How it is built

| step | who |
|---|---|
| cut sentences; drop headers, footers and the reference list; find every value, unit and range | code |
| propose the spans each value could be about: named terms, nearby phrases, the paper's own definitions | code |
| settle what layout decides ("X of VALUE", "KEY = VALUE", "respectively" lists) | code |
| decide the rest: role, property, quantity, which candidate is the subject and which the method; each sentence's modality and polarity | Jev |
| flag conflicts (hedge words against modality, one subject with two values), never correct them | code |

Every Jev request and reply is stored and sealed, so the base can be rebuilt with no call. A paper takes 300 to 1,250
calls, about 2 minutes per 300, and about $0.02.

### How accurate it is

| test (`experiments/…`) | result |
|---|---|
| `jev-clauses-paper2`: paper 2, 79 quantities (used for development) | every slot right 57 of 79; role 93 of 95; subject 65 of 79 |
| `jev-questions`: paper 3, 84 quantities, held out | every slot right: 25 (v5) → 55 (v6, frozen first) → 63 (v7, fixed after) |
| `jev-bench`: 5 held-out battery papers, 35 quantities | every slot right 19 of 35 (v8); wrong bindings 11 → 7 |
| all 20,025 decisions behind the 11 bench papers, asked again live | 98.6% the same; every flip was a near tie |
| `laya-bench`: stock Laya in Jev's place | 46% the same decisions as Jev; pairing gate AUROC 0.59 against Jev's 0.95 |

### Every role it played

| role | test | result | verdict |
|---|---|---|---|
| answer by SQL over its rows | `jev-clauses-paper2` | hand-written SQL answered 10 of 12 probes | works, but turning a question into SQL was never built |
| leads, measure runs and pairing gate in the door, Haiku | `leads`, `bench-leads`, `bench-multistep`, `bench-llama` | 55 vs 58 of 71 (one run); 261 vs 258 of 264; 188 vs 195 of 198; 154 questions p = 0.69 | no gain for a strong model; the gate caught 6 real binding errors |
| leads in the door, Llama 8B | `bench-llama` | 34 vs 7 of 154 without (p < 0.001) | helps, but far below the PDF (107) |
| whole clause base in the prompt, free answer | `clause-reasoning` | 117 with Jev's readings, 122 without, of 154 (PDF 107) | its sentences help; the readings add nothing |
| Jev's readings alone, no sentences | `scaling` | 24 of 140 | no |
| leads pick the hybrid's pages | `bench-cross/jev-pick` | 245 vs 249 of 342 for BM25 alone | no |
| quantity-or-label filter, which builds the facts form | `scaling-nojev` | 95 with Jev, 83 without, 79 with no ugrc at all, of 140 | **yes, +12 (p = 0.017)** |
| facts form as the paper | `scaling`, `cheme`, `cheme2` | 10 papers: 95 vs PDF 74 of 140; one paper: 297 vs 294 of 444, 288 vs 273 of 456 | beats the PDF when papers share a prompt; ties with one paper |
| facts plus matching sentences | `prose`, `cheme2` | 330 vs PDF 294 of 444; **340 vs PDF 273 of 456** | **the best single-paper form** |
| checker after the answer | `jev-check`, `new6`, `cheme` | wrong answers delivered: 19% → 8% (bench), 23% → 17% (new6), about 30% → 15–18% (cheme) | useful, but holds back 22–32% of right answers |

**Where it fits in the winner.** The winning prompt is built from the clause base's sentences. Jev's one decision
per value, quantity or label, chooses which sentences go in the facts part. The sentences without a value form the
pool the "prose" part is picked from. Jev's readings (role, subject, method) are never shown to the model.

## 3. Everything we tried

### A. Claude through ugrc's door (strong models)

| test | what | model | questions | result |
|---|---|---|---|---|
| paper 1 (README §12) | 27-page review with tables, door v1 → v2 | Opus | 6 | 6 right; $0.54 |
| paper 2 (README §12) | research article with data figures | Opus | 7 | 7 right; $0.46 |
| `hallucination-paper2` | false premises, absences, binding traps, a planted wrong figure reading | Opus | 48 | 0 invented values, 0 wrong pairings, 0 of 12 false premises accepted; 4 small flaws; $2.89 |
| `paper3` | review with three large tables | Opus | 29 | 27 right, 2 with a wrong secondary claim; $3.05 |
| `claude-capability` | what right answers owe to a strong model | Opus | 60 | 58 right, 2 format partials, 0 wrong; 44 of the 58 needed more than a lookup |
| `prof-rag` | a professor's questions over 10 papers, against his RAG system | Opus | 11 | ugrc 11 right; the RAG 7 of 8 general, 0 of 2 table, figure "reasonable" (his grading) |
| `whole-pdf` | the PDF itself in the prompt, no ugrc | Opus | 71 | PDF 71 right; ugrc 69 + 2 format partials |
| `whole-pdf` | the same, weaker model | Haiku | 71 | PDF 67 right, 2 wrong; ugrc 58 right, 13 partial, 0 wrong |
| `bench-leads` | 11 new papers, plain vs clause base, 3 runs | Haiku | 88 | 258 vs 261 of 264 (p = 0.38) |
| `bench-multistep` | multi-step questions, 3 runs | Haiku | 66 | 195 vs 188 of 198 (p = 0.22); every wrong answer was a percentage scaled twice (fixed) |
| `bench-llama`, Haiku arms | 2×2 against Llama, 3 runs | Haiku | 154 | 151–154 per run, with or without Jev (p = 0.69); $2.68 for 924 answers |

### B. Building the clause base and its judge

| test | what | result |
|---|---|---|
| `jev-clauses-paper2` | can a choose-only judge write clauses? | every slot 57 of 79; SQL over it answered 10 of 12 probes |
| `jev-questions` | better questions for Jev (v6, v7) | held out: 25 → 55 of 84 every slot right |
| `jev-bench` | 10 battery papers, v8 | held out 19 of 35; wrong bindings 11 → 7; $0.17 for all 10 papers |
| `leads` | leads, measure runs and pairing gate, Haiku, 71 questions | plain 58, clause base attached 64, leads 55 (one run each; within noise) |
| `laya-bench` | Laya in Jev's place, zero-shot | 46% agreement; the gate accepted all 5 wrong pairings; not usable without fine-tuning |

### C. Llama 3.1 8B, one paper at a time (154 bench questions)

| test | setup | right of 154 | PDF in the same test |
|---|---|---|---|
| `bench-llama` | through the door, Haiku's long prompt: with Jev / without | 13 / 5 | 107 |
| `bench-llama` | through the door, short prompt: with Jev / without | 34 / 7 | 107 |
| `bench-llama` | whole PDF pasted (~16k tokens) | 107 | — |
| `bench-cross` | hybrid | 119 | 107 |
| `clause-reasoning` | whole clause base, free answer: with readings / without | 117 / 122 | 107 (graded earlier, not blind to these) |
| `jev-check` | Jev checker on 838 hybrid answers | wrong delivered 19% → 8% | — |
| `bench-cross/jev-pick` | Jev's leads vs BM25 picking pages, 114 questions × 3 | 245 vs 249 of 342 | — |

### D. More papers in one prompt (the question names its paper)

| test | setup | result |
|---|---|---|
| `bench-llama` length test | the PDF buried among other papers, 154 questions | 107 alone → ~92 (31k tokens) → ~92 (60k) → 78 (118k) |
| `bench-llama` corpus | ugrc + Jev through the door over 10 papers, 140 questions | 33, the same as on one paper: search doesn't decay, but starts low |
| `bench-cross` | 33 questions needing 1–3 papers found first | hybrid 24, papers pasted 10, door with Jev 4, door without 1 |
| `scaling` | facts vs PDF text at 1 / 3 / 10 papers, 140 questions | facts 109 / 102 / 95; PDF text 103 / 88 / 74 (p = 0.006 at 10) |
| `scaling-nojev` | 10 papers: facts with Jev's filter / without Jev / regex on pdftotext | 95 / 83 / 79 |
| `scaling-more` | 20 and 40 papers | facts of every paper: 84 at 20, 67 at 40; at 40, BM25-picked PDF pages 103, picked facts pages 84 |

### E. New papers, held out (Llama, 3 runs each)

| test | papers, questions | result |
|---|---|---|
| `new6` | 6 mixed-field papers, 54 | hybrid 110, PDF 111 of 162 |
| `cheme` | 9 ChemE + the 6, 148; extractor v5 | hybrid 286, facts 297, PDF 294 of 444; v5 finds 12 of 50 tables |
| `prose` | the same 148 (the method was designed on them) | facts+prose 330, facts 298 of 444 |
| `cheme2` | 19 new ChemE papers, 152 | **facts+prose 340**, facts 288, PDF 273 of 456 (p < 0.0001) |

### F. Finding the paper (the question names no paper; Llama, one run)

| test | setup | result |
|---|---|---|
| `library` | 10-paper libraries, all 10 in the prompt, 246 questions | facts+prose 132, picked pages 128, facts 113. With only the right paper in view: 181, facts 156, PDF 152 |
| `routed` | search picks 1 paper of 10 | facts+prose 184, PDF 145 of 246 |
| `big-library` | 120 papers, 2–3 per topic, 388 questions | search picks the paper 304; right paper handed over 304; top 2 papers 242 |
| `short-route` | the same 388, cut to what a user might type | 287 against 303; own paper 301; asking when unsure about 299 (estimate) |
| `fresh` | 10 unseen papers, each added to the 120, 80 new questions | search found the paper 80 of 80; facts+prose 63, the paper's PDF 50 |

### G. Pointers for numbers on the winning setup (fresh test's 80 questions; Llama, one run)

| test | setup | result |
|---|---|---|
| `pointers` | code points each number of the free answers at a passage that prints it (468 answers) | 91% of 1,589 numbers printed in the paper, 9% derived or computed, 1% printed nowhere (9 answers: 7 wrong). The Jev binding check did not run (credits out) |
| `door-routed` | ugrc's door on the routed paper: every number must be a quote, a clause-base value or SQL | door 16, door with facts+prose and ids 21, against the free answer 61 of 80 (p < 0.0001); absence 0–1 of 10, false premise 0–1 of 10 |

### H. Against standard RAG, and in a long conversation (Llama, `benchmark`)

| test | setup | result |
|---|---|---|
| part 1: 160 questions over 130 papers, one run | search, then facts+prose; the right paper's whole text; the right paper's best 200-word chunks; standard RAG (hybrid BM25 + embedding retrieval over 7,932 chunks of all 130 papers) | **119**, 101, 96, 84. Table questions 22 / 9 / 5 / 7 of 37. Every RAG prompt held the right paper; it lost on picking the right passage |
| part 2: 16 linked questions on one paper, asked in one conversation and alone, 3 runs | the same four | alone: **ours 14.3**, pdf 12.3, chunks 12.3, rag 11.0 of 16. In the conversation: pdf 13.0, ours 12.3, chunks 10.3, rag 8.3. Over all four, the conversation cost 18 of 192 (p = 0.02) |

The conversation's losses came from three things:
- **vague follow-ups retrieving the wrong text:** "that synthesis" pulled another paper's 180 °C for 12 h;
- **facts sent on turn 1 being missed 14k tokens later;**
- **a false premise accepted mid-conversation:** 0 of 9 caught, against 9 of 9 when asked alone.

The context never ran out (at most 33k of 131k tokens), and no wrong answer carried into later turns.

Full account of what was tested: `experiments/benchmark/README.md`.

## 4. Against the whole PDF

Every Llama test that had a whole-PDF arm, beside the best other setup:

| test | papers in play | whole PDF | best other setup |
|---|---|---|---|
| `bench-llama` (154) | 1 | 107 | clause base, free answer 122; hybrid 119; door 34 |
| length test (154) | 1 among others, 118k tokens | 78 | — |
| `bench-cross` (33) | 10 | 10 | hybrid 24 |
| `scaling` (140) | 10 (only 7–9 fit) | 74 | facts 95 |
| `new6` (162) | 1 | 111 | hybrid 110 |
| `cheme` (444) | 1 | 294 | facts 297; hybrid 286 |
| `prose` (444) | 1 | 294 | facts+prose 330 |
| `cheme2` (456), held out | 1 | 273 | **facts+prose 340** |
| `library` (246) | 10 | does not fit | facts+prose 132 |
| `routed` (246) | search picks 1 of 10 | 145 | **facts+prose 184** |
| `big-library` (388) | 120 (2.06M tokens) | does not fit | **search, then facts+prose 304** |
| `fresh` (80), unseen papers | 121 (search picks 1) | 50 (the right paper's) | **search, then facts+prose 63** (p = 0.007) |
| `benchmark` (160) | 130 (search picks 1) | 101 (the right paper's) | **search, then facts+prose 119** (p = 0.005); RAG over all 130 papers 84 |

**With a strong model, the whole PDF is as good.** Opus got all 71 right from the whole PDF, against 69 through ugrc.
Haiku got more right from the whole PDF (67 vs 58), but 2 of its answers were wrong and none of ugrc's were. With
Claude, ugrc buys checked numbers, not more right answers.

**With an 8B model and one paper, each idea falls into one of three groups:**
- **Worse than the PDF:** ugrc's door protocol (34 vs 107). The model can't write pointers and SQL reliably.
- **Equal to the PDF:**
  - the hybrid: 110 vs 111 on held-out papers, 286 vs 294 on ChemE;
  - the facts form alone: 297 vs 294, and 288 vs 273 (p = 0.33), at about 40% of the length.
- **Better than the PDF:** facts+prose, +67 of 456 on held-out papers (75% right against 60%) at well under half the
  length.

**With many papers, the whole PDF stops working.** Each extra paper costs answers (107 → 78 at 118k tokens), and past
7–9 papers it doesn't fit at all. Search, then one paper's facts+prose, keeps the prompt at about 7k tokens, whatever
the library size.

**Why facts+prose beats the PDF:**
- **It is shorter.** Prompt length is the biggest lever for an 8B model.
- **Tables arrive row by row, under their caption and column names.** pdftotext writes them column by column. Table
  questions: 16 vs 7 of 18 with one paper (`scaling`); +38 table answers over the PDF on held-out papers
  (`cheme2`).
- **Jev's filter removes noise.** It drops sentences whose only numbers are labels: page numbers, addresses, DOIs,
  figure numbers.
- **The matching sentences put back what the facts form drops.** Examples are a table's number ("presented in Table
  6"), a method's name, a list of causes. On the 12 table questions whose table number the facts form lost: facts+prose 31,
  facts alone 11, of 36.
- **False premises:** +20 over the PDF on held-out papers (p = 0.003).

## 5. The recipe

**Once per paper, before any question:**
1. **Ingest (no model):** atoms in `atoms.duckdb` (extractor v5).
2. **Clause base (Jev):** sentences, values, and each value's quantity-or-label decision.
3. **Pages for search:** pdftotext of every page, headed `=== <title>, page N ===`.

**Per question:**
1. **Route** (`experiments/routed/run.py`, `route_one`): BM25 over all pages; the top page's paper wins.
2. **Build the document** (`experiments/prose/run.py`, `document`):
   - every sentence holding at least one value Jev did not call a label, in page order;
   - up to 30 of the other sentences, ranked by BM25 against the question, at most 5,000 characters, put back in
     page order;
   - each table as `Table N. <caption>`, then `Columns: a | b | c`, then one line per row;
   - figure facts as text.
3. **Prompt** (`experiments/scaling/run.py`, `SYSTEM`): "You answer questions about one document, "{title}", using
   only what that document contains. [what the document is] Answer briefly. If you compute a number, show the
   calculation. If the question assumes something the document contradicts, say so. If the document does not hold
   the answer, say so."
4. **One reply** at temperature 0.6, top_p 0.9.

`experiments/big-library/run.py` ties these together. It is experiment code, not yet a ugrc mode.

## 6. A fresh paper enters a 120-paper library

The user's case: the library already holds 120 papers and a new one arrives. Tested on 10 ChemE papers published
2025–26 that no earlier test had seen (`experiments/fresh/`, `RESULTS.md` there). Each was added alone to the 120, and
80 new questions were written for them before any answer existed.

### When the paper arrives (once, before any question)

| step | what it does | model | per paper (mean of 10) |
|---|---|---|---|
| 1. Ingest | ugrc reads the PDF into atoms: lines, tables and their cells, figures and their text (`atoms.duckdb`, extractor v5) | none | 15 s |
| 2. Clause base | Jev splits the text into sentences, finds every value, and decides for each whether it is a quantity or only a label: a sample name, a year, a reference number (`clauses.duckdb`) | Jev, ~940 calls | 49 s |
| 3. Pages for search | pdftotext of every page, each headed `=== <title>, page N ===`, added to the search index | none | under 1 s |

All 10 papers went through on the first try. Nothing about the other 120 changes: no re-ingest, no retraining, only
the new pages added to the index. The new papers did not pull old questions away. With all 10 in, 1 of the 388
earlier questions changed paper, and it moved to its own (382 right, against 381).

### When a question comes (every time)

1. **Search picks the paper.** BM25 keyword search scores every page of every paper against the question. The paper
   of the top page wins. No model. For these 80 questions it picked the new paper every time, over 121 papers and
   over all 130.
2. **That paper becomes its facts+prose form**, about a third of the paper's text:
   - every sentence holding a value Jev called a quantity, in page order;
   - up to 30 other sentences that best match the question, at most 5,000 characters;
   - each table row by row, then figure facts.
3. **Llama 3.1 8B answers** with only that paper in front of it. It is told to answer briefly, show any calculation,
   correct a false premise, and say so when the paper does not hold the answer. One reply.

### Results

| | right of 80 | prompt tokens (mean) |
|---|---|---|
| search, then facts+prose | **63** (79%) | 6,700 |
| the right paper handed over as facts+prose | 63 (search never missed) | 6,700 |
| the right paper's whole PDF text pasted | 50 (62%) | 20,600 |

- **The lead:** +13 (17 questions better, 4 worse), p = 0.007. It holds under a lenient recount: 68 vs 53 with false
  hedges, wrong table labels and one rounding slip counted right.
- **By type** (setup / PDF):

  | lookup | binding trap | table | computation | chained | false premise | absence |
  |---|---|---|---|---|---|---|
  | 12 / 11 of 12 | 10 / 8 of 10 | 13 / 9 of 18 | 5 / 3 of 10 | 5 / 5 of 10 | 8 / 5 of 10 | 10 / 9 of 10 |

- **Unseen papers did as well as the old ones:** 79% right, against 78% on the 120-paper test and 75% on cheme2. So
  the earlier numbers were not an artifact of papers and questions reused from test to test.
- **Missing tables cost little.** Ugrc's extractor found only 15 of the 48 tables these papers print, and none in 5
  papers, all ACS Omega (the library: 212 of 402). The table rows still reach the model as lines of text. On table
  questions from papers where no table was found, the setup got 6 of 9, the PDF 5 of 9.
- **What still fails** is what failed before: computation (most often "the input is not given" when it is printed)
  and chained lookups (the second link read from the wrong row).

## 7. Where it still fails

The model is now the limit, not search. On the 120-paper test, by question type:

| type | right |
|---|---|
| absence (the paper does not say) | 46 of 47 |
| lookup | 59 of 61 |
| binding trap (a value easily given for the wrong thing) | 46 of 53 |
| false premise | 45 of 55 |
| table | 64 of 91 |
| chained lookup | 23 of 34 |
| computation | 21 of 46 |
| figure | 0 of 1 |

The 84 answers that were not right, grouped roughly from the grade notes:
- 55 give a wrong value, take one from the wrong row, column or table, or leave part of the answer out;
- 9 say "not in the paper" when it is;
- 8 are rounding slips under a strict rule (82.1% where the key is 82.2%);
- 7 hedge ("not explicitly stated", then the value);
- 5 accept a false premise.

In `cheme2`, 17 questions got no right answer from any setup. Most involve tables that both pdftotext and the
extractor flatten: lost ± signs, blank cells that shift columns, and rows picked by a value printed elsewhere.

## 8. How far to trust this

- **One grader.** Claude wrote the questions, the answer keys and the short forms, and did all the grading. Grading
  was blind and hashed, and regrading agreed with itself (252 of 257, 162 of 162, 430 of 444, 140 of 140). That shows
  consistency, not independence. No human has checked a sample.
- **The questions are not users'.** They were written from the papers' text and lean on table lookups and
  computation.
- **Strict rules.** A wrong rounding of the answer's own inputs, and a false hedge, both count as wrong.
- **Noise.** Most later tests ran once per setup. One setup moved by up to 4 of 33 between runs. Paired tests account
  for this within a test, not across tests.
- **The papers.** Of the 55 papers asked about, 38 are 2025–26 ACS Omega / RSC Advances chemical engineering (10 of
  them unseen until the last test), 6 are from mixed fields, 10 are battery papers and 1 is an siRNA review. The
  library adds 75 more.
- **Single-paper questions only, at scale.** Questions that need two or more papers were tested only at 10 papers.
  The winning pipeline sends one paper, so it cannot answer them as it stands.
- **The answers are unchecked.** The free reply gives up ugrc's original promise that every number points into the
  paper. Putting the door back costs most right answers (21 against 61 of 80, `door-routed`). Code finds a printed
  source for 91% of the free answers' numbers, but whether each is the right one for what the answer says needs the
  Jev checker, which has not run on these answers (Jev's credits ran out).
- **Untested inside facts+prose:** whether Jev's filter still matters there (it was tested on the facts form alone),
  and whether dropping as many sentences at random would do as well.

## 9. Cost

| setup | cost |
|---|---|
| Opus through the door | $0.04–0.14 a question |
| Opus, whole PDF (cached) | $4.93 for 71 questions |
| Haiku through the door | $2.68 for 924 answers |
| Llama 8B on Modal (L40S, about $2 an hour) | 783 answers in 21 minutes, about $0.40 |
| Jev clause base | about $0.02 a paper, once (~940 Jev calls, 49 s) |
| Adding a paper to the library | about a minute: 15 s ingest, 49 s clause base, under 1 s indexing |

## 10. Next

1. **Validate before tuning more.** Collect 20–30 questions written the way the user would ask them, and have a
   person spot-check about 30 grades.
2. **Build it into ugrc as a mode:** route, then facts+prose, then one answer, then code pointers and the Jev checker,
   with the ask step when search is unsure. Not the door: through it Llama 8B kept 21 of 61 right answers.
3. **Fix the conversation case** (`benchmark`). Each turn, re-send the facts rows that match the new question, and
   route and retrieve on a stand-alone rewrite of the follow-up. Then rerun part 2 with a second paper.
4. **Attack the model's limit:**
   - let code do the arithmetic;
   - fix the table cases above (± signs, blank cells, ACS Omega layout);
   - or try a stronger open model on the same frozen questions.
5. **Questions across papers** at library scale.
6. **Fine-tune Laya** on Jev's recorded decisions, then compare it with Jev again.
