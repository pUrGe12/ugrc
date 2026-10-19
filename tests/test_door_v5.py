"""Door v5: a quote's atom may name a clause-base sentence or value; a quote may run down a wrapped table cell
and may not stop where the cell goes on; words may not lead into a hidden citation. Older doors' answers
re-check under their own rules."""
import json

from tests.test_routing import clause_base
from ugrc import answer, clauses, store, verify

# A table like a clinical-trial list: a row whose text wraps is printed on several lines, its short cells
# on the first. Columns are 100 pt wide; a printed line is 7 pt tall, every 10 pt.
WRAPPED = [  # row, col, header?, text
    (1, 1, True, "Drug"), (1, 2, True, "Target"), (1, 3, True, "Status"), (1, 4, True, "Sponsor"),
    (2, 1, False, "NBF-006"), (2, 2, False, "GSTP"), (2, 3, False, "Phase 1"), (2, 4, False, "Nitto BioPharma"),
    (3, 3, False, "Completed"),                                              # the status wraps
    (4, 1, False, "SY"), (4, 2, False, "KrasG12D"), (4, 3, False, "Phase 1"), (4, 4, False, "M.D. Anderson Cancer"),
    (5, 3, False, "Phase 2"), (5, 4, False, "Center"),
    (6, 3, False, "Recruiting"),
    (7, 1, False, "Co-5"), (7, 2, False, "KRAS"), (7, 3, False, "Phase 3"), (7, 4, False, "Acme"),
    (8, 1, False, "Results for"), (8, 2, False, "Co-5 trials"),             # one line across columns: a heading
]


def _add_table(root, tid, cells, top=300.0, step=10.0, tops=None):
    con = store.connect_write(root)
    n_cols = max(c for _, c, _, _ in cells)
    store._insert(con, "tables", [{"id": tid, "label": "Table 9", "number": 9, "page": 1, "continues": None,
                                   "columns_from": "test", "n_rows": max(r for r, *_ in cells), "n_cols": n_cols,
                                   "x0": 38.0, "top": top, "x1": 38.0 + 100 * n_cols, "bottom": top + 200,
                                   "caption": "Table 9 Trials.", "caption_lines": []}])
    store._insert(con, "table_columns", [{"id": f"{tid}.c{c}", "table_id": tid, "page": 1, "col_no": c, "header": h,
                                          "x_from": 38.0 + 100 * (c - 1), "x_to": 138.0 + 100 * (c - 1)}
                                         for r, c, hdr, h in cells if r == 1])
    rows = []
    for r, c, hdr, text in cells:
        y = (tops or {}).get(r, top + step * r)
        x0 = 40.0 + 100 * (c - 1)
        rows.append({"id": f"{tid}.r{r}c{c}", "table_id": tid, "page": 1, "row_no": r, "col_no": c, "is_header": hdr,
                     "text": text, "x0": x0, "top": y, "x1": x0 + 60, "bottom": y + 7})
    if any(t == "Results for" for *_, t in cells):                          # the heading's pieces touch
        for x in rows:
            if x["text"] == "Results for":
                x["x1"] = 138.0
            elif x["text"] == "Co-5 trials":
                x["x0"] = 138.5
    store._insert(con, "cells", rows)
    store.reseal(con, "extraction")
    con.close()


def _check(root, *runs, door=answer.DOOR_VERSION):
    con = store.connect_question(root)
    try:
        return answer.check({"runs": list(runs)}, con, door=door)
    finally:
        con.close()


def _rules(checked):
    assert not checked.ok
    return [r.rule for r in checked.refusals]


# ─────────────────────────── a clause-base id as a quote's atom ───────────────────────────

