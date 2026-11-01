# The benchmark: what was tested, how, and what came out

Run on 2026-11-01. This file is the full account. `PLAN.md` is the plan as frozen before any answer existed,
`RESULTS.md` the results write-up, and `report.txt` the raw printout.

**In short.** Over a library of 130 papers, our setup (search picks the paper, then that paper's clause base form) got
**119 of 160** questions right. Handed the right paper's whole text, the same model got 101. Standard RAG over all 130
papers got 84. Most of the lead comes from table questions. In a 16-question conversation on one paper, ours fell from
14.3 of 16 (each question asked alone) to 12.3, and the whole paper scored 13.0. Three causes were found, and two fixes
are proposed. Neither fix is tested yet.

---

## 1. What was asked

- Compare our best setup against two others:
  - a RAG system that pulls from all the papers at once;
  - the right paper's PDF text handed straight to the model (no choosing).
- Use a large corpus.
- Run a long-horizon test: one paper, 10-20 linked questions asked one after another in the same conversation, so
  the context keeps filling up. Measure every setup on it.
- Add any other setup worth testing. I added **chunks** (section 3.1): it shows how much of the gain comes from the
  clause base and how much from choosing the paper.

**"Our best setup"** is the winner of the fresh-paper test (`../fresh/`, arm `top1`), unchanged: keyword search
picks one paper, then the model gets that paper's **facts+prose** form from its Jev clause base. Two things are left
out of it on purpose:
- **The door (pointer answers):** it lost on this setup (21 against 61 of 80, `../door-routed/`).
- **The Jev checker:** it needs Jev credits, and there are none.

## 2. What every setup shared

| | |
|---|---|
| Model | Llama 3.1 8B Instruct (`llama-3.1-8b-instruct`), bf16 |
| Server | our own vLLM server on Modal (`../bench-llama/run-modal.sh`), context window 131,072 tokens |
| Sampling | temperature 0.6, top_p 0.9, at most 4,096 tokens out |
| Library | 130 papers, 2,123 pages with text: the big library's 120 (`../big-library/`) plus the fresh test's 10 (`../fresh/`) |
| Clause bases | the ones already built. Jev had no credits, so nothing new was built and no live judge ran |
| Instructions | the same for every setup, worded for what it shows: answer briefly; show any calculation; say so when the question assumes something the text contradicts; say so when the text lacks the answer |

The instructions in full, as given to ours, chunks and pdf (`{form}` is the one sentence that changes):

> You answer questions about one document, "{title}", using only what that document contains. {form} Answer briefly.
> If you compute a number, show the calculation. If the question assumes something the document contradicts, say so.
> If the document does not hold the answer, say so.

Earlier tests gave the PDF setup a shorter prompt without these instructions (`../bench-llama/direct.py`). Here only
the content shown differs between setups.

---

## 3. Part 1: one question at a time over the 130-paper library

### 3.1 The four setups

| setup | how the paper is chosen | what the model reads | size (mean prompt tokens) |
|---|---|---|---|
| **ours** | keyword search (BM25 over every page of the 130 papers, each page headed by its paper's title); the top page's paper | that paper's **facts+prose** form: page by page, every sentence that states a value (from the clause base), then up to 30 more sentences that best match the question (BM25, at most 5,000 characters), then every table row by row and the facts read from its figures | 6,335 |
| **pdf** | none: the question's own paper is handed over | that paper's whole `pdftotext` | 18,879 |
| **chunks** (my extra setup) | the same search as ours | that paper's best 200-word chunks by the hybrid retrieval below, up to 24,000 characters, put back in page order (overlapping windows joined) | 5,447 |
| **rag** (standard RAG) | none: retrieval runs over all 130 papers' chunks at once | the best 200-word chunks from any paper, up to 24,000 characters, best first, each headed by its paper's title and page | 6,481 |

The `{form}` sentence for each:
- **ours:** "It is below, condensed: page by page, the sentences that state a value, with the few other sentences that
  best match the question (the rest are left out), then its tables row by row and facts read from its figures."
- **pdf:** "Its text, extracted from the PDF, is below."
- **chunks:** "Below are the passages of its text, extracted from the PDF, that best match the question, in page order
  (the rest is left out)."
- **rag** has its own instructions, since it does not know the paper:

  > You answer questions using only the excerpts below. A search over a library of scientific papers retrieved them
  > for the question; each excerpt is headed by its paper's title and page. The question is about one paper: answer
  > from that paper's excerpts and name it. Answer briefly. If you compute a number, show the calculation. If the
  > question assumes something the excerpts contradict, say so. If the excerpts do not hold the answer, say so.

**Why 24,000 characters:** that is about the mean size of ours' document on the fresh test (about 6,700 tokens). It
lets rag and chunks see about as much text as ours, so the test compares what is shown, not how much.

### 3.2 How rag and chunks retrieve

| step | setting |
|---|---|
| Chunks | each page's `pdftotext` words in windows of 200 words, a new window every 160 words (40 words overlap). A window never crosses a page. A page's last window under 60 words joins the one before. 7,932 chunks; mean 183 words, 1,218 characters |
| Keyword scores | BM25 (k1 = 1.5, b = 0.75) over the chunks in play |
| Embedding scores | `BAAI/bge-base-en-v1.5`, pinned revision `a5beb1e3e68b9ab74eb54cfd186867f64f240e1a`. Queries get the model's search instruction ("Represent this sentence for searching relevant passages: "). CLS pooling, normalized, cosine. fp32 on a Modal GPU (`embed_modal.py`) |
| Fusion | reciprocal-rank fusion of the two rankings, k = 60 |
| Filling | take chunks best first while they fit in 24,000 characters (one that does not fit is skipped); stop within 300 characters of the budget |
| In play | rag: all 7,932 chunks. chunks: only the routed paper's |

On average a rag prompt held 18.6 chunks from 2.5 papers (at most 10 papers). A chunks prompt held 18.1 chunks.

### 3.3 The questions (160)

- **The fresh test's 80.** 10 ChemE papers no setup had been tuned on, 8 questions each: gasification,
  techno-economic, catalytic, adsorption, pyrolysis, CO2 capture, wastewater treatment, crystallization, reactor and
  mass transfer.
- **80 of the big-library test's 388.** Drawn per question type in proportion to the 388, by a fixed seed
  (`benchmark-2026-11-01`). They come from 38 papers.

No question was reworded and no key was changed. Every question was written for one paper, and its key is that paper's
printed value.

| type | count | what it tests | example question | key | trap |
|---|---|---|---|---|---|
| A, absence | 20 | the paper does not give it; the right answer says so | What tar yield did the carbide slag-assisted steam gasification of sewage sludge give at Ca/C = 0.50? | not given | a gas yield given as the tar yield |
| B, binding trap | 21 | a value sits next to a similar one for another sample or condition | ... what mutation rate and mutation step did the NSGA-II algorithm use ...? | 0.01 and 0.01 (Table 10) | the other algorithm's 0.02 and 0.05 (Table 8) |
| C, lookup | 25 | a value stated in the text | ... what N2 flow rate, steam flow rate and isothermal reaction time were used? | 800 mL/min, 1.0 g/min, 30 min | the drying conditions |
| F, false premise | 21 | the question assumes something the paper contradicts | Why did carbide slag lower the risk level of As from medium to low ...? | it did not: As stayed at medium | explaining the drop |
| H, chained | 17 | find one thing, then a value tied to it | Which Ca/C ratio was chosen for the temperature runs, and how much carbide slag did it take per 10.0 g of sludge? | 0.50, 7.39 g | 0.75's 11.09 g |
| T, table | 37 | a value read from a table | What ash and fixed carbon contents did the sewage sludge have? | 42.61 and 9.02 wt % (Table 1) | the volatile matter or moisture |
| X, computation | 19 | a number computed from the paper's values | By what percentage did the H2 yield rise from Ca/C 0 to 0.75? | (332.85 − 207.40) / 207.40 = 60.49% | the volume fractions' 10.29 points |

**Routing:** search put 159 of the 160 questions on their own paper. The miss, `bench/aenm-2022/X1`, went to
`bench/adma-2020`; the right paper ranked second.

### 3.4 Results

| setup | right | partial | wrong | right, with rounding slips and table labels forgiven |
|---|---|---|---|---|
| **ours** | **119** | 1 | 40 | **126** |
| pdf | 101 | 3 | 56 | 106 |
| chunks | 96 | 4 | 60 | 99 |
| rag | 84 | 11 | 65 | 86 |

**Paired tests** (the same question in two setups; right against not right; exact sign-flip):

| comparison | difference | better / worse / same | p |
|---|---|---|---|
| ours − pdf | +18 | 28 / 10 / 122 | 0.005 |
| ours − chunks | +23 | 29 / 6 / 125 | 0.0001 |
| ours − rag | +35 | 43 / 8 / 109 | < 0.0001 |
| chunks − rag | +12 | 21 / 9 / 130 | 0.04 |

With the strict rules relaxed (rounding and table labels forgiven), ours still leads by 20 over pdf (p = 0.002).

**By question type** (right):

| type | ours | pdf | chunks | rag |
|---|---|---|---|---|
| A, absence (20) | 19 | **20** | 18 | 16 |
| B, binding trap (21) | 18 | 18 | 18 | 16 |
| C, lookup (25) | **24** | 23 | **24** | 21 |
| F, false premise (21) | **18** | 17 | 17 | 13 |
| H, chained (17) | **11** | 9 | 8 | 6 |
| **T, table (37)** | **22** | 9 | 5 | 7 |
| X, computation (19) | **7** | 5 | 6 | 5 |

**By source** (right): the fresh 80: ours 61, pdf 49, chunks 46, rag 45. The big-library 80: ours 58, pdf 52,
chunks 50, rag 39.

**Tags the grader put on answers:**

| tag | meaning | verdict | ours | pdf | chunks | rag |
|---|---|---|---|---|---|---|
| `[hedge]` | "not explicitly stated", then a value given anyway | wrong | 8 | 12 | 12 | 9 |
| `[label]` | the value from the wrong table, row or column | wrong | 3 | 2 | 0 | 0 |
| `[paper]` | values taken from another paper | wrong | 0 | 0 | 0 | 1 |
| `[miss]` | part of the answer missing | partial | 0 | 1 | 1 | 5 |
| `[name]` | right values, credited to another paper | right | 0 | 0 | 0 | 1 |

Most wrong answers carry no tag (ours: 11 of its 40).

### 3.5 What part 1 shows

- **The lead comes from tables.** On the 37 table questions, ours got 22 right; no other setup got more than 9. On
  the other 123 the setups are close: ours 97, pdf 92, chunks 91, rag 77. The clause base writes each table row out
  as its own line. `pdftotext` and 200-word chunks run a table's cells together, and Llama then reads the wrong row
  or column.
- **RAG finds the paper; it misses the passage.** Every rag prompt held chunks of the right paper (on average 88% of
  its chunks were from it). Only one rag answer took values from another paper. Restricting the same retrieval to the
  right paper (chunks) gained 12 questions; the clause base gained 23 more.
- **The instructions do not explain the PDF gap.** On the same 80 fresh questions the pdf setup scored 49 with ours'
  instructions here, against 50 with its short prompt in the fresh test.
- **The result repeats:** ours scored 61 of 80 on the fresh questions, the same as the regraded fresh setup in the door
  test (61).
- **Every pdf prompt fit:** the largest was 61k tokens, under half the 131k window.

---

## 4. Part 2: a 16-question conversation on one paper

### 4.1 The paper and the questions

- **Paper:** `cheme3/adsorption-2`, from the library: RSC Advances, biochar loading in dual-phase
  MIL-100(Al)/MIL-110(Al) hybrids for CO2 adsorption. 16 pages, about 23,400 tokens of `pdftotext`. No earlier test
  had asked about it.
- **Questions:** I read its whole text and wrote 16 linked questions before any answer (`conversation.json`).
- **Two forms of each question:**
  - **chat:** worded as a follow-up ("that composition", "the best composition", "that synthesis"). 12 of the 16
    lean on earlier turns.
  - **solo:** the same question spelled out in full, so it stands alone.

| # | type | what it asks | key |
|---|---|---|---|
| 1 | C | which composition adsorbed the most CO2 at 298 K and 1 bar, and how much | BC-10: 39.59 cm3 STP/g (1.77 mmol/g) |
| 2 | B | the biochar mass in that composition and in the one with twice its loading | 37.1 mg and 83.5 mg |
| 3 | X | check its nominal biochar loading from the three precursor masses | 37.1 / 371.1 = 10.0% |
| 4 | B | the autoclave's temperature and time in that synthesis | 210 °C for 3.5 h |
| 5 | T | its BET area, micropore area and pore volume | 496.79 m2/g, 372.99 m2/g, 0.274 cm3/g |
| 6 | F | "why did the pristine framework adsorb more CO2 than that composition?" | it did not: 1.16 against 1.77 mmol/g |
| 7 | X | the external (non-micropore) share of BET area, for it and the pristine framework | about 24.9% and 14.6% |
| 8 | T | the CO2-TPD strong-site density (280-400 °C), for it and the pristine framework | 2.7811 mmol/g; not resolved for the pristine |
| 9 | X | sum the 20% composite's weak, medium and strong sites; does it match the printed total? | 4.9837; yes, 4.984 |
| 10 | A | the activated biochar's own CO2 uptake | not given |
| 11 | T | which isotherm model fitted the best composition better, with both R² | Freundlich, 0.8199 against Langmuir 0.1930 |
| 12 | F | "why did Langmuir describe the 20% composite better than Freundlich?" | it did not: Freundlich 0.9111 against 0.7537 |
| 13 | C | TGA residue at 800 °C for it and the pristine framework | about 47 and 30 wt% |
| 14 | X | by what percentage its uptake exceeds the 20% composite's | 29.2% (the paper: about 29%) |
| 15 | T | the comparison table's highest-uptake adsorbent, and its isotherm model | CoNi-MOF-74/biochar, 7.55 mmol/g, Hill |
| 16 | A | how many adsorption-desorption cycles it kept its capacity over | not measured |

Each key also has a trap (`conversation.json`), e.g. for question 7 the micropore shares (75.1%, 85.4%).

### 4.2 How each setup ran

- **solo:** each of the 16 questions asked alone, exactly as in part 1. Search sent all 16 to the right paper.
- **chat:** one conversation per setup and run. The 16 questions go in order, and every earlier question and answer
  stays in the context. What each turn adds:

| setup | turn 1 | each later turn |
|---|---|---|
| pdf | the whole paper, then the question | only the question |
| ours | search on every question so far picks the paper; its facts+prose document, matched on this question and the one before | only the matching prose sentences not yet shown, each with its page; the facts and tables are not sent again |
| rag | retrieval over all 130 papers on this question and the one before; the excerpts | only chunks not yet shown |
| chunks | the routed paper's best chunks on this question and the one before | only that paper's chunks not yet shown |

Search sent all 16 chat turns to the right paper.

A turn that no longer fit the 131k window would get no answer, count as not right, and the conversation would go on.
No turn hit that.

**Runs:** 3 of each setup in each form: 4 setups × 2 forms × 3 runs × 16 questions = 384 answers.

### 4.3 Results

| setup | solo, right of 16 (runs) | chat, right of 16 (runs) | chat − solo (48 pairs) | context at the last turn | prompt tokens for all 16 turns: chat / solo |
|---|---|---|---|---|---|
| ours | **14.3** (14, 14, 15) | 12.3 (11, 12, 14) | −6, p = 0.18 | 16.6k | 216k / 147k |
| pdf | 12.3 (11, 14, 12) | **13.0** (13, 14, 12) | +2, p = 0.77 | 24.6k | 377k / 361k |
| chunks | 12.3 (13, 12, 12) | 10.3 (10, 12, 9) | −6, p = 0.18 | 16.7k | 207k / 84k |
| rag | 11.0 (11, 11, 11) | 8.3 (9, 8, 8) | −8, p = 0.08 | 33.3k | 336k / 100k |

- **All four setups together:** chat − solo is −18 of 192 (p = 0.02).
- **ours − pdf:** +6 of 48 when asked alone (p = 0.21), −2 of 48 in chat (p = 0.77). One paper is too few to separate
  them.

**Per question** (right, of 3 runs: chat / solo):

| # | type | ours | pdf | chunks | rag |
|---|---|---|---|---|---|
| 1 | C | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 |
| 2 | B | 3 / 3 | 3 / 3 | **0** / 3 | **0** / 3 |
| 3 | X | 3 / 3 | 3 / 2 | 2 / 3 | 3 / 3 |
| 4 | B | 3 / 3 | 3 / 3 | 3 / 3 | **0** / 3 |
| 5 | T | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 |
| 6 | F | **0** / 3 | 3 / 1 | **0** / 3 | **0** / 3 |
| 7 | X | 2 / 1 | 3 / 3 | 3 / 2 | 3 / 2 |
| 8 | T | 3 / 3 | 3 / 3 | 2 / 2 | 3 / 3 |
| 9 | X | 3 / 3 | 3 / 1 | 0 / 0 | 0 / 0 |
| 10 | A | 2 / 2 | 1 / 3 | 3 / 3 | 2 / 3 |
| 11 | T | 3 / 2 | 2 / 2 | 2 / 0 | 0 / 0 |
| 12 | F | **1** / 3 | 2 / 2 | 2 / 3 | 2 / 1 |
| 13 | C | 3 / 3 | 2 / 2 | 3 / 3 | 2 / 0 |
| 14 | X | 2 / 2 | 2 / 3 | 2 / 3 | 1 / 3 |
| 15 | T | **1** / 3 | 0 / 0 | 0 / 0 | 0 / 0 |
| 16 | A | 2 / 3 | 3 / 3 | 3 / 3 | 3 / 3 |

### 4.4 What part 2 shows

The conversation hurt every setup that retrieves text, and not the whole paper. The answers show three causes:

1. **Vague follow-ups retrieve the wrong text.**
   - Question 4, "at what temperature ... during that synthesis?", sent rag to another paper's carbon-dot synthesis
     (180 °C for 12 h) in all 3 runs.
   - Question 2, "how much activated biochar went into that composition", got the 10 and 20 wt% loadings instead of
     the masses in all 6 rag and chunks conversations. Alone, all 6 were right.
2. **Facts sent early get missed.** Ours sends the paper's facts and tables once, on turn 1. Later turns add only new
   prose sentences. By turns 12 and 15, the isotherm fits (Table 5) and the comparison table (Table 6) were about 14k
   tokens back. Llama said they were "not given" or "not discussed": question 12 right 1 of 3 in chat against 3 of 3
   alone, question 15 the same. I confirmed by rebuilding the turns that those tables were sent only on turn 1.
3. **False premises get through.** Question 6 claims the pristine framework adsorbed more than the best composition.
   In chat, ours, rag and chunks caught it 0 of 9 times; they explained or restated the premise. Alone they caught it
   9 of 9 times. The pdf setup caught it 3 of 3 times in chat and 1 of 3 alone.

Things that did **not** happen:
- **No error carried over.** Every setup got turn 1 right in every run, so "the best composition" always meant the
  right sample. No answer built on an earlier wrong answer of its own.
- **The context never ran out.** The largest was 33k tokens (rag), a quarter of the window. No turn was refused.

Other notes:
- **Later questions are harder in both forms.** Turns 9-16 score lower than turns 1-8 even alone: they hold the
  computations, the comparison table and the second false premise. So splitting the conversation in half does not
  measure the effect of length.
- **Question 15 (the comparison table) was the hardest.** Only ours got it (3 of 3 alone, 1 of 3 in chat). Every
  other setup got 0 of 6.

---

## 5. How the answers were graded

- **Who:** Claude graded all 1,024 answers (640 in part 1, 384 in part 2).
- **Blind:** the grading sheets (`grade.py sheet bench`, `grade.py sheet conv`) show the question, the paper's title,
  the key and the trap, then the answers under letters. They do not say which setup, form or run wrote a letter.
  Part 2's sheet mixes chat and solo answers to the same question.
- **Verdicts:** right, partial or wrong. Only right counts in the scores.
- **Sealed:** the grades were hashed (`graded.sha256`) before `grade.py unseal` matched letters to setups.
- **Rules** (`GRADING.md`): the rules of the earlier tests, unchanged, plus five for this test:
  - **K1:** an answer that takes values from another paper is wrong.
  - **K2:** a chat answer is graded on its own text; a value the question asks for must be in the turn.
  - **K3:** an error carried over from an earlier turn is still an error.
  - **K4:** part 2's keys in detail (e.g. question 3 needs the precursor masses in mg, not their mmol amounts).
  - **K5:** a turn with no text counts as not right.
- **Strict rules that cost every setup:**
  - A result that is not the correct rounding of its own inputs is wrong (rule 25).
  - "Not explicitly stated, however X" is wrong (`[hedge]`).
  - Restating a false premise before correcting it is wrong.
  - A value from the wrong table is wrong (`[label]`).

  The "forgiven" column in section 3.4 relaxes the rounding and table-label rules.
- **Calls made while grading** (`GRADING-settled.md`): written after every letter was graded and before unsealing, and
  applied to every letter they fit. For example: an answer that only pastes the right passage, without saying which
  value answers the question, is partial.

---

## 6. How the run went

**Before the freeze** (no model involved):
- Built the questions, chunks, queries, routes and retrieval.
- Fixed an index error in the chunker.
- Moved the embedding step to a Modal GPU (`embed_modal.py`). On this laptop's CPU it ran at about 2 chunks a second,
  about an hour for 7,932. It is the same model, revision and pooling as `embed.py`.
- Froze everything: `frozen.sha256` covers the plan, the grading rules, all code, both question files and all
  retrieval data. `run.py` refuses to answer if any of them changed. All hashes still match.

**The answering run** (`run.sh`, 2026-11-01, 20:21 to 20:54 IST): parts 1 and 2 ran side by side on the Modal server.
- **Part 1:** 640 answers.
- **Part 2:** 192 answers asked alone and 12 conversations of 16 turns.

The part 1 client was restarted twice. Each time it was waiting on replies the server had already sent, and the
server sat idle. The second restart cut the client timeout to 180 s, so a lost reply is retried after 3 minutes. Both
restarts are logged in `answer.log`. Saved answers were kept, and nothing frozen changed.

**After the run:** the Modal apps (`ugrc-llama`, `ugrc-embed`) were stopped.

---

## 7. What was not tested

- **The Jev checker** on these answers: it needs Jev credits.
- **The two conversation fixes** (section 8): proposed, not run.
- **Other RAG designs:** no reranker, no query rewriting, one embedding model, one chunk size and one budget. This
  RAG is a standard one, not the strongest possible.
- **Claude as the answering model:** every setup used Llama 3.1 8B. Nothing ran against Haiku.
- **Repeat runs of part 1:** it ran once.
- **More than one paper in part 2.**

**Caveats:**
- Claude wrote the part 2 questions and keys and did all the grading.
- Part 1's 160 questions were written for earlier tests, also by Claude.

## 8. What comes next

Two fixes for conversations, neither needing Jev:
1. Each turn, re-send the facts and table rows that match the new question, not only those sent on turn 1.
2. Search and retrieve on a stand-alone rewrite of the follow-up ("that synthesis" → "the MIL-100/110 hybrids'
   solvothermal synthesis"), not on the raw turn.

Then rerun part 2 with both fixes, adding a second paper.

## 9. How to rerun it

```
python experiments/benchmark/run.py questions      # questions.json
python experiments/benchmark/run.py chunks         # chunks.jsonl
python experiments/benchmark/run.py queries        # queries.json
.venv/bin/modal run experiments/benchmark/embed_modal.py    # dense.json.gz
python experiments/benchmark/run.py route          # routes.json
python experiments/benchmark/run.py retrieve       # retrieval.json
./experiments/benchmark/run.sh                     # all answers (needs the Modal server and ~/.ugrc_vllm_key)
python experiments/benchmark/grade.py sheet bench  # blind sheets (and: sheet conv)
python experiments/benchmark/grade.py record bench < grades.txt   # (and: record conv)
python experiments/benchmark/grade.py unseal       # hashes the grades, then matches letters to setups: hand.json
python experiments/benchmark/grade.py report       # report.txt
```

`run.py show ARM KEY` prints one part 1 prompt, and `run.py showchat ARM TURN` prints a conversation's turns up to
TURN.

## 10. Files

| file | what it is |
|---|---|
| `README.md` | this account |
| `PLAN.md`, `GRADING.md` | the plan and grading rules, frozen before any answer |
| `run.py`, `run.sh`, `embed.py`, `embed_modal.py`, `grade.py` | the code, frozen |
| `frozen.sha256` | hashes of everything frozen |
| `questions.json` | part 1's 160 questions with keys and traps |
| `conversation.json` | part 2's 16 questions, both forms, keys and traps |
| `chunks.jsonl`, `queries.json`, `routes.json`, `dense.json.gz`, `retrieval.json` | the chunks, queries, search results, embedding scores and retrieved chunks |
| `answers/bench/`, `answers/solo/`, `answers/chat/` | every answer, with its prompt hash, token counts and timing |
| `answer.log`, `embed.log`, `embed-modal.log` | run logs |
| `grades-bench.json`, `grades-conv.json` | the blind grades |
| `GRADING-settled.md` | calls made while grading, before unsealing |
| `graded.sha256`, `hand.json` | the grades' hash, and the grades matched to setups |
| `report.txt` | `grade.py report`'s printout |
| `RESULTS.md` | the results write-up |
