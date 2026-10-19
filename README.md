# ugrc — cite, don't find, for one PDF

Ask a paper a question and get an answer in which **every number is a pointer into the paper**, checked by a
machine before you see it. The model never writes a fact. It points at where the fact already is (a line, a
table cell, a figure), and a checker with no model in it follows every pointer and refuses the answer if one
doesn't land.

This is the core idea of [mesh](../mesh) ("cite, don't find"), cut down to one job: question → cited answer.

```
$ python -m ugrc ask "What is the largest particle size reported in Table 2, and how much larger is it than the smallest one?" --db runs/cai2026

The largest particle size in Table 2[1] is 625 ±58 nm[2]. It belongs to the LF-RES[3] nanoparticles, which
deliver silncOSLMT[4] (ref. [118][5]). The smallest is 53.42 ±4.63[6] nm, from an MMP-2-responsive peptide
system carrying siPD-L1[7] (ref. [219][8]). Subtracting the mean values gives a difference of about 571.58[9] nm …

Sources:
[1] p6.T2 · page 6 · box [37.6, 74.7, 557.7, 597.9] · verbatim
     "Table 2 Nanocarrier-based siRNA delivery systems for tumor metastasis."
[2] p6.T2.r23c6 · page 6 · Table 2, printed row 23, column 6 (Particle size) · box [357.9, 271.7, 395.5, 279.7] · verbatim
     "625 ±58 nm"
[6] p6.T2.r58c6 · page 6 · Table 2, printed row 58, column 6 (Particle size) · … · verbatim
     "53.42 ±4.63"
[9] computed = 571.58 · computed from verbatim · from 2 atom(s): p6.T2.r23c6, p6.T2.r58c6
     sql: SELECT CAST(split_part(a.text,' ',1) AS DOUBLE) - CAST(split_part(b.text,' ',1) AS DOUBLE) AS diff
          FROM cells a, cells b WHERE a.id='p6.T2.r23c6' AND b.id='p6.T2.r58c6'
```

Every `[n]` resolves to a page and a box in the PDF. The model did not type `625 ±58 nm`: it named cell
`p6.T2.r23c6` and the checker copied the text from there. It did not type `571.58` either: it wrote SQL over
the two cells, and the checker ran it and traced the result back to those two cells.

---

## Contents