def test_a_value_or_sentence_id_names_the_line_of_a_quote(synth_root):
    # "85.2%" is printed on p1.L2, read off the figure by OCR and stated in a figure fact: which one?
    c = _check(synth_root, {"quote": "85.2%", "atom": "p1.L2:0#14"})
    assert _rules(c) == ["quote:absent"] and "3 places" in c.refusals[0].moves[0]
    clause_base(synth_root)                                  # the id names a value read from p1.L2
    c = _check(synth_root, {"text": "The yield was "}, {"quote": "85.2%", "atom": "p1.L2:0#14"})
    assert c.ok and c.text == "The yield was 85.2%[1]"
    src = c.citations[0]["source"]
    assert (src["atom"], src["relocated_from"], src["named_by"]) == ("p1.L2", "p1.L2:0#14", "value")
    c = _check(synth_root, {"quote": "85.2%", "atom": "p1.L2:0"})
    assert c.ok and c.citations[0]["source"]["named_by"] == "sentence"
    c = _check(synth_root, {"quote": "99.9%", "atom": "p1.L2:0"})
    assert _rules(c) == ["quote:absent"] and "a sentence of the clause base, on line(s) p1.L2" in c.refusals[0].why


def test_the_receipt_needs_the_clause_base_that_placed_a_quote(synth_root, tmp_path):
    clause_base(synth_root)
    runs = [{"text": "The yield was "}, {"quote": "85.2%", "atom": "p1.L2:0#14"}]
    con = store.connect_question(synth_root)
    c = answer.check({"runs": runs}, con)
    rec = {"runs": runs, "rendered": c.text, "citations": c.citations, "door_version": answer.DOOR_VERSION,
           "seals": dict(con.execute("SELECT name, sha256 FROM seals").fetchall()),
           "clause_seal": store.clause_seal(con)[0]}
    con.close()
    path = tmp_path / "a.json"
    path.write_text(json.dumps(rec))
    lines = verify.verify_answer(path, synth_root)
    assert all(ok for ok, _ in lines) and any("clause base holds the rows" in m for _, m in lines)
    (synth_root / clauses.CLAUSE_DB).unlink()
    lines = verify.verify_answer(path, synth_root)
    assert not all(ok for ok, _ in lines) and any("no clause base" in m for _, m in lines)


# ─────────────────────────── wrapped table cells ───────────────────────────

def test_printed_rows_that_continue_a_row_are_its_cell_pieces(synth_root):
    _add_table(synth_root, "p1.T9", WRAPPED)
    con = store.connect_readonly(synth_root)
    assert answer.wrap_pieces(con, "p1.T9.r2c3") == ["p1.T9.r2c3", "p1.T9.r3c3"]
    assert answer.wrap_pieces(con, "p1.T9.r6c3") == ["p1.T9.r4c3", "p1.T9.r5c3", "p1.T9.r6c3"]
    assert answer.wrap_pieces(con, "p1.T9.r4c4") == ["p1.T9.r4c4", "p1.T9.r5c4"]
    assert answer.wrap_pieces(con, "p1.T9.r2c1") == ["p1.T9.r2c1"]                # a short cell: its first line
    assert answer.wrap_pieces(con, "p1.T9.r7c1") == ["p1.T9.r7c1"]                # a heading is not a wrap
    assert answer.wrap_pieces(con, "p1.T9.r1c3") == ["p1.T9.r1c3"]                # nor a header
    assert answer.wrap_pieces(con, "p1.T1.r2c1") == ["p1.T1.r2c1"]                # Ni-10 / Ni-20: two full rows
    con.close()


def test_a_quote_runs_down_a_wrapped_cell(synth_root):
    _add_table(synth_root, "p1.T9", WRAPPED)
    c = _check(synth_root, {"quote": "Phase 1 Completed", "atom": "p1.T9.r2c3"})
    assert c.ok and c.citations[0]["source"]["atoms"] == ["p1.T9.r2c3", "p1.T9.r3c3"]
    c = _check(synth_root, {"quote": "M.D. Anderson Cancer Center", "atom": "p1.T9.r4c4"},
               {"text": ", status "}, {"quote": "Phase 1 Phase 2 Recruiting", "atom": "p1.T9.r4c3"})
    assert c.ok and c.text == "M.D. Anderson Cancer Center[1], status Phase 1 Phase 2 Recruiting[2]"
    # rows that are separate table rows are still never joined
    assert _rules(_check(synth_root, {"quote": "Recruiting Phase 3", "atom": "p1.T9.r6c3"})) == ["quote:absent"]


