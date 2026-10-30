"""Ask the document a question; get an answer whose every number is a checked pointer.

The model gets the document's contents as facts (what relations exist, what tables and figures
there are), three tools, and the answer format. It looks with SQL, may view a figure, and submits
an answer through the door (answer.check). A refused answer comes back with every refusal and its
legal moves; the model fixes it and resubmits. Nothing the model says outside an accepted
submission reaches the user.

When the paper has a clause base (what the judge read from its prose), each question arrives with its leads:
the clause-base sentences and values that code matched to it (ugrc/leads.py). The model may read the clause
base, show one of its values by id (a measure run, which the machine quotes from its line), and every quote
that names what its value is `of` passes the pairing gate (ugrc/pairing.py).
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from ugrc import answer, leads, lineage, llm, pairing, store
from ugrc.refusal import Refusal

MAX_TURNS = 40

SYSTEM = """You answer questions about one document, "@FILE" (@PAGES pages), using only what the document contains.

You never type a fact. Every number you show comes from the document by pointer, and a machine checks every pointer before your answer is accepted.

## The document, as atoms
The PDF has been read into a read-only DuckDB database. Every piece of it is an atom whose id says where it is:
- lines(id, page, line_no, text, size, region, x0, top, x1, bottom): every line of text, in reading order. id like p5.L12. region is a figure id when the line is printed inside a figure.
- tables(id, label, number, page, continues, caption, caption_lines, columns_from, n_rows, n_cols, x0, top, x1, bottom): one row per table part; a table continued onto the next page has a second part whose `continues` names the first. id like p6.T2.
- table_columns(id, table_id, page, col_no, header, x_from, x_to): id like p6.T2.c6.
- cells(id, table_id, page, row_no, col_no, is_header, text, x0, top, x1, bottom): id like p6.T2.r3c6. row_no counts PRINTED lines of the table: a table row whose text wraps spans consecutive row_no values, and its short cells usually sit on its first line.
- figures(id, label, number, page, caption, caption_lines, png, x0, top, x1, bottom): id like p5.F2.
- figure_ocr(id, figure_id, page, line_no, text, conf, reader): text tesseract read from a figure's pixels. id like p5.F2.o3.
- figure_facts(id, figure_id, page, fact_no, statement, basis, printed_text, quantity, value, unit, condition, panel, ocr_confirmed, check_note, reader): what a vision model read from a figure; fact_no 0 is its summary. id like p5.F2.k4.
- consts(id, value, unit, definition): exact unit factors and physical constants. id like K.per_kilo.
- atoms(id, kind, page, text, strength, parent, x0, top, x1, bottom): all of the above in one relation; search it to find where something is.
Every atom has a strength: verbatim (printed text of the PDF), ocr (read from pixels by OCR), model-read (a vision model's reading of a figure), model-read, ocr-confirmed (its printed words were also found by OCR), canon (a constant).

@CLAUSES## Contents
@TOC

## Tools
- sql(query): one read-only SELECT, or DESCRIBE <relation>, over the relations above.
- view_figure(figure_id): see a figure's image, its caption and the facts read from it.
- submit_answer(runs): your answer. The machine checks it; if it refuses, it says exactly why and what it accepts instead. Fix every point and submit again.

## The answer: a list of runs, concatenated in order
- {"text": "..."}: your own words. They contain no number, in digits or in words: a token that starts with a digit is refused (CO2, IL-6, PD-L1 are fine: they start with a letter), and so are number words (one, two, ..., twenty, hundred, thousand, million, dozen, twice). A list may be numbered at the start of a line ("1.", "2)").
- {"text": "...", "support": [{"atom": "<id>", "quote": "<exact text>"}]}: your words, backed by exact text from atoms. The support quotes are NOT shown in the answer: they stand behind your words as citations. Anything the reader must see in the document's own words (a number, a name, a phrase) goes in a quote run. So your words must say the thing themselves: words that only lead into a support quote or a search ("it states that", "the yield was", "as follows:") are refused.
- {"text": "...", "absent": ["<term>", ...]}: your words saying the document does not contain something, backed by searches. Each term must occur nowhere in the document (a case-insensitive search of every line, cell, column header, OCR line and figure fact, across line breaks). A term whose words all occur together nearby is refused too, since the document may say it in other words ("detection limit" vs "limit of detection"). The citation shows exactly what was searched, so search the forms the document would use (for a dose: "mg/kg", "mg kg", "dose").
- {"quote": "<exact text>", "atom": "<id>"}: the document's own characters, copied exactly (whole words, whole numbers). This is how a number from the document enters your answer. When the value is given for one particular thing (a material, sample, strain, cell, condition), add "of": "<that thing, as the document names it>": a judge reads the sentence and refuses a pairing it does not support. A quote may run on across consecutive lines of the text: name the line it starts in, and copy the words as they read; a hyphen at a line end may be kept ("spe-cific") or dropped ("specific"). A table cell whose text wraps onto the next printed rows is quoted down them, like lines ("Phase 1 Completed" from "Phase 1" over "Completed"): a printed row that fills at most half of the table's columns, all under text on the row above, continues that row. A quote that stops where its cell goes on to another printed row is refused, so quote the cell whole; different table rows are never joined. A single word or name (CO2, Ni-10, 4-MPBA) can be quoted from any atom that holds it: if the atom you name does not, the machine cites its first occurrence. A name that starts with a digit (4-MPBA) cannot go in your own words, so quote it whole; never shorten it.
@MEASURE_RUN- {"sql": "SELECT ...", "column": "<name>", "row": 0, "fmt": "raw"}: a value computed over atoms (a count, a sum, a difference, a conversion). The machine re-runs it and traces it to the atoms it read. A computed value may contain no number you typed except 0, 1 and 100; any other number comes from an atom or from consts. fmt is raw, int, fixed0 to fixed6, or pct0 to pct3; pctN multiplies a fraction by 100 itself (0.827 shows as 82.7%), so never give it a value you already multiplied by 100. Cite row 0 of a one-row result, or add ORDER BY.
- {"figure": "<id>"} and {"table": "<id>"}: a figure or a table as a whole; it renders as its label ("Fig. 2", "Table 2"). Refer to figures and tables this way, never by typing their number.
Each pointer becomes a citation the reader can follow to the page and position in the PDF. If the document does not hold what the question asks, say so in text runs."""

TOOLS = [
    {"name": "sql", "strict": True,
     "description": "Run one read-only SELECT (CTEs allowed) or DESCRIBE <relation> over the document's atoms. "
                    "Returns up to 150 rows as text, and says how many rows there are in all when it shows fewer.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["query"],
                      "properties": {"query": {"type": "string", "description": "the SQL (DuckDB dialect)"}}}},
    {"name": "view_figure", "strict": True,
     "description": "See one figure: its image, its caption, and the facts a vision model read from it (with ids and strengths).",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["figure_id"],
                      "properties": {"figure_id": {"type": "string", "description": "a figure id such as p5.F2"}}}},
    {"name": "submit_answer",
     "description": "Submit the answer as a list of runs (text, quote, sql, figure, table). The machine checks every pointer; "
                    "it either accepts the answer or returns every problem with what it accepts instead.",
     "input_schema": {"type": "object", "required": ["runs"],
                      "properties": {"runs": {"type": "array", "items": {"type": "object"},
                                              "description": "the runs, in reading order"}}}},
]


def contents(con, doc=None) -> str:
    """The tables and figures, with their ids, captions and sizes; of one paper when `doc` is given."""
    where, args = ("WHERE doc = ?", [doc]) if doc else ("", [])
    cap_chars = 200 if doc else 400
    out = ["Tables:"]
    for tid, label, page, cont, cap, nr, nc in con.execute(
            f"SELECT id, label, page, continues, caption, n_rows, n_cols FROM tables {where} ORDER BY page, id",
            args).fetchall():
        heads = con.execute("SELECT col_no, header FROM table_columns WHERE table_id = ? ORDER BY col_no", [tid]).fetchall()
        more = f", continues {cont}" if cont else ""
        out.append(f"- {tid} {label} (page {page}, {nr} printed rows x {nc} columns{more}): {cap!r}\n"
                   f"  columns: " + " | ".join(f"{c} {h or '?'}" for c, h in heads))
    if len(out) == 1:
        out.append("- (none)")
    out.append("Figures:")
    fwhere = "WHERE label IS NOT NULL" + (" AND doc = ?" if doc else "")
    for fid, label, page, cap in con.execute(
            f"SELECT id, label, page, caption FROM figures {fwhere} ORDER BY page, id", args).fetchall():
        nf = con.execute("SELECT count(*) FROM figure_facts WHERE figure_id = ?", [fid]).fetchone()[0]
        no = con.execute("SELECT count(*) FROM figure_ocr WHERE figure_id = ?", [fid]).fetchone()[0]
        cap = (cap or "")[:cap_chars]
        out.append(f"- {fid} {label} (page {page}; {nf} facts read, {no} OCR lines): {cap!r}")
    lwhere = "WHERE label IS NULL" + (" AND doc = ?" if doc else "")
    loose = [r[0] for r in con.execute(f"SELECT id FROM figures {lwhere} ORDER BY page, id", args).fetchall()]
    if loose:
        out.append(f"Uncaptioned images, not read: {', '.join(loose)}")
    return "\n".join(out)


CORPUS_DOCUMENTS = """## The documents
This is a collection, not one paper. Every id starts with its document's key and a colon: ensm-2021:p13.T4.r5c2 is a cell of Table 4 of document ensm-2021, and every relation has a `doc` column holding that key. The relation documents(id, file, sha256, pages, doi, title, extractor_version, substrate, substrate_seals) lists them; a question may be about one of them, several, or all. Text runs on across lines only within one page of one document.
@DOCS
"""


MEASURE_RUN = """- {"measure": "<id>"}: a value of measures, by its id (as the leads list it). The machine copies its text from the line it was read from and cites that line, so you type neither the value nor its place: when the value you need is a measure, show it this way rather than with a quote run. It takes "of" like a quote run. A value the leads mark as not showable is refused here: quote it yourself.
"""

CLAUSES = """## Facts already read from the prose
Before any question, every sentence of the prose was read once: code found each value in it, and a judge (a classifier that only chooses among options built from that sentence) said what each value is. Two relations hold what it read:
- measures(@DOCid, text, value, unit, key, lo, hi, role, role_p, property, property_p, about, method, quantity, page, modality, polarity, sentence, atoms): one row per value printed in a sentence. text is the value as printed (quote it from the atom in `atoms`, the line that holds it); role is result (this work measured or obtained it), setting (a condition it chose), background (from other work), count, or identifier (a label, like the 811 of NFA 811); about lists what the value is given for, method how it was measured, quantity the words naming what it measures, all in the document's words (lists; search them with array_to_string(about, ' ') ILIKE '%...%'); modality says what its sentence does; role_p and property_p are the judge's probabilities.
- sentences(@DOCid, page, kind, text, modality, modality_p, polarity, polarity_p, atoms): every sentence of the prose; modality is result, method, interpretation, possibility, background or other; polarity is affirmed or negated.
Each question comes with its leads: the sentences of these relations whose words match the question best, with their values and their ids. Start from them. They are readings, not the document: a value may lack its about, carry a wrong one, or be missing (table cells and figure facts are not in them, and property is often 'other'). So read a value's sentence before you use it, and when the leads and these relations do not hold what the question needs, search lines, cells and figure_facts as usual. A sql run may not read these relations (compute over lines and cells); a value of measures is shown with a measure run. A quote run's atom may be the id of a sentence or a value: the machine finds the quote in that sentence's lines.

"""

# A shorter prompt for a small open model (style "small"): the same tools, the same door, the same rules, said in
# fewer words, as numbered steps, with one worked example and the refusals small models hit most (a number in
# own words, a quote not copied exactly, two kinds in one run, runs sent as a string). The examples are made up:
# no bench paper's text or value appears here.
SYSTEM_SMALL = """You answer one question about one document, "@FILE" (@PAGES pages), using only what the document says.

THE RULE: you never type a number yourself. A number reaches your answer only by pointing at the document. A machine checks every answer; if a rule is broken it refuses the answer and tells you exactly what to fix.

## How to work
1. Look things up with the sql tool (and view_figure for figures). Copy text exactly as the tool returns it.
2. Build the answer as a list of runs (below).
3. Call submit_answer with {"runs": [ ... ]}. If it is refused, fix exactly what the refusal says, and submit again.

## The database (read-only DuckDB)
- lines(id, page, text): every line of the text, in reading order. id like p5.L12.
- cells(id, table_id, row_no, col_no, text): every table cell. id like p6.T2.r3c6. table_columns(table_id, col_no, header) holds the column headers.
- figure_facts(id, figure_id, statement, value, unit): facts read from figures. id like p5.F2.k4.
- atoms(id, kind, page, text): all of the above in one table. Search it first, for example:
  SELECT id, text FROM atoms WHERE text ILIKE '%surface area%' LIMIT 20
@CLAUSES## Contents
@TOC

## The answer: a list of runs, joined in order
Each run is one JSON object with exactly ONE of these keys: text, quote, measure, sql, figure, table.
- {"text": "your words"}: your own words. NO digits and NO number words (one, two, ten, hundred...). Names that start with a letter are fine (CO2, NMC622).
- {"quote": "exact text", "atom": "<id>"}: characters copied exactly from that atom's text. Every number in your answer comes in a quote run. You may add "of": "<what the value belongs to>". A quote may run on into the next line: name the line it starts in.
@MEASURE_RUN- {"sql": "SELECT ...", "column": "<name>", "row": 0, "fmt": "raw"}: a value the machine computes (a difference, a ratio, a count). Type no number in it except 0, 1 and 100. column is a column name of your SELECT. fmt is raw, int, fixed1, fixed2, or pct1 (pct1 multiplies by 100 for you).
- {"text": "your words", "absent": ["short term", ...]}: say the document does not contain something. Each term (one to three words) must occur nowhere in the document.
- {"figure": "<id>"} or {"table": "<id>"}: point at a figure or table. Never type "Fig." or "Table" with a number yourself.

## Example (made up)
Question: What was the BET surface area of the carbon?
1. sql: SELECT id, text FROM atoms WHERE text ILIKE '%surface area%' LIMIT 20
   result: p4.L22 | The BET surface area of the carbon was 1,250 m^2/g, higher than
2. submit_answer: {"runs": [{"text": "The BET surface area of the carbon was "}, {"quote": "1,250 m^2/g", "atom": "p4.L22", "of": "the carbon"}, {"text": "."}]}

These are refused:
- {"text": "The surface area was 1,250 m^2/g."}: a number in your own words. Put it in a quote run.
- {"quote": "1250 m2/g", "atom": "p4.L22"}: not copied exactly. The line says "1,250 m^2/g".
- {"text": "The surface area was", "quote": "1,250 m^2/g"}: two kinds in one run. Make two runs.
- {"runs": "[{...}]"}: runs must be a JSON list, not a string.

## When the document does not answer
If the question assumes something the document contradicts, say so in text runs and quote what the document does say. If the document holds nothing about it, use an absent run with short terms."""

CLAUSES_SMALL = """## Leads
Some questions come with leads: sentences of the document that match the question, each value listed with an id like p4.L22:3#17 and what it was read to be. If a lead holds the value you need, show it with a measure run: the machine copies the value for you. First check that the lead's sentence is about what was asked. If the leads do not hold the answer, search lines and cells as usual. The tables measures(id, text, about, quantity, sentence, atoms) and sentences(id, text, atoms) hold all the leads; you may search them with the sql tool, but a sql run in your answer may not read them.
"""

MEASURE_RUN_SMALL = """- {"measure": "<id>"}: a value from the leads, by its id (like p4.L22:3#17). The machine copies the value from the document. You may add "of". Example: {"runs": [{"text": "The surface area was "}, {"measure": "p4.L22:3#17"}, {"text": "."}]}
"""

PROMPT_STYLES = {"full": (SYSTEM, CLAUSES, MEASURE_RUN), "small": (SYSTEM_SMALL, CLAUSES_SMALL, MEASURE_RUN_SMALL)}


def _small_corpus(con) -> str:
    """The small prompt for a corpus: the same rules and examples, with the documents listed and every id carrying
    its document's key ("paper-a:p4.L22", made up like the rest of the example)."""
    docs = con.execute("SELECT id, title FROM documents ORDER BY id").fetchall()
    listing = "\n".join(f"- {k}: {t!r}" for k, t in docs)
    toc = "\n\n".join(f"### {k}\n{contents(con, k)}" for k, _ in docs)
    s = SYSTEM_SMALL
    s = s.replace('You answer one question about one document, "@FILE" (@PAGES pages), using only what the document says.',
                  f"You answer one question about a collection of {len(docs)} documents, using only what they say. "
                  "A question may be about one of them, several, or all.")
    s = s.replace("## The database (read-only DuckDB)\n",
                  "## The documents\n" + listing + "\n\n## The database (read-only DuckDB)\n"
                  "Every id starts with its document's key and a colon (paper-a:p5.L12), and every table has a doc "
                  "column holding that key. documents(id, title) lists the documents.\n")
    s = s.replace("id like p5.L12", "id like paper-a:p5.L12").replace("id like p6.T2.r3c6", "id like paper-a:p6.T2.r3c6")
    s = s.replace("id like p5.F2.k4", "id like paper-a:p5.F2.k4")
    s = s.replace("SELECT id, text FROM atoms WHERE text ILIKE '%surface area%' LIMIT 20",
                  "SELECT id, text FROM atoms WHERE text ILIKE '%surface area%' LIMIT 20   (add AND doc = 'paper-a' to stay in one document)")
    s = s.replace("p4.L22", "paper-a:p4.L22")
    s = s.replace("## When the document does not answer", "## When the documents do not answer")
    s = s.replace("If the question assumes something the document contradicts, say so in text runs and quote what the document does say. If the document holds nothing about it,",
                  "If the question assumes something the documents contradict, say so in text runs and quote what they do say. If no document holds anything about it,")
    s = s.replace("must occur nowhere in the document.", "must occur nowhere in any of the documents.")
    on = store.has_clauses(con)
    clause_part = CLAUSES_SMALL.replace("sentences of the document", "sentences of the documents").replace("p4.L22:3#17", "paper-a:p4.L22:3#17")
    measure_part = MEASURE_RUN_SMALL.replace("p4.L22:3#17", "paper-a:p4.L22:3#17")
    return (s.replace("@TOC", toc).replace("@CLAUSES", clause_part if on else "")
            .replace("@MEASURE_RUN", measure_part if on else ""))


def system_prompt(con, style: str = "full") -> str:
    if style != "full":
        from ugrc import corpus
        if corpus.is_corpus(con):
            if style == "small":
                return _small_corpus(con)
            raise ValueError(f"prompt style {style!r} has no corpus form")
        system, clause_part, measure_part = PROMPT_STYLES[style]
        file, pages = con.execute("SELECT file, pages FROM sources").fetchone()
        on = store.has_clauses(con)
        return (system.replace("@FILE", file).replace("@PAGES", str(pages)).replace("@TOC", contents(con))
                .replace("@CLAUSES", clause_part if on else "").replace("@MEASURE_RUN", measure_part if on else ""))
    return _system_prompt_full(con)


def _system_prompt_full(con) -> str:
    from ugrc import corpus
    if corpus.is_corpus(con):
        docs = con.execute("SELECT id, doi, pages, title FROM documents ORDER BY id").fetchall()
        intro = (f"You answer questions about a collection of {len(docs)} documents, using only what they contain."
                 + SYSTEM[SYSTEM.index("\n"):SYSTEM.index("## The document, as atoms")])
        listing = "\n".join(f"- {k}: {title!r} (DOI {doi or 'not printed'}, {pages} pages)" for k, doi, pages, title in docs)
        toc = "\n\n".join(f"### {k}\n{contents(con, k)}" for k, *_ in docs)
        rest = SYSTEM[SYSTEM.index("## The document, as atoms"):].replace("@TOC", toc)
        return _with_clauses(con, intro + CORPUS_DOCUMENTS.replace("@DOCS", listing) + "\n" + rest, "doc, ")
    file, pages = con.execute("SELECT file, pages FROM sources").fetchone()
    return _with_clauses(con, SYSTEM.replace("@FILE", file).replace("@PAGES", str(pages)).replace("@TOC", contents(con)), "")


def _with_clauses(con, prompt: str, doc: str) -> str:
    on = store.has_clauses(con)
    return (prompt.replace("@CLAUSES", CLAUSES.replace("@DOC", doc) if on else "")
            .replace("@MEASURE_RUN", MEASURE_RUN if on else ""))


def question_message(con, question: str) -> tuple[str, leads.Leads]:
    """What the model is sent for one question: the question, then its leads when there is a clause base."""
    found = leads.find(con, question)
    return (question + "\n\n" + found.text if found.text else question), found


def _view_figure(con, root: Path, fid):
    row = con.execute("SELECT id, label, page, caption, png FROM figures WHERE id = ?", [fid]).fetchone() \
        if isinstance(fid, str) else None
    if row is None:
        ids = [r[0] for r in con.execute("SELECT id FROM figures WHERE label IS NOT NULL").fetchall()]
        return f"there is no figure {fid!r}; figures: {ids}", True
    facts = con.execute("SELECT id, statement, basis, ocr_confirmed, check_note FROM figure_facts "
                        "WHERE figure_id = ? ORDER BY fact_no", [fid]).fetchall()
    lines = [f"{row[1]} (page {row[2]}) — caption: {row[3]!r}", "facts read from it:"]
    lines += [f"- {i} [{b}{', ocr-confirmed' if c else ''}] {s}" for i, s, b, c, _ in facts] or ["- (not read yet)"]
    png = (root / row[4]).read_bytes()
    return [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.standard_b64encode(png).decode()}},
            {"type": "text", "text": "\n".join(lines)}], False


