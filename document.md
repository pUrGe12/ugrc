# The best procedure: a small model answering questions over a large library of papers

Written 2026-11-01. This is the setup that won every test so far with Llama 3.1 8B, described end to end: what
happens when a paper is added, what happens when a question comes in, and the numbers behind each step. How it was
found, and everything that lost, is in `conclusion.md`. The method and each test's details are in the methodology doc
(https://claude.ai/code/artifact/efe49cff-4c52-4f7f-9eb9-180920121aa6).

## In one paragraph

Each paper is read once when it enters the library: ugrc turns the PDF into atoms (no model), Jev reads every value
in its prose and decides whether it is a real quantity or only a label (about 940 calls, under a minute), and the
paper's pages go into a keyword search index. When a question comes, keyword search over every page of every paper
picks one paper (22 ms over 130 papers). That paper is condensed into its **facts+prose** form: the sentences that
state a quantity, up to 30 other sentences that best match the question, and its tables row by row (about 6,700
tokens, a third of the paper's text). Llama 3.1 8B answers from that alone, in one reply. On 10 papers it had never
seen, added to a 120-paper library, it got 63 of 80 questions right, against 50 when handed the right paper's whole
PDF text.

## 1. What it runs on

| piece | what | where |
|---|---|---|
| ugrc | PDF to atoms (lines, tables, cells, figures), no model; extractor v5, frozen by hash | `ugrc/extract.py`, `python -m ugrc ingest` |
| pdftotext | the plain text of each page, for search | poppler-utils |
| Jev | a judge that only picks among options code gives it, with a probability; it cannot write | hosted, `JEV_API_KEY` |
| Llama 3.1 8B Instruct | the answering model, bf16 | our own vLLM server on Modal, one L40S (`experiments/bench-llama/modal_vllm.py`) |
| DuckDB | each paper's stores: `atoms.duckdb` and `clauses.duckdb` | `runs/<set>/<paper>/` |

## 2. When a paper enters the library

Nothing about the papers already in the library changes: no re-ingest, no retraining. The new pages are added to the
search index.

| step | what it does | model | time (mean of 10 new papers) | produces |
|---|---|---|---|---|
| 1. Ingest | reads the PDF into atoms: every line with its page and box, tables and their cells, figures and any text or values read from them | none | 15 s | `atoms.duckdb` (~5 MB), `figures/` (~1.4 MB) |
| 2. Clause base | cuts the prose into sentences (dropping headers, footers and references), finds every value and unit, then asks Jev, for each value, whether it is a quantity (result, setting, count, background) or only an identifier (a sample name, a year, "NMC 811", a reference number), and what it is about | Jev, ~940 calls (628–1,144) | 49 s with 8 workers | `clauses.duckdb` (~6 MB): sentences, values, Jev's decisions, every Jev request and reply sealed |
| 3. Search pages | pdftotext of every page, headed `=== <title>, page N ===`, added to the BM25 index | none | under 1 s | the index (all 130 papers rebuild in 0.3 s) |

Command for steps 1 and 2 (skips any step already done):

```
JEV_API_KEY=... ./experiments/big-library/prepare.sh SET KEY [KEY ...]     # ~/Desktop/papers-SET/KEY.pdf -> runs/SET/KEY
```

**What the 10 new papers gave** (`experiments/fresh/intake.json`):

| per paper | mean | range |
|---|---|---|
| pages | 16 | 10–24 |
| ingest + clause base | 64 s | 43–83 s |
| Jev calls | 939 | 628–1,144 |
| values found | 310 | 196–434 |
| of them labels, left out of the facts | 103 (33%) | 67–168 |
| sentences | 327 | 207–519 |
| paper text (pdftotext) | 20,500 tokens | 11,600–31,000 |
| facts form (before the prose sentences) | 5,300 tokens | 3,300–7,800 |
| Jev cost | about $0.02 | |

All 10 went through on the first try. Adding them did not disturb the library: of the 388 earlier questions, 1
changed paper, and it moved to its own (382 right against 381).

**One known gap:** the extractor finds about half the tables papers print (212 of 402 in the library, 15 of 48 in
the new papers; none in some ACS Omega layouts). A table it misses still reaches the model, as the pdftotext lines
inside the prose, just not row by row under its caption. It cost little in the last test (table questions from
papers with no table found: 6 of 9 right, against 5 of 9 from the whole PDF).

## 3. When a question comes in

### Step 1: search picks one paper (no model, 22 ms)

BM25 keyword search (k1 = 1.5, b = 0.75; lowercase words and numbers) scores every page of every paper against the
question. Each page carries its paper's title in its header, so title words count. The paper of the single best
page wins. Only that paper goes on.

- 120-paper library: the right paper first for 381 of 388 questions (98%).
- 10 new papers, each among the 120: 80 of 80, and 80 of 80 over all 130.
- Short questions without the subject words: 360 of 388 (93%).

Sending the top 2 papers instead is worse (242 against 304 of 388): the model mixes the papers or says "neither
holds the answer".

### Step 2: build that paper's facts+prose form (35 ms)

From the paper's clause base and atoms (`experiments/prose/run.py`, `document()`), page by page:

1. **Every sentence that holds at least one value Jev called a quantity**, in page order. Sentences whose only numbers
   are labels (page numbers, DOIs, addresses, figure numbers) are left out.
2. **Up to 30 of the other sentences**, the ones that best match the question by BM25, at most 5,000 characters,
   put back in page order. These bring back what the facts drop: a table's number, a method's name, a list of causes.
3. **Each table the extractor found**, as `Table N. <caption>`, then `Columns: a | b | c`, then one line per row.
4. **Figure facts** read from the images, marked "(Figure N, read from the image)".

### Step 3: the prompt

System:

> You answer questions about one document, "{title}", using only what that document contains. It is below,
> condensed: page by page, the sentences that state a value, with the few other sentences that best match the
> question (the rest are left out), then its tables row by row and facts read from its figures. Answer briefly. If
> you compute a number, show the calculation. If the question assumes something the document contradicts, say so. If
> the document does not hold the answer, say so.

User:

```
<document title="{title}">
=== page 1 ===
- {sentence}
- {sentence}
...
Table 1. {caption}
Columns: {a} | {b} | {c}
{row}
...
</document>

Question (about "{title}"): {question}
```

### Step 4: one answer

Llama 3.1 8B Instruct, temperature 0.6, top_p 0.9, at most 4,096 output tokens, one reply, no tools. The answer goes
back as written.

## 4. Sizes and times

| prompt | tokens |
|---|---|
| **facts+prose, one paper (the procedure)** | **6,700 mean** (new papers; median 6,800, 4,200–10,000); 7,100 on the 120-paper test (one table-heavy paper reaches 36,000) |
| the same paper's whole PDF text | 20,600 mean (12,900–34,900) |
| the facts form alone | 5,300 mean |
| search's top 2 papers, facts+prose | 13,100 mean |
| 10 papers' whole text | 155,000–194,000 (more than Llama's 131,000 window) |
| the whole library, 130 papers, 2,123 pages | 2.27 million |

| step | time |
|---|---|
| adding a paper | about 64 s (15 s ingest, 49 s clause base) |
| routing a question over 130 papers | 22 ms |
| building the facts+prose prompt | 35 ms |
| Llama's answer | median 6 s with 8 at a time; answers are short (median 58 tokens) |
| the Modal server waking from cold | under 3 min (2 min 42 s in the last run) |
| 160 answers / 783 answers | under 4 min / 21 min |

| cost | |
|---|---|
| Jev, per paper added | about $0.02, once |
| Llama on Modal (L40S, about $2 an hour while awake) | 783 answers for about $0.40, about $0.0005 an answer |

## 5. How well it works

All Llama 3.1 8B, graded blind to which setup wrote each answer, on questions written and frozen before any answer.

| test | what | the procedure | comparison |
|---|---|---|---|
| `benchmark` | 130 papers; the fresh test's 80 questions and 80 drawn from the 388 | **119 of 160 (74%)** | right paper's whole PDF 101 (p = 0.005); standard RAG over all 130 papers 84; right paper's best chunks 96 |
| `fresh` | 10 papers no test had seen, each added to the 120; 80 new questions | **63 of 80 (79%)** | right paper's whole PDF 50 (p = 0.007); right paper's facts+prose 63 |
| `big-library` | 120 papers, 2–3 per ChemE topic plus other fields; 388 questions | **304 of 388 (78%)** | right paper handed over 304; top 2 papers 242 |
| `short-route` | the same 388 cut to what a user might type | 287 of 388 | the long questions 303; asking the user when search is unsure 299 (estimate) |
| `routed` | 10-paper libraries, 246 questions | 184 of 246 | right paper's whole PDF 145 |
| `cheme2` | 19 new ChemE papers, one paper in view, 3 runs | 340 of 456 (75%) | whole PDF 273 (p < 0.0001), facts alone 288 |

By question type on the new papers (procedure / whole PDF): lookup 12 / 11 of 12, binding trap 10 / 8 of 10, table
13 / 9 of 18, computation 5 / 3 of 10, chained lookup 5 / 5 of 10, false premise 8 / 5 of 10, absence 10 / 9 of 10.

## 6. Why each piece is there

| piece | what removing or replacing it cost | test |
|---|---|---|
| one paper instead of many | 10 papers in one prompt: 132 of 246 against 184 routed | `library`, `routed` |
| keyword search to pick it | scores as if handed the right paper (304 vs 304) | `big-library` |
| one paper, not the top 2 | top 2: 242 against 304 | `big-library` |
| condensed instead of the whole text | whole PDF text: 273 against 340 of 456; 50 against 63 of 80 | `cheme2`, `fresh` |
| Jev's quantity-or-label filter | without it: 83 against 95 of 140 (p = 0.017) | `scaling-nojev` |
| the 30 matching sentences | facts alone: 288 against 340 of 456 | `cheme2` |
| tables row by row | table questions: 16 vs 7 of 18 against pdftotext | `scaling` |
| a free answer, not ugrc's pointer protocol | the door: 34 of 154 against 107 for the whole PDF | `bench-llama` |

## 7. Where it fails

- **Computation** (5 of 10 on the new papers, 21 of 46 on the 120): most often the model says a printed input is
  not there.
- **Chained lookups** (5 of 10; 23 of 34): the second value read from the wrong row.
- **Tables** the extractor flattens or misses: lost ± signs, blank cells that shift columns.
- **A wrong paper is never recovered:** of 18 misrouted questions that had an answer, Llama got 0 right.
- **Questions that need two papers** are not handled: only one paper is sent.
- **Long conversations** (`benchmark`, part 2): asked alone, 14.3 of 16 questions on one paper were right; asked as one
  16-turn conversation, 12.3, against 13.0 for the whole PDF.
  - Follow-ups like "that synthesis" route and retrieve poorly.
  - The facts sent on turn 1 get missed many turns later.
  - The fix to test: each turn, re-send the facts the new question matches, and search on a stand-alone rewrite of
    the question.

## 8. Not in it yet

- **Pointers for numbers.** ugrc's original promise was that every number in an answer points into the paper (an
  atom, a quote, a SQL query) and code refuses anything that does not resolve. The procedure gives that up: the
  answer is free text. Two ways back were tested on it:
  - **The door itself** (`experiments/door-routed/`): Llama must deliver every number as a quote, a clause-base value
    or SQL. It got 21 of 80 right with the facts+prose form in view (16 without), against 61 for the free answer. It
    quotes some number from the paper even where the paper gives none, and it cannot compute. Not worth it for an 8B
    model.
  - **Pointers after the answer** (`experiments/pointers/`): code finds a passage printing the number for 91% of the
    numbers in 468 free answers; 9% are derived or computed; 1% are printed nowhere (9 answers, 7 of them wrong). This
    leaves the answer unchanged. The Jev checker that decides whether each pointed number is the right one for what
    the answer says (on the bench it cut wrong answers delivered from 19% to 8%, holding back 22–32% of right ones)
    did not run: Jev's credits ran out.
- **Asking the user** to pick between the top 2 titles when search is unsure (about 1 question in 7 for short
  questions; worth about 12 of the 16 answers short questions lose).
- **A ugrc mode.** It runs as experiment code (`experiments/big-library/run.py`, `experiments/fresh/run.py`), not as
  `python -m ugrc ask`.

## 9. Caveats

- One grader, Claude, who also wrote the questions and keys; blind and hashed, but no human has checked a sample.
- The questions were written from the papers and lean on lookups, tables and computation, not on users' questions.
- Mostly 2025–26 ACS Omega and RSC Advances chemical engineering papers.
- Most library tests ran once per setup; paired tests account for that within a test.

## 10. Files

| what | where |
|---|---|
| add papers | `experiments/big-library/prepare.sh` |
| routing, prompts, answering | `experiments/big-library/run.py`, `experiments/routed/run.py`, `experiments/fresh/run.py` |
| facts+prose form | `experiments/prose/run.py` (`document`), `experiments/scaling/run.py` (`condensed`, `SYSTEM`) |
| Modal server | `experiments/bench-llama/modal_vllm.py`, `experiments/fresh/run.sh` |
| results | `experiments/*/RESULTS.md` or `PLAN.md`, `conclusion.md`, the methodology doc |