def test_a_quote_may_not_stop_where_its_cell_goes_on(synth_root):
    _add_table(synth_root, "p1.T9", WRAPPED)
    c = _check(synth_root, {"text": "NBF-006 is in "}, {"quote": "Phase 1", "atom": "p1.T9.r2c3"})
    assert _rules(c) == ["quote:wrapped"] and c.refusals[0].where == "runs[1]"
    assert "'Completed'" in c.refusals[0].why and '"Phase 1 Completed"' in c.refusals[0].moves[0]
    assert _rules(_check(synth_root, {"quote": "Completed", "atom": "p1.T9.r3c3"})) == ["quote:wrapped"]
    assert _rules(_check(synth_root, {"quote": "Phase 1 Phase 2", "atom": "p1.T9.r4c3"})) == ["quote:wrapped"]
    # every piece shown, one quote each, is the whole cell
    assert _check(synth_root, {"quote": "Phase 1", "atom": "p1.T9.r2c3"}, {"text": " "},
                  {"quote": "Completed", "atom": "p1.T9.r3c3"}).ok
    # a quote that stops inside a piece cuts nothing at the row break
    assert _check(synth_root, {"quote": "Anderson", "atom": "p1.T9.r4c4"}).ok
    assert _check(synth_root, {"quote": "Acme", "atom": "p1.T9.r7c4"}).ok           # the heading below is not its cell
    # door v4 quoted a wrapped cell piece by piece and refused none of this
    assert _check(synth_root, {"quote": "Phase 1", "atom": "p1.T9.r2c3"}, door="4").ok


def test_interleaved_printed_rows_continue_nothing(synth_root):
    # a name centred on its several-line entry is printed between two lines: rows do not say where entries start
    cells = [(1, 1, True, "Regulator"), (1, 2, True, "Function"), (1, 3, True, "Ref."),
             (2, 2, False, "binds the promoter and"), (3, 1, False, "PsrA"), (3, 3, False, "[112]"),
             (4, 2, False, "activates its transcription")]
    _add_table(synth_root, "p1.T8", cells, tops={2: 320.0, 3: 324.3, 4: 328.6})
    con = store.connect_readonly(synth_root)
    assert answer.wrap_pieces(con, "p1.T8.r4c2") == ["p1.T8.r4c2"]
    con.close()


# ─────────────────────────── words that lead into a hidden citation ───────────────────────────

SUPPORT = [{"atom": "p1.L2", "quote": "The yield was 85.2%"}]


def test_words_that_lead_into_a_hidden_quote_are_refused(synth_root):
    c = _check(synth_root, {"text": "The paper states that", "support": SUPPORT})
    assert _rules(c) == ["text:lead-in"] and c.refusals[0].where == "runs[0]" and "'The paper states that[1]'" in c.refusals[0].why
    assert _rules(_check(synth_root, {"text": "The yield is given as:", "support": SUPPORT})) == ["text:lead-in"]
    assert _rules(_check(synth_root, {"text": "Nothing is said about the", "absent": ["zeta potential"]})) == ["text:lead-in"]
    # words that say the thing themselves; or a shown quote right after the mark that completes them
    assert _check(synth_root, {"text": "Over Ni-10 the yield was high", "support": SUPPORT}).ok
    c = _check(synth_root, {"text": "The yield was", "support": SUPPORT}, {"text": " "}, {"quote": "85.2%", "atom": "p1.L2"})
    assert c.ok and c.text == "The yield was[1] 85.2%[2]"
    assert _check(synth_root, {"text": "The paper states that", "support": SUPPORT}, door="4").ok


def test_an_older_doors_answer_rechecks_under_its_own_rules(synth_root, tmp_path):
    runs = [{"text": "The paper states that", "support": SUPPORT}]
    con = store.connect_question(synth_root)
    c = answer.check({"runs": runs}, con, door="4")
    seals = dict(con.execute("SELECT name, sha256 FROM seals").fetchall())
    con.close()
    path = tmp_path / "v4.json"
    path.write_text(json.dumps({"runs": runs, "rendered": c.text, "citations": c.citations, "seals": seals,
                                "door_version": "4"}))
    assert all(ok for ok, _ in verify.verify_answer(path, synth_root))
    path.write_text(json.dumps({"runs": runs, "rendered": c.text, "citations": c.citations, "seals": seals,
                                "door_version": answer.DOOR_VERSION}))
    lines = verify.verify_answer(path, synth_root)
    assert not all(ok for ok, _ in lines) and any("text:lead-in" in m for _, m in lines)
