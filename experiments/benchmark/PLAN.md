# The benchmark: our system against RAG and the whole paper, one question at a time and in a long conversation

Written 2026-11-01, before any answer of this test existed, while Jev has no credits (no new clause bases, no live
judge). Every paper here already has its clause base. Llama 3.1 8B answers in every arm, on our own vLLM server on
Modal (bf16, context 131,072 tokens, temperature 0.6, top_p 0.9, at most 4,096 tokens out), as in every test since the
bench battery.

## Part 1: one question at a time, over the whole library

The library is the 130 papers of the fresh test (`../fresh/`): the big library's 120 and the 10 fresh ones, 2,123
pages with text. Every arm answers every question in one reply.

| arm | what the model gets |
|---|---|
| `ours` | keyword search (BM25 over every page, headed by the paper's title) picks one paper; that paper's facts+prose form from its Jev clause base. The winning setup, unchanged (`../fresh/run.py` arm top1) |
| `rag` | a standard RAG pipeline with no paper choice: every paper's pdftotext cut into 200-word windows (step 160, within a page; 7,932 chunks), hybrid retrieval over all of them (BM25 and `BAAI/bge-base-en-v1.5` dense scores, revision a5beb1e3 from the local cache, reciprocal-rank fusion, k = 60), the best chunks while they fit in 24,000 characters, best first, each headed by its paper's title and page. The prompt says the question is about one paper and asks the model to answer from that paper's excerpts and name it |
| `chunks` | ours' paper choice, then that paper's own chunks by the same hybrid retrieval, up to the same 24,000 characters, in page order (overlapping windows joined). This is the extra arm: it asks what the clause base adds once the paper is chosen |
| `pdf` | the question's own paper, handed over (no choice), its whole pdftotext |

The 24,000-character budget is about the mean size of ours' document on the fresh test (about 6,700 prompt tokens),
so rag and chunks see about as much text as ours. Every arm gets ours' instructions (answer briefly, show a
calculation, say so when the question assumes something the text contradicts or the text lacks the answer), worded
for what it is shown. Earlier tests' pdf arm had a shorter prompt (`../bench-llama/direct.py`) without them; here
only the content differs between arms.

**Questions (160).** All 80 of the fresh test (10 new ChemE papers, keys from pdftotext) and 80 of the big-library
test's 388, drawn per category in proportion to the 388, by a fixed seed (`run.py questions`). Wording and keys are
unchanged. Routing over all 130 papers puts 159 of the 160 on their own paper (`routes.json`).

**Measure.** Right answers per arm, graded blind (GRADING.md). Paired exact sign-flip tests on right/not right:
ours against each other arm, and chunks against rag. Also: right by category and by source; how many rag prompts held
any chunk of the question's paper, and rag's right answers with and without; prompt size.

**Expected.** From earlier tests: ours ≥ pdf (fresh test 63 vs 50 of 80; held out 340 vs 273 of 456). No earlier test
had a cross-library RAG arm; the pages arm on the 10-paper library (BM25 pages from every paper) scored 128 against
prose 132 of 246.

## Part 2: a long conversation on one paper

One paper no earlier test asked about: `cheme3/adsorption-2` (RSC Advances, biochar in MIL-100(Al)/MIL-110(Al)
hybrids for CO2 adsorption; 16 pages, about 23,400 tokens of pdftotext). Claude read its whole pdftotext and wrote 16
linked questions (`conversation.json`): the best composition and its uptake, its synthesis masses, a check of its
nominal loading, the autoclave conditions, its surface areas, a false premise on the pristine framework, external
surface shares, TPD site densities, a sum checked against a printed total, an absence (the biochar alone), isotherm
fits, a false premise on the 20% composite's fit, TGA residues, a percentage back to turn 1's uptakes, the comparison
table, and an absence (cycling). Twelve of the 16 lean on earlier turns ("that composition", "the best composition").

Each question has two forms: `chat`, asked in order in one conversation, and `solo`, spelled out and asked alone.

- **chat**: one conversation per arm, the 16 questions in order, every earlier question and answer kept in the
  context. What each turn adds:
  - `pdf`: the whole paper once, on turn 1; later turns add only the question.
  - `ours`: the routing query is every question so far. The first time a paper is routed, its facts+prose document
    for this question and the one before; later turns add only the prose sentences not yet shown, with their pages.
  - `rag`: retrieval on this question and the one before, over all 130 papers; only chunks not yet shown are added.
  - `chunks`: the same over the routed paper's chunks; only chunks not yet shown are added.
  A turn whose context no longer fits the window gets no answer (recorded, not right), and the conversation goes on
  without it.
- **solo**: each of the 16 questions alone, in the arm's part 1 form (ours, rag, chunks: routed or retrieved on
  the solo question; pdf: the paper).

Three runs of each arm in each mode: 4 arms × 2 modes × 3 runs × 16 = 384 answers.

**Measure.** Right answers per arm and mode, turns 1-8 against 9-16; chat against solo per arm (paired over the
48 run-question pairs, exact sign-flip); in chat, how often a turn is right after a right turn and after a wrong one
(error carrying over); context size at the last turn; turns refused for length.

## Order, freezing, grading

1. No model: `run.py questions`, `chunks`, `queries`; the dense scores; `run.py route`, `retrieve`. Their outputs
   are frozen with the code. The dense scores come from `embed_modal.py` (the same computation as `embed.py`, on a
   Modal GPU): `embed.py` on this laptop's CPU ran at about 2 chunks a second, an hour for the 7,932.
2. Freeze: `frozen.sha256` over PLAN.md, GRADING.md, run.py, run.sh, embed.py, embed_modal.py, grade.py,
   questions.json, conversation.json, chunks.jsonl, queries.json, routes.json, dense.json.gz, retrieval.json.
   `run.py` refuses to answer if any changed.
3. Answer: `run.sh` (`run.py answer`, `run.py solo`, `run.py chat` side by side on the Modal server).
4. Grade blind (`grade.py sheet bench`, `sheet conv`): which arm, mode or run wrote a letter stays in code until
   `grade.py unseal`, which hashes the grades first.
5. RESULTS.md.