1. [The idea](#1-the-idea)
2. [How it works, end to end](#2-how-it-works-end-to-end)
3. [From PDF to atoms](#3-from-pdf-to-atoms-no-model)
4. [Reading figures: OCR and a vision model](#4-reading-figures-ocr-and-a-vision-model)
5. [Atoms, ids and strengths](#5-atoms-ids-and-strengths)
6. [Pointers: what an answer is made of](#6-pointers-what-an-answer-is-made-of)
7. [SQL: computing without typing numbers](#7-sql-computing-without-typing-numbers)
8. [What the model sees, and when](#8-what-the-model-sees-and-when)
9. [The receipt](#9-the-receipt)
10. [What is stored where](#10-what-is-stored-where)
11. [Using it](#11-using-it)
12. [Results on the test papers](#12-results-on-the-test-papers)
13. [Clauses read by a classifier (experimental)](#13-clauses-read-by-a-classifier-experimental)
14. [Why it is built this way](#14-why-it-is-built-this-way)
15. [Limits](#15-limits)
16. [What came from mesh](#16-what-came-from-mesh)
17. [Code map and tests](#17-code-map-and-tests)

---

## 1. The idea

A language model can't be trusted to copy a number correctly, and you can't tell when it didn't. So it is never
allowed to write one. It may only write a **pointer**: an address of something that already exists in the
document, or a query over those addresses. A machine resolves every pointer and fills in the value itself.

That changes what can go wrong:

- a fabricated number is **impossible**: there is nothing to type it into;
- a wrong pointer is **visible**: it resolves to the wrong text, and the citation shows that text;
- a pointer to nothing is **refused** before the answer reaches you.

What stays the model's job is judgment: which atoms answer the question, and how to phrase the answer. The
citations exist so you can check that judgment cheaply, without hunting for the facts yourself.

## 2. How it works, end to end

```
paper.pdf
  │  ingest (pdfplumber, no model)
  ▼
atoms.duckdb ── every line, table cell, column header and figure, each with an id, a page and a box
  │             sealed by hash; re-extracting the PDF reproduces it exactly
  │
  ├─ OCR (tesseract) of each figure's pixels ──────► figure_ocr     (strength: ocr)
  └─ a vision model reads each figure ─────────────► figure_facts   (strength: model-read,
                                                                     or model-read, ocr-confirmed)
question
  │  the answering model looks (read-only SQL, view a figure), then submits its answer as runs
  ▼
the door (no model) ── resolves every pointer; refuses with the rule and the legal move; model fixes, resubmits
  ▼
answer + one citation per pointer ── saved with the seals it was checked against
  ▼
the receipt (`verify`, no model) ── re-checks the substrate and re-runs the door on the stored answer
```

## 3. From PDF to atoms (no model)

`ugrc/extract.py` turns the PDF into atoms with pdfplumber (pinned at 0.11.10). It is a pure function of the
PDF's bytes: same file, same atoms, same ids. Nothing is interpreted. No number is parsed and nothing is ranked
as important. It only records **where** each piece of ink is.

**Lines.** Words come from pdfplumber in the PDF's own content-stream order, which for a typeset paper is
reading order (left column, then right). A word continues the current line when it overlaps the line
vertically, moves forward, and is closer than a column gutter (9 pt). Words are joined with one space.
The one exception is a word split off by a size or baseline change, like a sub- or superscript touching its
neighbour:
- a **superscript** (smaller and raised) joins with a caret, because flattening it changes what the text
  says. `9.2 × 10⁷` is extracted as `9.2 × 10^7`, never `9.2 × 107`; `CD8⁺` becomes `CD8^+` and `mm³`
  becomes `mm^3`;
- a **subscript** joins tight, so `mPEG2k`, `CO2` and `NH4HCO3` stay one token while "CO2 emission" keeps
  its space.

A wide gap between words (over 9 pt) ends a line only when it spans the page's centre, which is where a
two-column gutter is; a stretched, fully justified line stays one line. Typographic ligatures (ﬁ → fi) are
expanded. Nothing else is normalized: no Unicode folding, so `²` stays `²`. A glyph the PDF's font maps to no
character is kept as pdfminer writes it, `(cid:0)`: the PDF doesn't say what it is (often a minus sign), so
it isn't guessed.

**Tables.** A table is found only where the paper **draws** one: a line starting "Table N", then a full-width
rule within 40 pt below it.
- **Header and bottom.** The short per-column rules under the header (how Elsevier draws booktabs tables)
  mark the header row and give the **column boundaries**. If no such rules are drawn, the boundaries are
  word-free vertical strips at least 4 pt wide.
- **End of the table.** It ends at the next full-width rule. A table continued on the next page ends at its
  last ink above the page number, and its next part ("Table 3 (continued)") records that it `continues`
  the first.
- **Rows** are *printed* rows. A table row whose text wraps occupies several consecutive printed rows.
  Which printed rows belong together is not drawn in the PDF, so it is not guessed.

**Figures.** A figure is an embedded image with a caption starting at most 30 pt below it, captioned
"Fig. N", "Figure N", "Scheme N" or "Chart N" (ids `p4.F1`, `p2.S1`, `p1.C1`).
- **Caption:** the caption's first line plus the lines that continue it (same font size, directly below).
- **Rendering:** the region is rendered to a PNG at 200 dpi, whose **pixel hash** is stored. That hash is
  what every later reading of the figure is pinned to. The embedded image's own bytes are hashed too.
- **Uncaptioned images** (logos, cover art) are recorded as `p1.I1` and never read.

**Coverage.** Every word on a page lands in exactly one atom: a cell if it lies inside a drawn table, a line
otherwise. This is tested by counting characters.

Every tolerance (9 pt gutter, 40 pt caption gap, …) is a named constant with its unit in `extract.py`, under
`EXTRACTOR_VERSION` (now 4). Changing one changes what an atom id means. The history: v2 added schemes and
charts; v3 added superscript carets and the centre-gutter rule; v4 splits words on pages that print no space
glyphs at a gap of 0.15 of the font size (7 of 10 papers in a battery-materials set came out with words glued
together, "Advancementtimelineof..."; pages that do print spaces read exactly as in v3, so the earlier
substrates re-extract unchanged).

## 4. Reading figures: OCR and a vision model

A figure in a paper is usually a raster image, so its labels and numbers exist only as pixels. Two independent
readers read them, and the machine compares them.

**OCR** (`ugrc/ocr.py`). Tesseract reads each captioned figure at 300 dpi. Each OCR line is stored with its
confidence and its box mapped back to PDF points, as an atom of strength `ocr`.

**The vision model** (`ugrc/figures.py`, `claude-opus-5-5`) is shown exactly two things: the figure's pixels
(the pinned PNG) and its caption, verbatim from the PDF. It is **not shown the OCR**, because OCR is the
second, independent reader, and checking the model against text it was handed would confirm nothing. It is
told the caption is already recorded, so it reports what the image adds. It returns facts:

```json
{"statement": "Under the metal-based nanoparticles heading, the three nanocarriers shown are AuNPs, SPIONs and MOF.",
 "basis": "printed",                       // printed in the image, or "visual" (shapes, heights, colours)
 "printed_text": ["Metal-based nanoparticles", "AuNPs", "SPIONs", "MOF"],
 "quantity": null, "value": null, "unit": null, "condition": null, "panel": null}
```

Then, with no model, each fact is checked:

- every `printed_text` string must occur in tesseract's reading of the same pixels, character for character
  (whitespace aside);
- a printed fact's `value` must be one of the numbers in its `printed_text`.

A fact that passes both checks is `model-read, ocr-confirmed`. Anything else is `model-read`, with the reason
recorded in `check_note`. Nothing is dropped, and nothing is promoted. Fact 0 of each figure is the model's
summary of it.

On the test paper the model read 90 facts from 4 figures: 59 "printed", 37 of those OCR-confirmed.
- **Most misses are OCR's.** It reads `μM` as `uM` and an underlined heading as `Metal-based_nanoparticles`,
  fails on Greek letters (`HIF-1α`), and splits labels across columns.
- **At least one may be the model's.** It reported pH ticks `6.0 / 5.0 / 4.0` that OCR never saw. Either OCR
  missed small ticks or the model invented them. The machine can't tell which, so the fact stays `model-read`.

## 5. Atoms, ids and strengths

| id | what it is | where it comes from |
|---|---|---|
| `p5.L12` | line 12 of page 5, in reading order | the PDF's text |
| `p6.T2` | Table 2 as drawn on page 6 (`p17.T3` continues `p16.T3`) | drawn rules + caption |
| `p6.T2.c6` | column 6's header | the header cells |
| `p6.T2.r3c6` | Table 2, printed row 3, column 6 | text inside the table |
| `p5.F2` | Figure 2 (a region of page 5, with its PNG); `p2.S1` is Scheme 1 | embedded image + caption |
| `p5.F2.o3` | a line OCR read from Fig. 2's pixels | tesseract |
| `p5.F2.k4` | a fact the vision model read from Fig. 2 (`k0` = its summary) | vision model |
| `K.per_kilo` | an exact unit factor or physical constant (11 of them) | definitions, not data |

Every atom carries a page and a box in PDF points. On the first test paper there are 4,108 atoms: 3,064
lines, 795 cells, 30 column headers, 114 OCR lines, 94 figure facts (90 + 4 summaries), 11 constants.

**Strength** says how far to trust an atom, from strongest to weakest:

| strength | meaning |
|---|---|
| `verbatim` | printed text of the PDF, read by position |
| `canon` | an exact constant (SI definitions, unit prefixes) |
| `ocr` | text tesseract read from a figure's pixels |
| `model-read, ocr-confirmed` | a vision-model reading whose printed words OCR also found |
| `model-read` | a vision-model reading, not confirmed |

A computed value is labelled with its weakest source ("computed from verbatim").

## 6. Pointers: what an answer is made of

The answering model submits its answer as a list of **runs**, concatenated in order:

| run | what it is | what the door checks |
|---|---|---|
| `{"text": "..."}` | the model's own words | contain **no number**: no token starting with a digit, no number word |
| `{"text": "...", "support": [{"atom", "quote"}]}` | own words, backed by the document | each support quote is verbatim in its atom. Support quotes are **cited, not shown**, so words that only lead into one are refused |
| `{"text": "...", "absent": ["term", ...]}` | own words saying the document lacks something | each term occurs **nowhere** in the document |
| `{"quote": "...", "atom": "p6.T2.r3c6"}` | the document's own characters, shown | verbatim in the atom, cut cleanly, a wrapped cell shown whole; this is how a number enters an answer. `atom` may also be a clause-base sentence or value id |
| `{"measure": "p3.L28:66#389"}` | a value of the clause base (§13), by id; the machine copies its text | the value's text resolves as a quote in the line(s) it was read from; cited like a quote, with the judge's reading |
| `{"sql": "SELECT ...", "column": "x", "row": 0, "fmt": "fixed2"}` | a value computed over atoms | see §7: re-run, literal ban, traced to its atoms |
| `{"figure": "p5.F2"}`, `{"table": "p6.T2"}` | a figure or table as a whole | the id exists; renders its label ("Fig. 2", "Table 2") |

The door checks the **whole** submission at once and refuses with every problem. Each refusal names the
rule, the spot, why, and what it accepts instead. The model fixes the problems and resubmits.

### The rules, one by one

**Own words carry no numbers.**
- **Digits.** A token that *starts* with a digit is a number (`2 h`, `~98`, `(n = 5)`). Tokens that start with
  a letter keep their digits, so `CO2`, `Al2O3`, `IL-6`, `PD-L1` and `TGF-β1` are fine.
- **Number words** are refused too, from a closed list: one … nineteen, the tens, hundred, thousand, million,
  billion, trillion, dozen, twice, thrice. "Double", "triple", "half", "single", "both" and ordinals are
  deliberately *not* on the list, because they are also domain terms (double-stranded, triple-negative,
  half-life).
- **List numbering** ("1.", "2)") is allowed at the start of a line.
- Figures and tables are referred to by pointer (`{"table": ...}`), never as typed "Table 2". A wrong
  "Table 3" is a wrong citation.

**A quote is verbatim and whole.**
- It must appear character for character in the atom, and may not cut through a word or a number. "9" out of
  "98", "5" out of "1.5", "100 nm" out of "90–100 nm", "98" out of "~98", "85.2" out of "85.2%" and "10" out
  of "Ni-10" are all refused, because each would show you a statement the document does not make.
- **A number after an unmapped glyph keeps the glyph.** In "g-factors were (cid:0) 0.0151 and 0.0150" the
  glyph is probably a minus sign. Quoting "0.0151" alone is refused, because it would drop the sign. The
  refusal's move is to quote "(cid:0) 0.0151" and say in words that the sign is illegible in the PDF.
- **Across line breaks.** A quote may run across consecutive lines of the text, in reading order. A hyphen at
  a line end may be kept ("spe-cific") or dropped ("specific"); a slash at a line end joins tight
  ("PLGA/PLA"). The citation lists every line the quote spans.
- **Down a table column only within one wrapped cell (door v5).** Consecutive printed rows may be one wrapped
  cell ("Phase 1" / "Completed") or two different entries ("Ni-10" / "Ni-20"). A printed row **continues** the
  row above it when it fills at most half of the table's columns, only columns that hold text on the row right
  above, and is not one line running across columns (a sub-heading split at a column boundary: its pieces
  touch). In a table whose printed lines interleave (a name centred beside a several-line entry), no row
  continues another. A quote may run down a wrapped cell's pieces like lines, and **a quote that stops where its
  cell goes on** (it ends a piece that has one below, or begins a piece that has one above) is refused unless
  the answer shows that piece too: "Phase 1" alone would hide "Completed". Rows that are separate entries are
  never joined. On the 13 test papers, every one of the 10 distinct cuts this rule finds in stored answers is
  a real wrap.
- **You quote, the machine locates.** If the named atom doesn't hold the quote but exactly one place in the
  document does, the quote is relocated there and the citation records `relocated_from`. When the clause base
  is attached, `atom` may be a sentence or value id from the leads: the quote is looked up in that sentence's
  lines, and the citation records `named_by` (door v5).
- **Several places.** A single word or name ("Ni-10", "4-MPBA") resolves to its first occurrence, because its
  characters are the same everywhere; the citation records how many occurrences there are. A number or a
  phrase must still name its place, and the refusal lists the candidates.
- **Ready-made quotes.** When the door refuses a digit-led token in the model's own words that the document
  writes exactly that way (a name like "4-MPBA", or a value), the refusal includes the ready quote run, with
  "never shorten it". This exists because a model once avoided the refusal by writing "mercaptophenylboronic
  acid", dropping the "4-".

**Words say what they cite (door v5).** A support quote or a search is cited, not shown, so words that only
lead into it leave the reader without the thing: "it states that[1]", "the LOD was OD600 =[3]". When the words
before a hidden citation's mark end in an opener (":", "(", "=", an opening quotation mark) or a lead-in word
("that", "is", "of", "was", "states", …), and no shown quote right after the mark completes them, the run is
refused (`text:lead-in`), with the move "show those words as a quote run". This rule is
`experiments/bench-leads/gaps.py`'s detector, which agreed with hand grades on 71 of 71 answers; in the 528
answers of `experiments/bench-leads` it refuses exactly the 35 answers with a format gap.

**"The paper doesn't say" is a search.** An `absent` run lists search terms, and the door searches every atom
(lines, cells, column headers, OCR lines, figure facts) for each one:
- case-insensitively, with Unicode forms unified (µ and μ, ﬁ and fi);
- across line breaks, and down table columns.

Any match refuses the claim and names where it occurs. So does a near match: when all the words of a term
(each 3 letters or longer) occur together within two consecutive lines, the document may say the same thing
in other words. The search "detection limit" is refused because page 6 says "limit of detection". Searches read *more* liberally than quotes on purpose:
over-joining can only make a search find more, so an absence claim errs toward refused, never toward passed.
The citation records exactly what was searched, so a narrow search is visible as narrow:

```json
{"kind": "search", "terms": ["mg/kg", "mg kg", "mg·kg", "µg"], "matches": 0,
 "scope": "every atom of the document: text lines, table cells, column headers, OCR lines, figure facts",
 "atoms_searched": 4108}
```

### What a citation records

Every citation in the saved answer carries what a reader needs to find it in the PDF. A quote spanning two
lines:

```json
{"kind": "quote", "quote": "primarily involves five critical steps", "strength": "verbatim",
 "source": {"atom": "p3.L78", "atoms": ["p3.L78", "p3.L79"], "kind": "line", "page": 3,
            "bbox": [306.6, 202.9, 557.7, 221.4],
            "text": "process of tumor metastasis, illustrated in Fig. 1, primarily involves five critical steps: …"}}
```

A table cell also records the table, printed row, column and column header. A figure fact records the
figure, its PNG, the reader, basis, printed text, whether OCR confirmed it, and why not. A computed value
records the SQL, the value, and every source atom with its own location.

## 7. SQL: computing without typing numbers

Counts, sums, differences and unit conversions are written as SQL over the atoms (DuckDB). `ugrc/lineage.py`
does three things to a cited query.

**The gate.**
- **One read-only SELECT** (CTEs allowed) over the atom relations only: no table functions, no files,
  no DDL.
- **A locked-down connection.** It is read-only with external access off, so the gate is the second lock,
  not the only one.

**The literal ban** (from mesh). SQL may *choose* with any constant: `WHERE page = 6`,
`regexp_extract(text, '([0-9.]+)', 1)`, `round(x, 2)`, `CAST(x AS DECIMAL(10,2))`. But a *value* may not
contain a typed number. `SELECT 42`, `count(*)*0 + 4200000`, `x/1000`, `CASE … THEN '85 %'`,
`lpad('', 2, '98')` and `coalesce(NULL, 98)` are all refused. The only numbers a value may carry as written
are 0, 1 and 100. A unit factor comes from `consts`:
`(SELECT value FROM consts WHERE id = 'K.per_kilo')`. That constant is an atom too, so it shows up in the
lineage. Which literal is "choosing" and which is "value" is decided by sqlglot's syntax tree (a regex group
number versus an operand of `*`), not by pattern matching.

**A percent is scaled once (door v6).** `fmt: pctN` shows a fraction as a percent: it multiplies by 100
itself. A pct run whose SQL also multiplies by 100 is refused (`sql:pct-scaled`), with what the reader
would have seen and the two fixes (keep the `* 100` and use `fixedN`, or drop it). Haiku did this in all 9
pct computations of `experiments/bench-leads` and `experiments/bench-multistep` ("3,333%" for 33.3%, "8,270.3%"
for 82.7%). Every pointer resolved and every receipt was GREEN, so this was the benches' only source of
wrong answers. Replayed over all 924 stored answers, the rule refuses exactly those 8 answers and no other.

**Why-provenance by rewriting** (Perm/GProM style, as mesh's `freesql_lineage`).
- **Rewrite.** Every relation the query reads is wrapped to carry `[id] AS __prov`. Every SELECT level
  combines its sources' ids, and flattens them over the group when it aggregates. Scalar subqueries get a
  twin that carries their rows' ids.
- **Verified by execution.** The rewritten query's original columns must reproduce the original rows. A
  rewriter bug therefore shows up as a refusal, never as a wrong source list.
- **Shapes it can't trace exactly are refused by name, each with the equivalent that works:**

  | refused | write instead |
  |---|---|
  | UNION | one query per branch |
  | window functions | GROUP BY or a JOIN |
  | `IN (SELECT …)`, `EXISTS` | a JOIN |
  | DISTINCT inside a subquery | GROUP BY |
  | GROUP BY ALL, NATURAL JOIN | name the columns |

A cited value must come from a stable row (ORDER BY when there are several), must not be NULL, and must trace
to at least one atom. `SELECT 1` reads nothing, so it has no source and is refused.

Lineage is **per row**: a value's sources are the atoms that fed its row. That is exact for a read of one
column, and a superset when the row joins several atoms.

## 8. What the model sees, and when

**When the question arrives,** the model sees the question and a ~6 KB system prompt:
- the file name and page count;
- the relations and their columns, the id formats and the strength vocabulary;
- a table of contents: each table's id, caption, size and column headers; each figure's id, caption (first
  400 characters), and how many facts and OCR lines it has;
- the tools and the answer format.

It does **not** see the paper's text, any cell, any OCR line, any figure fact or any image. It knows how the
paper is laid out, not what it says.

**With a clause base (§13),** the question also arrives with its **leads** (`ugrc/leads.py`): the sentences of
the prose whose words best match the question, each with its values and what the judge read them to be. Code
picks them, no model: the question's words are matched against each sentence and each value's reading (what
it is of, by what method, what it measures, its unit; never the judge's category label), widened by names
the paper defines ("vanadium pentoxide (V2O5)", the clause base's aliases) and, for a word found nowhere, by
its one-letter misspellings, and ranked by how rare the matched words are. Up to 12 sentences are sent; the
record keeps which. A value in the leads is shown with a measure run, so the model types neither the value
nor where it is.

**While it works,** content arrives only through tools, as the model chooses:
- `sql`: one read-only query, up to 150 rows back, each value cut at 400 characters, and the total row count
  when more exist. Looking is not traced and not literal-banned; only cited SQL is.
- `view_figure`: the figure's pixels, its caption and its stored facts with their ids.
- **Refusals** also carry content: an atom's real text, and the places that do hold a quote.

**When it submits,** the door resolves every pointer itself:

| piece of the final answer | produced by | checked |
|---|---|---|
| prose | the model | no number in digits or words |
| quoted text | the model types it | verbatim and whole in the named atom(s) |
| a clause-base value | **the machine copies it** from the value's line; the model names the measure id | verbatim and whole in that line |
| a computed value | **the machine runs the SQL**; the model never types it | literal ban, re-run, traced |
| "Table 2", "Fig. 2" | **the machine renders it** | the id exists |
| page, box, column header, strength, lineage | the machine | from the atom rows |
| "not in the paper" | the machine searches | zero matches |

**Afterwards,** the receipt re-runs the same check (§9).

**Never settled by the machine:**
- whether the cited atoms are the *right* ones for the question;
- reasoning written in prose (see §12);
- anything the model didn't look at.

## 9. The receipt

`python -m ugrc verify --db DIR [--pdf PAPER.pdf] [ANSWER.json …]` re-checks everything with no model:

- **substrate:**
  - the stored rows still hash to their seals (extraction, readings);
  - every figure PNG still holds the pixels its row pins;
  - every figure reading is pinned to those same pixels;
- **with `--pdf`:**
  - the PDF's bytes match the ingested file;
  - **re-extracting the PDF reproduces every atom**, so the atoms are a function of the PDF and not a copy
    someone could edit. If the substrate was built by an older extractor, the receipt says so on the same
    line; if the current extractor reads the PDF differently, the check goes red rather than passing;
- **each answer:**
  - it was checked by the current door version, or by an older one the door re-checks (under that door's rules);
  - against the current seals;
  - running the door again reproduces the same text and the same citations, byte for byte;
  - an answer that shows clause-base values, or quotes a line found by a clause-base id, needs that clause
    base beside the substrate, its rows still hashing to the seal the answer was checked against.
- **door versions:** door v4 only added the measure run. Door v5 added three things. Two are acceptances v4
  refused: clause-base ids as a quote's atom, and quotes down a wrapped cell. One is a pair of refusals: a cut
  wrapped cell and lead-in words. Door v6 added one refusal, a percent scaled twice. A rule applies from the
  door version that added it, and the receipt re-runs an answer under the door that accepted it, so answers
  of doors v3, v4 and v5 still re-check byte for byte; an older one must be re-checked (`recheck`) or asked
  again. `recheck` carries an answer over to the current door, so it applies every rule.

**When the extractor changes,** nothing is silently re-interpreted. You re-ingest into a new directory, then
use two no-model commands:
- `adopt-readings` carries the figure readings across, figure by figure, but only where the pinned pixels
  are identical (a reading is a reading of pixels);
- `recheck` re-runs the door on each stored answer against the new substrate. An answer whose pointers all
  still resolve is saved again with `rechecked_from`; one that doesn't is reported with its refusals.

Green means the pointers re-resolve. It does not mean the answer is good. Whether the right atoms were cited
is a judgment, and the citations are there so a reader can make it quickly.

## 10. What is stored where

```
runs/<paper>/
  atoms.duckdb        sources, lines, tables, table_columns, cells, figures, consts,
                      figure_ocr, figure_facts, figure_reads, seals, and the `atoms` view over all of them
  figures/<id>.png    the pinned figure renders (200 dpi)
  manifest.json       counts and anything the extractor declined, by name
  answers/<time>-<question>.json
                      question, model, runs (exactly what the model submitted), rendered text,
                      citations (full metadata), door_version, seals, refused rounds, tool calls, token usage
```

The `seals` table holds two hashes:

| seal | covers | how it is checked |
|---|---|---|
| **extraction** | the deterministic read of the PDF | `verify --pdf` re-derives it from the PDF |
| **readings** | OCR, figure facts and figure reads | pinned once, with who read what, from which pixels, and when; a model is not a function, so these can't be re-derived |

## 11. Using it

```bash
cd ~/Desktop/ugrc
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# also needed: tesseract (apt install tesseract-ocr), and Claude credentials for the two model steps

.venv/bin/python -m ugrc ingest ~/Downloads/paper.pdf --out runs/paper      # PDF -> atoms + OCR (no model)
.venv/bin/python -m ugrc corpus --out runs/all runs/paperA runs/paperB       # several papers as one, to ask across them
.venv/bin/python -m ugrc read-figures --db runs/paper                        # vision model reads the figures
.venv/bin/python -m ugrc ask "What particle sizes are reported for LNPs?" --db runs/paper
.venv/bin/python -m ugrc session questions.txt --db runs/paper                # many questions, one conversation
.venv/bin/python -m ugrc verify --db runs/paper --pdf ~/Downloads/paper.pdf runs/paper/answers/*.json
.venv/bin/python -m ugrc show p6.T2.r3c6 --db runs/paper                     # where is this atom?
.venv/bin/python -m ugrc adopt-readings --from runs/paper-old --db runs/paper # after a re-extraction
.venv/bin/python -m ugrc recheck runs/paper-old/answers/X.json --db runs/paper
.venv/bin/python -m ugrc sql "SELECT id, text FROM atoms WHERE text ILIKE '%EPR%'" --db runs/paper
.venv/bin/python -m ugrc clauses --db runs/paper --out runs/paper/clauses     # Jev reads the paper once (section 13)
.venv/bin/python -m pytest -q                                                # 225 tests, no model calls
```

**Credentials:**
- The SDK reads `ANTHROPIC_API_KEY`, or an `ant auth login` profile.
- If your key is in another variable, pass it per command without printing it:
  `ANTHROPIC_API_KEY="$API_KEY" .venv/bin/python -m ugrc ask …`.

**Model settings:**
- `claude-opus-5-5` by default (`UGRC_MODEL` or `--model` to change), at effort `high`.
- Anthropic's server-side refusal fallback is on: a declined request is retried on the recommended fallback
  model inside the same call. A refusal that survives it is raised by name, never read as an answer.
- The system prompt is cached across the turns of one question.

**An open model instead of Claude:** set `UGRC_LLM_URL` to an OpenAI-compatible chat-completions server
(e.g. llama.cpp's `llama-server --jinja`, `http://127.0.0.1:8090/v1`; `UGRC_LLM_KEY` if it wants a key) and
`UGRC_MODEL` to its model name. `ugrc/llm.py` translates each request and reply, so the loop and the door do
not change. Figures reach a text-only model as their caption and facts, not pixels. One encoding quirk of small
models (an array argument sent as a string, of JSON or a Python literal) is decoded and listed in the answer record
(`adapter_repairs`). Sampling: `UGRC_TEMPERATURE` 0.6, `UGRC_TOP_P` 0.9. `experiments/bench-llama/serve.sh`
starts Llama 3.1 8B this way.

## 12. Results on the test papers

### Paper 1: a review with tables

Cai et al., *Engineered nanomaterials for siRNA therapy against tumor metastasis*, Chemical Engineering
Journal 549 (2026) 182349. 27 pages, two columns, three booktabs tables (one continued across pages), four
raster figures.

**Ingest (extractor v3):**
- 3,064 lines, 4 table parts (795 cells), 4 figures plus 2 uncaptioned images, 114 OCR lines;
- nothing declined;
- re-extraction reproduces every atom.

**Six questions, asked twice.** The first round ran under door v1. Its problems led to the fixes in §6, and the
second round ran under door v2.

| question | door v1 | door v2 |
|---|---|---|
| sizes and release mechanisms of the lipid carriers in Table 2 | correct, but "roughly one hundred to one hundred fifty nanometres" slipped through as uncited words | number words refused; numbered list; count of rows computed by SQL |
| trials in Table 1, and how many use LNP | correct, but "four trials" was an uncited word | refused; trials listed by pointer; 19 trials and 15 drug entries computed by SQL |
| categories in Fig. 2 | correct; CQD rightly marked OCR-unconfirmed | same, with citation marks on the words |
| main steps of metastasis | correct, but "involves five" silently vanished (the model thought support quotes are shown) | "five critical steps" quoted across lines 78–79 |
| largest vs smallest particle size | 625 ±58 nm vs 53.42 ±4.63 nm, difference 571.58 traced to the two cells | same |
| the siRNA dose Gao et al. used | "not reported", backed by an unrelated line | backed by a search: 4 terms, 0 matches in 4,114 atoms |

Both rounds also caught a real inconsistency in the paper: Fig. 1's caption says "five key steps" but lists
four, while the main text lists five. I checked every factual claim above against the tables; all hold.

**Per question:**
- 4–7 tool calls, and at most one refused submission before acceptance;
- what got refused: number words, a numbered list (door v1), a support quote aimed at a figure id, an
  untraceable `IN (SELECT …)`;
- the receipt is green for all six.

**Cost (door v2 run, Opus 5.5 list prices, cache writes included):** $0.05–$0.14 per question, $0.54 for all
six. The cost of reading the four figures was not recorded.

**What the door still did not catch:**
- **Reasoning in prose.** The q5 answer says no approximate or upper-bound size is smaller than 53.42 nm, but
  "<190 nm" is only an upper bound and could be smaller. "Roughly an order of magnitude" is a quantity
  outside the word list.
- **Missing spaces where the model glues runs** ("tumour-associated[10]macrophages").

These six answers were made on the v1 substrate. After the v3 re-extraction, `recheck` re-resolved all six:
- five are identical;
- the dose answer's text is identical, and its search now covers 4,108 atoms instead of 4,114.

### Paper 2: a research article with data figures

Liu et al., *Intrinsic chiroptical structure-encoded single-probe sensor array for highly discriminative
bacterial identification*, Chemical Engineering Journal 549 (2026) 182243. 9 pages, no tables (its tables
are in the supplement), one scheme and five data figures (TEM, CD spectra, LDA plots, heat maps).

**Reading the paper by hand first found three extraction defects. All three were fixed as classes, not one-off
patches:**

| defect | what it would have done | fix |
|---|---|---|
| exponents flattened: "9.2 × 10⁷" read as "9.2 × 107" | a verbatim quote would show the wrong number | superscripts join with `^` (v3) |
| a minus sign in an unmapped glyph: "(cid:0) 0.0151" | quoting "0.0151" would drop the sign | the door refuses a number right after an unmapped glyph |
| "Scheme 1" not recognized as a caption | the scheme would be filed as an uncaptioned image, never read | captions may be Fig./Figure/Scheme/Chart (v2) |

A stretched, fully justified line also split into one word per line; the centre-gutter rule (v3) fixed it.

**Ingest:** 701 lines, 6 figures (1 scheme + 5 figures) plus 2 uncaptioned images, 204 OCR lines.

**Figure reading:** 208 facts, 81 "printed", 37 of those OCR-confirmed. On data plots OCR garbles tick
labels and minus signs, so nearly every reading of a curve or a bar stays `model-read`, which is the right
label for an estimate. Two examples of why the labels matter:
- The model read the CD peaks as "near 592 nm" and "near 800–830 nm", where the text states 585 nm and
  790 nm.
- Its Fig. 1 summary calls BA "berberine". In this paper BA is 4-mercaptophenylboronic acid, and the caption
  never defines it.

**Seven questions:**

| question | answer (all checked against the paper by hand) |
|---|---|
| viable cell count of each of the seven strains | all seven correct, e.g. "9.2 × 10^7 CFU/mL", each quoted from its line |
| optimized conditions | cysteine 75 μM, growth solution 80 μL, 4-MPBA 165 μM, NaCl 65 mM, with tested ranges |
| LODs, CD vs UV–vis | 0.0034 vs 0.0066 and 0.0123 vs 0.0125; factor 1.94 computed by traced SQL, labelled as the model's own calculation |
| CD peaks and g-factors | 585 and 790 nm; quoted "(cid:0) 0.0151 and 0.0150" with the glyph, stated the sign is illegible, and labelled its sign assignment from Fig. 1d as inference |
| partial discrimination, blind tests | S. typhimurium and S. aureus; 100% accuracy on four strains |
| zeta potentials (exist only in a chart) | about −7, +7 and +4 mV, presented as estimates read off the chart (`model-read`) |
| clinical sensitivity and specificity | not reported, backed by a search: 6 terms, 0 matches in 1,130 atoms |

**Per question:**
- 3–7 tool calls, and at most one refused submission;
- what got refused: number words, quoting a number without its glyph, a SQL value with no FROM, and one false
  positive (see below);
- $0.04–$0.09 per question, $0.46 for all seven; the receipt is green.

**The false positive:** the chemical name "4-MPBA" starts with a digit, so the door read it as a number. The
model got past it by quoting the name. Locant-prefixed names (4-MPBA, 5-FU, 2-propanol) can't be told apart
from quantities like "2-fold" by spelling alone, so both stay out of free prose. Since door v3, quoting them
costs nothing: the refusal hands back the exact quote, and a name resolves wherever it occurs.

### Hallucination stress test (paper 2)

48 answers in total:
- 31 independent probes;
- the same probes partly re-asked as a 15-question session that keeps its history;
- 2 long synthesis tasks.

The probe mix: false premises, absences, binding traps, and a planted wrong figure reading ("berberine").
Graded by hand against an answer key written before running. Full write-up in
`experiments/hallucination-paper2/RESULTS.md`.

**Results:**
- **zero** invented values;
- **zero** wrong pairings (including 35 strain/field pairings in one long task);
- **zero** accepted false premises (0 of 12);
- the wrong figure reading was **never** used.

**Four flaws:**
- two absence searches narrower than the claims they backed;
- one hedged wrong inference (in a session answer that found a real text/figure inconsistency in the paper);
- one imprecision the door induced: "4-MPBA" became "mercaptophenylboronic acid".

**Cost:** $2.89. All 48 answers re-resolve under the receipt.

**Follow-up (door v3):** the two mechanical flaws were fixed:
- the near-match absence rule;
- easy quoting of digit-led names.

Under door v3, 47 of the 48 answers re-check identically. The 48th is F6, whose "detection limit" search is
now refused, as intended. The 13 stored answers of both papers were re-checked and all resolve identically.

## 13. Clauses read by a classifier (experimental)

The question loop above re-reads the paper for every question. The clause idea reads it **once**: every
measured value is bound to what it is about, by what method, and as what quantity, and questions become
deterministic SQL over those bindings. `ugrc/clauses.py` does that reading with **Jev**, a non-generative
judge that can only *choose* among options it is given (`ugrc/jev.py`; `JEV_API_KEY`).

That works because a clause's arguments are spans of the paper. Code proposes every span, so the judge only
picks:

| step | who |
|---|---|
| cut sentences; find every quantity (interval, unit, `KEY =`); find named terms, phrases beside each value, and the paper's own definitions | code |
| let the layout decide what it can: "X of VALUE" and "KEY =VALUE" name the quantity, a list shares it, "VALUE (CD, …)" binds CD, a term inside the value is its unit | code |
| decide the rest: role, property kind, quantity, each term's relation (about / measured by / unrelated), sentence modality and polarity, whether a definition is right | Jev |
| flag hedge and negation conflicts, structure-vs-judge disagreements, one subject with two values, bindings across sentences; never correct | code |

```
runs/<paper>/…/clauses.duckdb   sentences, aliases, measures, jev_calls (every request and response), seals
```

```bash
.venv/bin/python -m ugrc clauses --db runs/paper2 --out runs/paper2/clauses        # ~300 Jev calls, ~2 min
.venv/bin/python -m ugrc clauses-check runs/paper2/clauses --db runs/paper2         # zero model
.venv/bin/python -m ugrc clauses-check runs/paper2/clauses --db runs/paper2 --rerun # ask Jev again, compare
.venv/bin/python -m ugrc clauses-replay --from OLD --db runs/paper2 --out NEW       # re-decide pinned answers
```

**On paper 2** (95 values, gold written before any call; `experiments/jev-clauses-paper2/RESULTS.md`):

| | right |
|---|---|
| role | 93/95 |
| property kind | 76/79 |
| method | 76/79 |
| quantity | 74/79 |
| subject | 65/79 lenient, 45/79 strict |

- **It got the key bindings right:** all 7 viable counts to the right strain, and all 4 detection limits
  to the right strain and method.
- **Re-running reproduced 1,123 of 1,138 decisions.** Every flip was a near tie (winning probability at
  most 0.58).
- **SQL alone answered 10 of 12 probes** with line pointers. One was partial (C3). One (X1) inherited an
  extraction error: "OD600" bound as a subject made a false CD-vs-UV pair.

**The receipt (`clauses-check`):**
- the seal covers the rows;
- the base was built on this substrate;
- re-planning asks exactly the pinned questions;
- re-deciding from the pinned answers reproduces every row.

`--rerun` adds the live comparison.

**Two worked examples — one where the clause base carries a question, one where it cannot** —
are in `docs/jev-worked-examples.md`, with the exact Jev questions, probabilities and resulting SQL.

**Open:**
- Subjects that are common nouns ("the tube", "these bacteria") are never offered as candidates. That is 28
  of the 79 values.
- On a paper with tables the clause base is not usable yet: it reads only text lines, so 0 of paper 3's 156
  measures come from a cell.
- Extra bindings are the judge's main error.
- Turning a question into a query is not built: the probe SQL was written by hand. The question loop now
  gets the clause base's matching rows as leads and can show its values by id (§8), but finding them is
  word matching, not a query: on papers 2 and 3, the leads held at least one prose line Opus's answers
  cited in 46 of 49 answers, on the 10-paper corpus in 6 of 11.

## 14. Why it is built this way

- **Tables only where drawn; columns from drawn rules.** A grid guessed from whitespace is not a fact the
  document states. Whitespace gutters are the fallback, and each table records which method it used.
- **Printed rows, not logical rows.** Which printed rows form one table row isn't drawn, so it isn't guessed.
  This is also why a quote never runs down a column.
- **The vision model never sees the OCR.** Two readers can only confirm each other if they read
  independently.
- **Choosing versus computing.** Constants are free in WHERE and in regex patterns, and banned inside values.
  The line is drawn on the syntax tree, the same way mesh's pointer/term split draws it.
- **Searches err toward finding.** Joining across lines, down columns and across Unicode forms can only find
  more, so an absence claim can only become harder to pass. Quotes stay exact.
- **The door answers the whole submission,** with the rule and the legal move, never just "invalid". Most
  failures of a capable model are failures of the feedback it was given.
- **Say no, never crash.** Hostile input (a malformed run, a DDL statement, a quote 100 kB long) becomes a
  named refusal. When a code bug did slip in during development, it surfaced as `checker:error` refusals, not
  a crash.

## 15. Limits

- **The extractor is under every pointer.** An atom's address is a coordinate into pdfplumber's reading of
  the PDF. The version is pinned, and `verify --pdf` proves the atoms still match the bytes.
- **Text the PDF doesn't carry.** Scanned pages, text drawn as outlines, and fonts with no Unicode mapping
  give no atoms. Chart values that exist only as pixels are only as good as their readers.
- **Visual readings can't be checked by the machine.** Bar heights, trends and colours stay `model-read`.
- **Prose is not checked beyond its numbers.** Reasoning, comparisons and qualitative claims without a
  `support` quote pass unchecked. Requiring `support` on every sentence would close this.
- **Number words come from a closed list.** Domain terms like "double" and "half" pass, and so does
  "order of magnitude". In the other direction, chemical names that start with a digit (4-MPBA) are refused
  in prose and have to be quoted.
- **Readings can be wrong and still be cited.** A `model-read` fact can be a hallucination ("berberine" for
  BA). The citation's label shows it is a model's reading, but the door can't tell a good reading from a bad
  one.
- **Glyphs the PDF doesn't map stay unknown** (`(cid:0)`). The door stops a number from losing its sign,
  but it can't say what the glyph is.
- **An absence is only as good as its search terms.** The near-match rule catches a term worded differently
  in the paper ("detection limit" vs "limit of detection"). It can't catch terms that simply don't cover the
  claim, such as searching "shelf" and "storage" to back "the monitoring time is not stated". The citation
  shows the terms, so a reader can judge. The near rule matches whole words, with no stemming.
- **Lineage is per row,** and a computed value's method (is this the right formula?) is the model's choice.
- **One PDF per substrate.** Tables without drawn rules, single-column tables and multi-line logical rows
  are not reconstructed.
- **Clauses are judged, not proved.** A clause's every argument is a real span, but which span it is bound
  to is Jev's choice. A wrong binding is inherited by every query over it. The flags, the margins and the
  re-run comparison mark the doubtful ones; they don't fix them.

## 16. What came from mesh

**Taken:**
- the sealed raw substrate, re-checked by the receipt;
- SQL as the only way to compute, and the literal ban;
- Perm-style lineage, verified by execution;
- "you quote, the machine locates" (W3C TextQuoteSelector, exact or fail);
- doors that answer the whole submission with the rule and the legal move;
- the receipt as the same check run again with no model;
- named tolerances with units;
- "say no, never crash".

**Left out:** the deliverable pipeline (contract, gates, ties, render backends, critic, converge, court),
the SQL-to-terms compiler, the 13-kind provenance kernel, and scoring.

## 17. Code map and tests

| file | role |
|---|---|
| `ugrc/extract.py` | PDF → lines, tables, cells, figures (pdfplumber; every tolerance named) |
| `ugrc/store.py` | DuckDB schema, the `atoms` view, constants, seals |
| `ugrc/ocr.py` | tesseract over figure pixels |
| `ugrc/figures.py` | the vision model's reading of figures, and the OCR cross-check |
| `ugrc/llm.py` | the one place a model is called: Claude (refusal fallback on), or an OpenAI-compatible open model |
| `ugrc/lineage.py` | the SQL gate, the literal ban, why-provenance |
| `ugrc/answer.py` | the door: runs, quotes, line flows, absence searches, rendering, citations |
| `ugrc/ask.py` | the question loop (one question, or a session that keeps history): prompt, tools, saving, printing |
| `ugrc/verify.py` | the receipt |
| `ugrc/corpus.py` | several papers' substrates as one: ids prefixed by paper key, a `documents` relation, its own receipt |
| `ugrc/jev.py` | the Jev client (a judge that only chooses) |
| `ugrc/leads.py` | a question's leads: the clause-base sentences and values whose words match it, found by code |
| `ugrc/pairing.py` | the pairing gate: a quoted value said to be `of` something, checked by the clause base or the judge |
| `ugrc/clauses.py` | clauses: sentences, quantities, candidates, layout rules, Jev's decisions, the clause door, replay and receipt |

`docs/jev-worked-examples.md` holds the two reference cases for the clause base: the question it answers
with no model at answer time, and the question it cannot answer, with the one-line cause.
| `ugrc/__main__.py` | the command line |

`tests/` holds 225 tests, none of which calls a model:
- **Synthetic paper** (`tests/synth.py`): a small hand-built substrate with a hyphenated line break, a
  wrapped cell and a Greek mu.
- **Scripted fake model client** (`tests/fakes.py`): drives the question loop and the figure reader.
- **Real-paper tests:** extraction invariants and re-extraction. These are skipped when the PDF is absent;
  set `UGRC_TEST_PDF` to point at it.
- **Word joining** (`tests/test_extract_join.py`): carets, subscripts, the centre-gutter rule.
- **Carry-over** (`tests/test_carry_over.py`): `adopt-readings` and `recheck`.
- **Clauses** (`tests/test_clauses.py`): quantity parsing, masks, definitions, phrases, layout rules, the
  door's conflict rules, build, replay and the clause receipt, with a scripted judge.
- **Routing and leads** (`tests/test_routing.py`, `tests/test_leads.py`): the clause base attached only to
  its own substrate, the pairing gate, leads, the measure run through the door, the loop and the receipt.
- **Door v5** (`tests/test_door_v5.py`): clause-base ids as a quote's atom, wrapped cells (pieces, quotes down
  them, cut cells, a sub-heading and interleaved rows that are not wraps), lead-in words, and older doors'
  answers re-checking under their own rules.
- **Door v6** (`tests/test_door_v6.py`): a percent scaled twice is refused, in every spelling of `* 100`;
  a fraction with `pct`, or a percent with `fixed`, passes; door v5 answers still re-check.
- **Open-model adapter** (`tests/test_llm_openai.py`): a conversation translated to chat completions and back,
  empty turns left out, an array argument sent as a string (JSON or a Python literal) decoded and counted, and
  the door saying so when `runs` arrives as a string, and a reply the server cannot parse taken as a bad turn.