def _new_record(question, model, con, found) -> dict:
    return {"question": question, "model": model, "tool_calls": 0, "turns": 0, "trace": [], "door_refusals": [],
            "door_version": answer.DOOR_VERSION, "pairings": [], "clause_base": store.has_clauses(con),
            "clause_seal": store.clause_seal(con)[0], "leads": found.record(),
            "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                      "cache_creation_input_tokens": 0}}


def ask(root, question: str, model=None, cl=None, effort="high", log=print, judge=None, prompt="full") -> dict:
    """One question in a fresh conversation. `judge` answers the pairing gate's questions (default: Jev).
    `prompt` is the system prompt's style (PROMPT_STYLES); the record keeps it and the prompt's hash."""
    root = Path(root)
    model = model or llm.MODEL
    cl = cl or llm.client()
    con = store.connect_question(root)
    try:
        text, found = question_message(con, question)
        record = _new_record(question, model, con, found)
        system = system_prompt(con, prompt)
        record["prompt"] = {"style": prompt, "sha256": hashlib.sha256(system.encode()).hexdigest()}
        _answer(con, root, cl, model, system, [{"role": "user", "content": text}],
                record, effort, log, judge)
        return record
    finally:
        con.close()


def session(root, questions, model=None, cl=None, effort="high", log=print, on_answer=None, judge=None) -> list[dict]:
    """Several questions in ONE conversation: each question sees every earlier question, every tool
    result and every accepted answer. Each answer still goes through the door on its own."""
    root = Path(root)
    model = model or llm.MODEL
    cl = cl or llm.client()
    con = store.connect_question(root)
    sid = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    try:
        system, messages, pending, records = system_prompt(con), [], None, []
        for i, q in enumerate(questions):
            # the accepted submit_answer still needs its tool_result before the next question
            text, found = question_message(con, q)
            messages.append({"role": "user", "content": (pending or []) + [{"type": "text", "text": text}]})
            record = _new_record(q, model, con, found)
            record.update({"session": sid, "session_index": i})
            log(f"[session {i + 1}/{len(questions)}] {q[:90]}")
            pending = _answer(con, root, cl, model, system, messages, record, effort, log, judge)
            records.append(record)
            if on_answer:
                on_answer(record)
        return records
    finally:
        con.close()


def _answer(con, root, cl, model, system, messages, record, effort, log, judge=None) -> list:
    """Run model turns on `messages` (appending to it) until an answer is accepted; fill `record`.
    Returns the tool results of the accepting turn, which a session sends back with its next question."""
    for _ in range(MAX_TURNS):
        resp = llm.create(cl, model=model, max_tokens=16000, system=system, tools=TOOLS, messages=messages,
                          output_config={"effort": effort}, cache_control={"type": "ephemeral"})
        record["turns"] += 1
        if getattr(resp, "repairs", None):              # arguments the open-model adapter decoded (llm.decode_nested)
            record.setdefault("adapter_repairs", []).extend(resp.repairs)
        if getattr(resp, "host", None):                 # the host that served this turn, when a router names it
            hosts = record.setdefault("served_by", {})
            hosts[resp.host] = hosts.get(resp.host, 0) + 1
        for k in record["usage"]:
            record["usage"][k] += getattr(resp.usage, k, 0) or 0
        messages.append({"role": "assistant", "content": resp.content})
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            nudge = ("Your last turn was cut off at the output limit; continue." if resp.stop_reason == "max_tokens"
                     else "Only an answer sent through submit_answer reaches the user; submit it there.")
            messages.append({"role": "user", "content": nudge})
            continue
        results, accepted = [], None
        for u in uses:
            record["tool_calls"] += 1
            inp = u.input if isinstance(u.input, dict) else {}
            if u.name == "sql":
                try:
                    out, err = lineage.explore(con, inp.get("query")), False
                except Refusal as r:
                    out, err = r.render(), True
                log(f"  sql: {str(inp.get('query'))[:110]!r}" + (" -> refused" if err else ""))
            elif u.name == "view_figure":
                out, err = _view_figure(con, root, inp.get("figure_id"))
                log(f"  view_figure: {inp.get('figure_id')}")
            elif u.name == "submit_answer":
                checked = answer.check(inp, con)
                verdicts = []
                if checked.ok:      # the door accepted the pointers; the pairing gate checks what each is `of`
                    refused, verdicts = pairing.check(con, inp["runs"], checked.citations, judge)
                    if refused:
                        checked = answer.Checked(False, refusals=refused)
                if checked.ok:
                    accepted = (inp, checked, verdicts)
                    out, err = "accepted", False
                else:
                    record["door_refusals"].append([r.to_json() for r in checked.refusals])
                    out, err = checked.refusal_text(), True
                log(f"  submit_answer: " + ("accepted" if checked.ok else f"refused ({len(checked.refusals)} problems)"))
            else:
                out, err = f"there is no tool {u.name!r}", True
            results.append({"type": "tool_result", "tool_use_id": u.id, "content": out, "is_error": err})
            # what the model did, step by step: shows how much of an answer rests on the model's own work
            step = {"turn": record["turns"], "tool": u.name, "refused": err}
            if u.name == "sql":
                step["query"] = inp.get("query")
                step["rows"] = None if err else max(len(out.splitlines()) - 1, 0)
            elif u.name == "view_figure":
                step["figure"] = inp.get("figure_id")
            elif u.name == "submit_answer":
                step["runs"] = len(inp.get("runs") or [])
                if verdicts:
                    step["pairings"] = [{k: v[k] for k in ("run", "of", "verdict", "by", "p") if k in v} for v in verdicts]
                if err:
                    step["rules"] = [r["rule"] for r in record["door_refusals"][-1]]
            record["trace"].append(step)
        if accepted:
            doc, checked, verdicts = accepted
            seals = dict(con.execute("SELECT name, sha256 FROM seals").fetchall())
            record.update({"runs": doc["runs"], "rendered": checked.text, "citations": checked.citations, "pairings": verdicts,
                           "seals": seals, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            return results
        messages.append({"role": "user", "content": results})
    err = RuntimeError(f"no accepted answer within {MAX_TURNS} model turns "
                       f"({len(record['door_refusals'])} refused submissions)")
    err.record, err.messages = record, messages     # what was tried, for whoever reports the failure
    raise err


def save(root, record) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", record["question"].lower()).strip("-")[:50] or "answer"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = Path(root) / "answers" / f"{stamp}-{slug}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False, default=str))
    return path


def format_answer(record) -> str:
    out = [record["rendered"], "", "Sources:"]
    for c in record["citations"]:
        if c["kind"] == "computed":
            ids = ", ".join(s["atom"] for s in c["sources"][:8]) + (" …" if c["n_sources"] > 8 else "")
            out.append(f"[{c['n']}] computed = {c['rendered']} · {c['strength']} · from {c['n_sources']} atom(s): {ids}\n"
                       f"     sql: {' '.join(c['sql'].split())}")
            continue
        if c["kind"] == "search":
            terms = ", ".join(repr(t) for t in c["terms"])
            out.append(f"[{c['n']}] searched for {terms}: {c['matches']} matches in {c['atoms_searched']:,} atoms "
                       f"({c['scope']})")
            continue
        s = c["source"]
        where = (f"{s['doc']} (DOI {s.get('doi')}) · " if s.get("doc") else "") + f"page {s.get('page')}"
        if s.get("kind") == "cell":
            where += f" · {s['table']}, printed row {s.get('row')}, column {s.get('col')} ({s.get('column_header')})"
        elif s.get("kind") == "column_header":
            where += f" · {s['table']}, column header"
        if s.get("figure"):
            where += f" · {s['figure']}"
        if s.get("bbox"):
            where += f" · box {s['bbox']}"
        moved = f" (relocated from {s['relocated_from']})" if s.get("relocated_from") else ""
        text = s.get("text") or s.get("caption") or ""
        name = f"{s['atoms'][0]}–{s['atoms'][-1]}" if s.get("atoms") else s["atom"]
        out.append(f"[{c['n']}] {name}{moved} · {where} · {c.get('strength')}\n     \"{text[:220]}\"")
    return "\n".join(out)
