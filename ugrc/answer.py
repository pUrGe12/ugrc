"""The answer door: an answer is a list of runs, and every number in it is a pointer.

    {"text": "..."}                                      the answerer's own words — no numbers, in
                                                         digits or in words
    {"text": "...", "support": [{"atom", "quote"}...]}   own words, backed by exact text in atoms
                                                         (the support quotes are cited, not shown)
    {"text": "...", "absent": ["term", ...]}             own words saying the document lacks
                                                         something, backed by searches that find
                                                         every term nowhere in the document
    {"quote": "...", "atom": "p6.T2.r3c6"}               the document's own characters, verbatim;
                                                         may run across consecutive lines, and down
                                                         the printed rows of one wrapped table cell;
                                                         atom may also name a clause-base sentence
                                                         or value that holds the quote
    {"quote": "...", "atom": "...", "of": "NFA 811"}     ... naming what the value is given for; this door
                                                         keeps it with the citation, and the pairing gate
                                                         (ugrc/pairing.py) checks it against the sentence
    {"measure": "p3.L28:66#389"}                         a value of the clause base, by id: the machine
                                                         quotes its text from its own line(s) and cites it
                                                         like a quote, with what the judge read it to be;
                                                         may carry "of" like a quote
    {"sql": "SELECT ...", "column": "x", "row": 0, "fmt": "fixed1"}
                                                         a value computed over atoms, traced back
    {"figure": "p5.F2"}  {"table": "p6.T2"}              a figure / table as a whole (its label)

check() resolves every pointer against the substrate with no model involved and answers the WHOLE
submission at once (two rules, a cut wrapped cell and words that lead into a hidden quote, are checked once
every pointer resolves): either the rendered answer with one citation per pointer, or every refusal,
each naming the rule, the spot, why, and the legal move. The same function is the receipt: run
again on a stored answer it must reproduce the same text and the same citations.
"""
from __future__ import annotations

import json
import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from ugrc import lineage
from ugrc.refusal import Refusal
from ugrc.store import STRENGTH_RANK, has_clauses

DOOR_VERSION = "6"     # bumped whenever an accepted answer would render or cite differently, or be refused
                       # 3: an absence term whose words co-occur nearby is refused; a name token resolves
                       #    to its first occurrence
                       # 4: a measure run shows a value of the clause base, quoted from its line by the machine
                       # 5: a quote's atom may name a clause-base sentence or value; a quote may run down a
                       #    wrapped table cell, and one that shows only part of it is refused; words that
                       #    lead into a hidden citation ("it reports that[1]") are refused
                       # 6: a pct-formatted value whose sql already multiplies by 100 is refused (it would
                       #    show "3,333%" for 33.3%)
# Older doors whose answers this door re-checks under their own rules: v4 only added a run kind v3 refused,
# and v5's and v6's additions either accept what the door before refused (rendering it as that door would
# have, had it accepted) or are refusals that apply from their own version on (check(door=...)). The receipt
# re-runs the door an answer was accepted by.
RECHECKS = ("3", "4", "5")
MAX_RUNS = 300
MAX_TERM_CHARS = 200
FMT = re.compile(r"^(raw|int|fixed[0-6]|pct[0-3])$")
# a multiplication by 100 in a sql run (outside its string literals): with fmt pctN the value is scaled twice
_TIMES_100 = re.compile(r"\*\s*100(?:\.0*)?(?![\d.])|(?<![\w.])100(?:\.0*)?\s*\*")
_SQL_STRING = re.compile(r"'(?:[^']|'')*'")
MAX_OF_CHARS = 200
RUN_FIELDS = {"text": {"text", "support", "absent"}, "quote": {"quote", "atom", "of"}, "measure": {"measure", "of"},
              "sql": {"sql", "column", "row", "fmt"}, "figure": {"figure"}, "table": {"table"}}

# A token that STARTS with a digit (after an opening bracket or a sign/approximation mark) is a
# number. Tokens that start with a letter keep their digits: CO2, Al2O3, IL-6, PD-L1, TGF-β1.
_OPENERS = "([{\"'“‘«"
_NUMERIC_TOKEN = re.compile(r"^[~≈<>≤≥±+\-−–]?\d")
# ... except a list's own numbering at the start of a line: "1." or "2)".
_ENUMERATOR = re.compile(r"^\d{1,2}[.)]$")
# A closed list of number words: cardinals, the tens, scale words, and the multiplicatives that
# carry no other meaning. Left out on purpose, because they are also domain terms: double
# (double-stranded), triple (triple-negative), half (half-life), single, both, and ordinals.
NUMBER_WORDS = frozenset("""
    zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen
    sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety
    hundred hundreds thousand thousands million millions billion billions trillion trillions
    dozen dozens twice thrice""".split())
_WORD = re.compile(r"[^\W\d_]+")

SEARCH_SCOPE = "every atom of the document: text lines, table cells, column headers, OCR lines, figure facts"
NEAR_WINDOW_ATOMS = 2     # an absence term is "said another way" when all its words occur within this many
                          # consecutive atoms of one flow (two lines catch a phrase broken by a line end)
NEAR_MIN_WORD_CHARS = 3   # words shorter than this ("of", "mg") are not used for the near check
_WORDS = re.compile(r"[^\W_]+")


@dataclass
class Checked:
    ok: bool
    text: str = ""
    citations: list = field(default_factory=list)
    refusals: list = field(default_factory=list)

    def refusal_text(self) -> str:
        head = f"The answer was refused: {len(self.refusals)} problem(s). Fix all of them and submit again.\n"
        return head + "\n\n".join(r.render() for r in self.refusals)


def prose_numbers(text: str, line_start: bool = True) -> list[str]:
    """The numbers in the answerer's own words: tokens that start with a digit, and number words.
    `line_start` says whether the text begins a line (a list may be numbered there)."""
    out = []
    for m in re.finditer(r"\S+", text):
        tok = m.group()
        if not _NUMERIC_TOKEN.match(tok.lstrip(_OPENERS)):
            continue
        before = text[:m.start()]
        at_line_start = (line_start and not before.strip(" \t")) or before.rstrip(" \t").endswith("\n")
        if at_line_start and _ENUMERATOR.match(tok):
            continue
        out.append(tok)
    out += [w.group() for w in _WORD.finditer(text) if w.group().lower() in NUMBER_WORDS]
    return out


# ─────────────────────────── atoms ───────────────────────────

def _atom(con, aid):
    row = con.execute("SELECT id, kind, page, text, strength, parent, x0, top, x1, bottom FROM atoms WHERE id = ?",
                      [aid]).fetchone()
    if row is None:
        return None
    return dict(zip(("id", "kind", "page", "text", "strength", "parent", "x0", "top", "x1", "bottom"), row))


def _describe(con, aid) -> dict:
    """Everything a reader needs to find this atom in the PDF: page, box, and what it belongs to; in a
    corpus, also which paper (its key and DOI)."""
    return {**_describe_in(con, aid), **_paper(con, aid)}


def _paper(con, aid) -> dict:
    """In a corpus, the paper an id belongs to: {"doc", "doi"}; nothing for a single paper's ids."""
    if isinstance(aid, str) and ":" in aid:
        row = con.execute("SELECT id, doi FROM documents WHERE id = ?", [aid.split(":", 1)[0]]).fetchone()
        if row:
            return {"doc": row[0], "doi": row[1]}
    return {}


def _describe_in(con, aid) -> dict:
    a = _atom(con, aid)
    if a is None:                                       # a table or figure id read as a whole
        for rel, kind in (("tables", "table"), ("figures", "figure")):
            row = con.execute(f"SELECT id, label, page, x0, top, x1, bottom FROM {rel} WHERE id = ?", [aid]).fetchone()
            if row:
                return {"atom": row[0], "kind": kind, "label": row[1], "page": row[2],
                        "bbox": [round(v, 1) for v in row[3:7]], "strength": "verbatim"}
        return {"atom": aid, "kind": "unknown"}
    d = {"atom": a["id"], "kind": a["kind"], "page": a["page"], "strength": a["strength"], "text": a["text"]}
    if a["x0"] is not None and a["top"] is not None:
        d["bbox"] = [round(v, 1) for v in (a["x0"], a["top"], a["x1"], a["bottom"])]
    if a["kind"] == "cell":
        t = con.execute("SELECT t.label, c.row_no, c.col_no, h.header FROM cells c JOIN tables t ON t.id = c.table_id "
                        "LEFT JOIN table_columns h ON h.table_id = c.table_id AND h.col_no = c.col_no WHERE c.id = ?",
                        [aid]).fetchone()
        d.update({"table": t[0], "row": t[1], "col": t[2], "column_header": t[3]})
    elif a["kind"] == "column_header":
        d["table"] = con.execute("SELECT label FROM tables WHERE id = ?", [a["parent"]]).fetchone()[0]
    elif a["kind"] in ("ocr", "figure_fact"):
        f = con.execute("SELECT label, png FROM figures WHERE id = ?", [a["parent"]]).fetchone()
        d.update({"figure": f[0], "figure_png": f[1]})
        if a["kind"] == "ocr":
            d["reader"] = con.execute("SELECT reader FROM figure_ocr WHERE id = ?", [aid]).fetchone()[0]
        else:
            r = con.execute("SELECT reader, basis, printed_text, ocr_confirmed, check_note FROM figure_facts WHERE id = ?",
                            [aid]).fetchone()
            d.update(dict(zip(("reader", "basis", "printed_text", "ocr_confirmed", "check_note"), r)))
    elif a["kind"] == "line" and a["parent"]:
        d["figure"] = con.execute("SELECT label FROM figures WHERE id = ?", [a["parent"]]).fetchone()[0]
    elif a["kind"] == "const":
        d["value"] = con.execute("SELECT value FROM consts WHERE id = ?", [aid]).fetchone()[0]
    return d


def _describe_span(con, span) -> dict:
    """A quote that runs across several atoms: the first atom's description, every atom in order,
    their own texts, and the union box when they share a page."""
    d = _describe(con, span[0])
    if len(span) > 1:
        rows = {r[0]: r[1:] for r in con.execute(
            f"SELECT id, text, page, x0, top, x1, bottom FROM atoms WHERE id IN ({', '.join('?' * len(span))})",
            list(span)).fetchall()}
        d["atoms"] = list(span)
        d["text"] = " ".join(rows[a][0] for a in span)
        if len({rows[a][1] for a in span}) == 1 and all(rows[a][2] is not None for a in span):
            d["bbox"] = [round(min(rows[a][2] for a in span), 1), round(min(rows[a][3] for a in span), 1),
                         round(max(rows[a][4] for a in span), 1), round(max(rows[a][5] for a in span), 1)]
    return d


def _span_name(span) -> str:
    return span[0] if len(span) == 1 else f"{span[0]}–{span[-1]}"


# ─────────────────────────── quotes ───────────────────────────

# Characters that belong to a number they touch: a quote may not start a number right after one of
# these, nor end a number right before a percent sign or before one of the joiners and a digit.
_ATTACH_BEFORE = set("~±≈<>≤≥+−-–—./,×^")
_ATTACH_AFTER = set("%‰")
_JOIN_AFTER = set(".,–-—−/×^:")


# A glyph the PDF's font maps to no character: pdfminer writes "(cid:N)". It is often a minus sign
# or another symbol, so a number right after one may have lost its sign.
_UNMAPPED_BEFORE = re.compile(r"\(cid:\d+\)\s*$")


def _after_unmapped(text: str, i: int) -> bool:
    return text[i].isdigit() and bool(_UNMAPPED_BEFORE.search(text[:i]))


def _clean_cut(text: str, i: int, j: int) -> bool:
    """A quote may not cut through a word or a number. "9" out of "98", "5" out of "1.5", "100 nm"
    out of "90–100 nm", "98" out of "~98" or "85.2" out of "85.2%" would each show the reader a
    statement the document does not make."""
    q0, q1 = text[i], text[j - 1]
    if _after_unmapped(text, i):
        return False
    before = text[i - 1] if i > 0 else ""
    after = text[j] if j < len(text) else ""
    after2 = text[j + 1] if j + 1 < len(text) else ""
    if before and ((q0.isalnum() and before.isalnum()) or (q0.isdigit() and before in _ATTACH_BEFORE)):
        return False
    if after and ((q1.isalnum() and after.isalnum())
                  or (q1.isdigit() and (after in _ATTACH_AFTER or (after in _JOIN_AFTER and after2.isdigit())))):
        return False
    return True


def _holds(text: str, quote: str) -> bool:
    i = text.find(quote)
    while i != -1:
        if _clean_cut(text, i, i + len(quote)):
            return True
        i = text.find(quote, i + 1)
    return False


def fold(text: str) -> str:
    """Text as a search compares it: Unicode compatibility forms unified (NFKC: the micro sign and
    Greek mu, ligatures, full-width digits) and case removed. Searches only; a quote stays exact."""
    return unicodedata.normalize("NFKC", text).casefold()


# A line that ends in one of these continues on the next line without a space; a hyphen there may
# also be a typesetter's line-break hyphen ("spe-" + "cific"). Every joining is tried, none chosen.
_TIGHT_END = ("-", "\u2010", "\u2011", "\u00ad", "/")
_HYPHEN_END = ("-", "\u2010", "\u2011", "\u00ad")
JOIN_MODES = ("tight", "dehyphen", "spaced")


def _join(seg, mode):
    """One segment's texts joined under one mode: (text, start offset of each atom)."""
    parts, starts, pos = [], [], 0
    for k, (_, t) in enumerate(seg):
        if k:
            prev = seg[k - 1][1]
            sep = " "
            if mode != "spaced" and prev.endswith(_TIGHT_END):
                sep = ""
                if mode == "dehyphen" and prev.endswith(_HYPHEN_END):
                    parts[-1] = parts[-1][:-1]
                    pos -= 1
            parts.append(sep)
            pos += len(sep)
        starts.append(pos)
        parts.append(t)
        pos += len(t)
    return "".join(parts), starts


class Flows:
    """Text that runs on across atoms, so a phrase broken by a line end is still one phrase.

    QUOTES read a page's lines in reading order: consecutive lines are one continuous text. They do
    NOT read down a table column — consecutive printed rows may be one wrapped cell ("143.47 ±" /
    "10.34 nm") or two different table rows ("Ni-10" / "Ni-20"), and nothing in the drawing says
    which, so a quote stays inside one cell (a wrapped cell is quoted piece by piece).
    SEARCHES (absent) read both, and table columns down consecutive rows too: over-joining can only
    make a search find more, so an absence claim errs toward being refused, never toward passing."""

    def __init__(self, con):
        self.lines = []
        cur, key = [], None
        # one page of one paper is one flow; in a corpus an id starts with its paper's key ("ensm-2021:p3.L5")
        for aid, doc, page, text in con.execute(
                "SELECT id, CASE WHEN contains(id, ':') THEN split_part(id, ':', 1) ELSE '' END AS doc, page, text "
                "FROM lines ORDER BY doc, page, line_no").fetchall():
            if (doc, page) != key and cur:
                self.lines.append(cur)
                cur = []
            key = (doc, page)
            cur.append((aid, text))
        if cur:
            self.lines.append(cur)
        self.columns = []
        cur, prev = [], None
        for aid, tid, col, row, text in con.execute(
                "SELECT id, table_id, col_no, row_no, text FROM cells ORDER BY table_id, col_no, row_no").fetchall():
            if cur and (prev[0] != (tid, col) or row != prev[1] + 1):
                self.columns.append(cur)
                cur = []
            prev = ((tid, col), row)
            cur.append((aid, text))
        if cur:
            self.columns.append(cur)
        self.exact = [[_join(s, m) for m in JOIN_MODES] for s in self.lines]
        self.lower = [[_join([(a, fold(t)) for a, t in s], m) for m in JOIN_MODES] for s in self.lines + self.columns]

    def _spans(self, segments, joined, needle, clean):
        out = []
        for seg, variants in zip(segments, joined):
            for text, starts in variants:
                i = text.find(needle)
                while i != -1:
                    j = i + len(needle)
                    if not clean or _clean_cut(text, i, j):
                        a, b = bisect_right(starts, i) - 1, bisect_right(starts, j - 1) - 1
                        span = tuple(x[0] for x in seg[a:b + 1])
                        if span not in out:
                            out.append(span)
                    i = text.find(needle, i + 1)
        return out

    def near(self, words):
        """Spans of at most NEAR_WINDOW_ATOMS consecutive atoms (lines, or one column's rows) whose words
        include every one of `words`, ignoring case, Unicode forms and line-end hyphens."""
        out = []
        for seg in self.lines + self.columns:
            for i, size in ((i, k) for i in range(len(seg)) for k in range(1, NEAR_WINDOW_ATOMS + 1)):
                window = seg[i:i + size]
                if len(window) < size:
                    continue
                folded = [(a, fold(t)) for a, t in window]
                have = set()
                for mode in ("dehyphen", "spaced"):
                    have.update(_WORDS.findall(_join(folded, mode)[0]))
                if words <= have:
                    span = tuple(a for a, _ in window)
                    if span not in out:
                        out.append(span)
        # report the smallest places: drop a window that contains another reported one
        return [sp for sp in out if not any(o != sp and set(o) <= set(sp) for o in out)]

    def quote_spans(self, quote):
        """Minimal spans of body lines that hold the quote verbatim, cut cleanly."""
        return self._spans(self.lines, self.exact, quote, clean=True)

    def mentions(self, term):
        """Spans of lines, or of one column's consecutive cells, where the term occurs at all, ignoring
        case and Unicode compatibility forms (µ and μ, ﬁ and fi)."""
        return self._spans(self.lines + self.columns, self.lower, fold(term), clean=False)


_STRIP = "()[]{},.;:!?\"'“”‘’"


def _is_name(quote: str) -> bool:
    """One token that contains a letter: a name like 4-MPBA, Ni-10 or HGNRs, not a number or a phrase."""
    return not re.search(r"\s", quote) and bool(re.search(r"[^\W\d_]", quote))


def _where_written(con, flows, token):
    """An atom that holds `token` as a whole token, or None."""
    spans = flows().quote_spans(token)
    if spans:
        return spans[0][0]
    for (h,) in con.execute("SELECT id FROM atoms WHERE kind <> 'line' AND contains(text, ?) ORDER BY id LIMIT 20",
                            [token]).fetchall():
        if _holds(_atom(con, h)["text"], token):
            return h
    return None


def _clause_lines(con, aid):
    """("sentence" | "value", its lines) when `aid` is a sentence or measure id of the attached clause base."""
    if not isinstance(aid, str) or not has_clauses(con):
        return None
    for rel, name in (("sentences", "sentence"), ("measures", "value")):
        row = con.execute(f"SELECT atoms FROM {rel} WHERE id = ?", [aid]).fetchone()
        if row and row[0]:
            return name, list(row[0])
    return None


# ─────────────────────────── wrapped table cells ───────────────────────────

# A table row whose text wraps is printed on several lines; the extractor gives each printed line its own
# row_no. A printed row CONTINUES the row above it when it fills at most half of the table's columns, only
# columns that hold text on the printed row right above it (a wrap carries on a cell already begun; a new
# entry under a group label starts a cell of its own, like the reference of a new row), and is not one line
# of text running across columns (a sub-heading split at a column boundary: its pieces touch). Then a cell's
# pieces are the consecutive printed rows of that table row with text in the cell's column.
WRAP_MAX_SHARE = 0.5
SPANNING_GAP = 0.5        # pieces closer than this many line heights are one line across columns
INTERLEAVED_STEP = 0.6    # printed rows closer than this share of the table's usual line step interleave


def _wrap_rows(con, tid, cache):
    """{row_no: {col_no: (id, text)}} of the table's printed rows, and {row_no: row_no of the row it continues
    or its own}."""
    if tid in cache:
        return cache[tid]
    n_cols = con.execute("SELECT count(*) FROM table_columns WHERE table_id = ?", [tid]).fetchone()[0]
    rows, geo, header = {}, {}, {}
    for cid, r, c, hdr, text, x0, top, x1, bottom in con.execute(
            "SELECT id, row_no, col_no, is_header, text, x0, top, x1, bottom FROM cells WHERE table_id = ? "
            "AND text IS NOT NULL AND trim(text) <> '' ORDER BY row_no, col_no", [tid]).fetchall():
        rows.setdefault(r, {})[c] = (cid, text)
        geo.setdefault(r, []).append((c, x0, x1, (bottom - top) if top is not None and bottom is not None else None))
        header[r] = header.get(r, True) and bool(hdr)
    n_cols = max(n_cols, max((c for cols in rows.values() for c in cols), default=0))
    tops = [t for (t,) in con.execute("SELECT min(top) FROM cells WHERE table_id = ? AND text IS NOT NULL AND "
                                      "trim(text) <> '' GROUP BY row_no ORDER BY row_no", [tid]).fetchall()
            if t is not None]
    steps = sorted(b - a for a, b in zip(tops, tops[1:]) if b > a)
    # a short cell printed beside the middle of its row (a name centred on a several-line entry) puts its
    # line between two printed lines: then the printed rows do not say where an entry starts, and no row
    # is read as continuing another
    interleaved = bool(steps) and steps[0] < INTERLEAVED_STEP * steps[len(steps) // 2]
    head, group = None, {}
    for r in sorted(rows):
        g = sorted(geo[r])
        spanning = any(b[0] == a[0] + 1 and None not in (a[2], b[1], a[3]) and b[1] - a[2] < SPANNING_GAP * a[3]
                       for a, b in zip(g, g[1:]))
        continues = (not interleaved and head is not None and not header[r] and not header[head] and r == max(group) + 1
                     and len(rows[r]) <= WRAP_MAX_SHARE * n_cols and not spanning and set(rows[r]) <= set(rows[r - 1]))
        if not continues:
            head = r
        group[r] = head
    cache[tid] = (rows, group)
    return cache[tid]


def wrap_pieces(con, cid, cache=None) -> list[str]:
    """The cell ids of the wrapped cell that `cid` is a piece of, in printed order (just [cid] when it does
    not wrap)."""
    cache = {} if cache is None else cache
    row = con.execute("SELECT table_id, row_no, col_no FROM cells WHERE id = ?", [cid]).fetchone()
    if row is None:
        return [cid]
    tid, r, c = row
    rows, group = _wrap_rows(con, tid, cache)
    if r not in rows or c not in rows[r]:
        return [cid]
    run = [r]
    while run[0] - 1 in rows and group.get(run[0] - 1) == group[r] and c in rows[run[0] - 1]:
        run.insert(0, run[0] - 1)
    while run[-1] + 1 in rows and group.get(run[-1] + 1) == group[r] and c in rows[run[-1] + 1]:
        run.append(run[-1] + 1)
    return [rows[k][c][0] for k in run]


def _wrapped_quote(con, cid, quote):
    """The span of a wrapped cell's pieces that holds the quote, read down the cell, through `cid`."""
    pieces = wrap_pieces(con, cid)
    if len(pieces) < 2:
        return None
    texts = dict(con.execute(f"SELECT id, text FROM cells WHERE id IN ({', '.join('?' * len(pieces))})",
                             pieces).fetchall())
    seg = [(p, texts[p]) for p in pieces]
    for mode in JOIN_MODES:
        text, starts = _join(seg, mode)
        i = text.find(quote)
        while i != -1:
            j = i + len(quote)
            if _clean_cut(text, i, j):
                a, b = bisect_right(starts, i) - 1, bisect_right(starts, j - 1) - 1
                span = tuple(pieces[a:b + 1])
                if cid in span and len(span) > 1:
                    return span
            i = text.find(quote, i + 1)
    return None


def _cut_cell(con, entry, shown, cache):
    """For a shown quote of a table cell that stops exactly where its cell goes on to another printed row (it
    begins a piece that has one above, or ends a piece that has one below) and the answer does not show that
    next piece: (the piece, the side, the piece's text). A quote that runs into the next piece, or stops
    inside a piece, cuts nothing there."""
    src = entry.get("source") or {}
    atoms = src.get("atoms") or [src.get("atom")]
    if src.get("kind") != "cell":
        return None
    first, last = wrap_pieces(con, atoms[0], cache), wrap_pieces(con, atoms[-1], cache)
    if len(first) < 2 and len(last) < 2:
        return None
    ids = list(dict.fromkeys(first + last))
    texts = dict(con.execute(f"SELECT id, text FROM cells WHERE id IN ({', '.join('?' * len(ids))})", ids).fetchall())
    quote, seg = entry["quote"], [(a, texts[a]) for a in atoms]
    begins = any(_join(seg, mode)[0].strip().startswith(quote) for mode in JOIN_MODES)
    ends = any(_join(seg, mode)[0].strip().endswith(quote) for mode in JOIN_MODES)
    i, j = first.index(atoms[0]), last.index(atoms[-1])
    if begins and i > 0 and first[i - 1] not in shown:
        return first[i - 1], "above", texts[first[i - 1]]
    if ends and j + 1 < len(last) and last[j + 1] not in shown:
        return last[j + 1], "below", texts[last[j + 1]]
    return None


# ─────────────────────────── hidden citations ───────────────────────────

# A support quote or an absence search is cited, not shown. Words that only lead into it leave the reader
# without the thing they lead to: "it reports that[1]", "the LOD was OD600 =[3]". The words before the mark
# (and before any marks right ahead of it) end in an opener or a lead-in word, and what follows is not a
# shown quote that completes them ("is[4] 5 L fed-batch fermentation[5]" shows the words at [5]).
LEAD_IN = frozenset("""that is was are were be of at to by from with as and or the a an about around
    approximately roughly near reads read states stated says said writes gives given reports reported
    labelled labeled named called its their""".split())
LEAD_OPENERS = (":", "“", "‘", "(", "[", "=", "≈", "~")
_STRAIGHT = ('"', "'")                 # open a quotation only after a space or an opener ("matrix\"[1]" closes one)
_MARK = re.compile(r"\[(\d+)\]")
_LAST_WORD = re.compile(r"([^\W\d_]+)$")


def lead_in_gaps(text: str, citations: list) -> list[tuple[int, str]]:
    """(citation number, the words before its mark) for every hidden citation the words lead into."""
    cites = {c["n"]: c for c in citations or []}
    hidden = {n for n, c in cites.items() if c["kind"] in ("support", "search")}
    out = []
    for m in _MARK.finditer(text or ""):
        n = int(m.group(1))
        if n not in hidden:
            continue
        before = text[:m.start()]
        while re.search(r"\[\d+\]$", before):           # "that[1][2]": read past the marks ahead of this one
            before = re.sub(r"\[\d+\]$", "", before)
        tail = before.rstrip()
        last = _LAST_WORD.search(tail)
        opens = tail.endswith(LEAD_OPENERS) or (tail.endswith(_STRAIGHT) and (len(tail) == 1 or tail[-2] in " (\n"))
        if not tail or not (opens or (last and last.group(1).casefold() in LEAD_IN)):
            continue
        after = re.match(r"(?:\[\d+\])*([^\[]*)\[(\d+)\]", text[m.end():])
        if after and int(after.group(2)) not in hidden and \
                after.group(1).strip() == str(cites.get(int(after.group(2)), {}).get("rendered", "")).strip() != "":
            continue                                       # a shown quote completes the words
        out.append((n, tail[-40:]))
    return out


def check_quote(con, item, where, flows) -> dict:
    """Where the quote is verbatim: the named atom, a run of consecutive lines through it, or — when
    the named place misses — the one place in the document that holds it. Raises Refusal."""
    if not isinstance(item, dict):
        raise Refusal("quote:shape", "a quote must be an object {\"quote\": ..., \"atom\": ...}", where=where)
    quote, aid = item.get("quote"), item.get("atom")
    if not isinstance(quote, str) or not quote.strip():
        raise Refusal("quote:empty", "the quote is empty", ["copy the exact characters from the atom's text"], where)
    if not isinstance(aid, str):
        raise Refusal("quote:atom", "the quote names no atom", ["set \"atom\" to the id of the atom whose text holds it"], where)
    atom = _atom(con, aid)
    if atom is not None and atom["text"] is not None and _holds(atom["text"], quote):
        return _describe(con, aid)
    spans = flows().quote_spans(quote)
    mine = [s for s in spans if aid in s]
    if len(mine) == 1:
        return _describe_span(con, mine[0])
    others = [(h,) for (h,) in con.execute(
        "SELECT id FROM atoms WHERE kind <> 'line' AND contains(text, ?) ORDER BY id LIMIT 50",
        [quote]).fetchall() if _holds(_atom(con, h)["text"], quote)]
    candidates = mine or (spans + others)
    if not mine and len(candidates) == 1:
        d = _describe_span(con, candidates[0])
        d["relocated_from"] = aid
        return d
    if not mine and len(candidates) > 1 and _is_name(quote):
        # a single word or name ("4-MPBA") is the same characters wherever it occurs: cite its first
        # occurrence rather than refuse. A number, or a phrase, still has to name its place.
        d = _describe_span(con, candidates[0])
        d.update({"relocated_from": aid, "occurrences": len(candidates)})
        return d
    # v5: where v4 refused. Down the printed rows of one wrapped cell, and by a clause-base id.
    if atom is not None and atom["kind"] == "cell":
        span = _wrapped_quote(con, aid, quote)
        if span:
            return _describe_span(con, span)
    named = _clause_lines(con, aid) if atom is None else None
    if named:
        kind_named, lines = named
        inside = [s for s in spans if set(s) & set(lines)]
        if len(inside) == 1:
            d = _describe_span(con, inside[0])
            d.update({"relocated_from": aid, "named_by": kind_named})
            return d
        if inside:
            candidates = inside
    if atom is None and named:
        why = (f"there is no atom {aid!r}: it is a {named[0]} of the clause base, on line(s) {', '.join(named[1])}, "
               + ("and those lines do not hold " if not candidates or not set(named[1]) & {a for c in candidates for a in c}
                  else "and those lines hold ") + f"{quote!r}" + (" more than once" if len(candidates) > 1 and
                                                                    set(named[1]) & {a for c in candidates for a in c} else ""))
    elif atom is None:
        why = f"there is no atom {aid!r}"
    elif atom["text"] is not None and quote in atom["text"] and _after_unmapped(atom["text"], atom["text"].find(quote)):
        why = (f"{quote!r} follows an unmapped glyph in {aid} ({atom['text'][:300]!r}): the PDF's font does not say "
               "which character it is, and it is often a minus sign, so the number alone may have lost its sign")
    elif atom["text"] is not None and quote in atom["text"]:
        why = f"{quote!r} occurs in {aid} only as part of a longer word or number (its text: {atom['text'][:300]!r})"
    else:
        why = f"{aid} does not contain {quote!r}; its text is {(atom['text'] or '')[:600]!r}"
    if len(candidates) > 1:
        names = [_span_name(s) for s in candidates]
        moves = [f"the quote is verbatim in {len(names)} places ({', '.join(names[:8])}{', …' if len(names) > 8 else ''}): "
                 "set \"atom\" to the one you mean"]
    elif atom is not None and atom["text"] and _after_unmapped(atom["text"], max(atom["text"].find(quote), 0)):
        glyph = _UNMAPPED_BEFORE.search(atom["text"][:atom["text"].find(quote)]).group().strip()
        moves = [f"quote the number together with the glyph, e.g. {glyph + ' ' + quote!r}, and say in your own words "
                 "that the sign is not legible in the PDF"]
    else:
        moves = ["copy the characters exactly as the document has them (whole words and whole numbers); a quote "
                 "may continue across a line break, and a hyphen at a line end may be kept or dropped",
                 "look the text up first: SELECT id, text FROM atoms WHERE text ILIKE '%<a word of it>%'"]
    raise Refusal("quote:absent", why, moves, where)


def check_absent(con, terms, where, flows) -> dict:
    """A search citation: every term occurs nowhere in the document. Raises Refusal."""
    if not isinstance(terms, list) or not terms:
        raise Refusal("absent:shape", "absent must be a non-empty list of search terms",
                      ["list the words the document would use if it said this, e.g. [\"mg/kg\", \"dose\"]"], where)
    bad = [t for t in terms if not isinstance(t, str) or not t.strip() or len(t) > MAX_TERM_CHARS]
    if bad:
        raise Refusal("absent:term", f"each term must be non-empty text of at most {MAX_TERM_CHARS} characters; got {bad[:3]!r}",
                      ["send short search terms"], where)
    found = {}
    for t in terms:
        hits = flows().mentions(t) + [(h,) for h, text in con.execute(
            "SELECT id, text FROM atoms WHERE kind NOT IN ('line', 'cell') AND text IS NOT NULL ORDER BY id").fetchall()
            if fold(t) in fold(text)]
        if hits:
            found[t] = hits
    if found:
        where_found = "; ".join(f"{t!r} at {', '.join(_span_name(s) for s in h[:6])}{', …' if len(h) > 6 else ''}"
                                for t, h in found.items())
        raise Refusal("absent:found", f"the document does contain what the search was for: {where_found}",
                      ["read those atoms: the document may say what you claim it does not — quote it instead",
                       "or narrow the claim (and its terms) to what really is missing"], where)
    # A term can miss only because the document words it differently ("detection limit" vs "limit of
    # detection"). When all of a term's words occur together nearby, the search proves nothing.
    near = {}
    for t in terms:
        words = {w for w in _WORDS.findall(fold(t)) if len(w) >= NEAR_MIN_WORD_CHARS}
        if len(words) < 2:
            continue                                   # a single word is already covered by the exact search
        hits = flows().near(words) + [(h,) for h, text in con.execute(
            "SELECT id, text FROM atoms WHERE kind NOT IN ('line', 'cell') AND text IS NOT NULL ORDER BY id").fetchall()
            if words <= set(_WORDS.findall(fold(text)))]
        if hits:
            near[t] = hits
    if near:
        said = []
        for t, h in near.items():
            first = h[0][0]
            text = (_atom(con, first) or {}).get("text") or ""
            said.append(f"the words of {t!r} occur together at {', '.join(_span_name(s) for s in h[:6])}"
                        f"{', …' if len(h) > 6 else ''} (e.g. {first}: {text[:120]!r})")
        raise Refusal("absent:near", "the document may say this in other words: " + "; ".join(said),
                      ["read those atoms: if they say it, quote them instead of claiming it is absent",
                       "if they are about something else, say what IS there (quote it) and search for the exact "
                       "wording the missing thing would have"], where)
    n = con.execute("SELECT count(*) FROM atoms").fetchone()[0]
    return {"kind": "search", "terms": list(terms), "matches": 0, "scope": SEARCH_SCOPE,
            "atoms_searched": n, "strength": "search"}


# The judge's reading of a value, kept with its citation: what the reader is told the clause base says.
MEASURE_READING = ("role", "role_p", "property", "property_p", "about", "method", "quantity", "sentence")


def check_measure(con, mid, where, flows) -> dict:
    """A value of the clause base shown by id: its text, quoted from the line(s) it was read from, with
    the judge's reading of it. The text must resolve there exactly as a quote run would; a value whose
    text the door would refuse as a quote (a cut through a longer number, a sign lost to an unmapped
    glyph) is refused here too. Raises Refusal."""
    if not has_clauses(con):
        raise Refusal("measure:no-clause-base", "this document has no clause base attached, so there are no measure ids",
                      ["quote the value instead: {\"quote\": \"<exact text>\", \"atom\": \"<id>\"}"], where)
    cols = ("id", "text", "atoms") + MEASURE_READING
    row = con.execute(f"SELECT {', '.join(cols)} FROM measures WHERE id = ?", [mid]).fetchone() \
        if isinstance(mid, str) else None
    if row is None:
        raise Refusal("measure:absent", f"there is no measure {mid!r}",
                      ["copy the id exactly from the leads, or look it up: SELECT id, text, about FROM measures WHERE ..."], where)
    m = dict(zip(cols, row))
    try:
        d = check_quote(con, {"quote": m["text"], "atom": m["atoms"][0]}, where, flows)
    except Refusal as r:
        raise Refusal("measure:cut", f"measure {mid} reads {m['text']!r} as a value, but it cannot be shown as it is: {r.why}",
                      r.moves + ["or quote the value yourself with a quote run, as the line has it"], where)
    if d.get("relocated_from") or not set(d.get("atoms") or [d["atom"]]) & set(m["atoms"]):
        raise Refusal("measure:cut", f"measure {mid}'s text {m['text']!r} is not where the clause base read it ({', '.join(m['atoms'])})",
                      ["quote the value yourself with a quote run, from the line that holds it"], where)
    reading = {k: (round(m[k], 2) if k.endswith("_p") and m[k] is not None else m[k]) for k in MEASURE_READING}
    return {"text": m["text"], "source": d, "reading": {**reading, "read_by": "judge"}}


# ─────────────────────────── values ───────────────────────────

def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float, Decimal)):
        return None
    return Decimal(str(v))


def render_value(v, fmt) -> str:
    if fmt == "raw":
        return str(v)
    d = _num(v)
    if d is None:
        raise ValueError(f"fmt {fmt!r} needs a number, the value is {type(v).__name__} {str(v)[:60]!r}")
    if not d.is_finite():
        raise ValueError("the value is not a finite number")
    if fmt == "int":
        return f"{d.quantize(Decimal('1'), ROUND_HALF_UP):,}"
    if fmt.startswith("fixed"):
        n = int(fmt[5:])
        return f"{d.quantize(Decimal(1).scaleb(-n), ROUND_HALF_UP):,}"
    n = int(fmt[3:])
    return f"{(d * 100).quantize(Decimal(1).scaleb(-n), ROUND_HALF_UP):,}%"


def _json_safe(v):
    if isinstance(v, (bool, int, str)) or v is None:
        return v
    if isinstance(v, float):
        return v
    return str(v)


def _weakest(strengths) -> str:
    """The weakest strength among the sources; verbatim when every source is verbatim or canon."""
    worst = max((STRENGTH_RANK.get(s, 9) for s in strengths), default=0)
    if worst == 0:
        return "verbatim"
    return next(s for s in strengths if STRENGTH_RANK.get(s, 9) == worst)


# ─────────────────────────── the door ───────────────────────────

def check(doc, con, door: str = DOOR_VERSION) -> Checked:
    """Check a submission under door `door` (the current one, or one of RECHECKS for a stored answer)."""
    refusals, pieces, cites = [], [], []
    built, run_of = [], {}
    level = int(door) if str(door).isdigit() else int(DOOR_VERSION)   # rules added by door N apply from N on

    def flows():
        if not built:
            built.append(Flows(con))
        return built[0]

    def cite(entry, rendered):
        entry["n"] = len(cites) + 1
        entry["rendered"] = rendered
        cites.append(entry)
        run_of[entry["n"]] = where
        return f"[{entry['n']}]"

    runs = doc.get("runs") if isinstance(doc, dict) else None
    if not isinstance(runs, list) or not runs:
        got = ("runs arrived as a string (text that holds a list), not as a list" if isinstance(runs, str)
               else "runs is missing" if runs is None else f"runs arrived as {type(runs).__name__}, not a list"
               if not isinstance(runs, list) else "runs is an empty list")
        return Checked(False, refusals=[Refusal("answer:shape", f"the answer must be {{\"runs\": [ ...non-empty list of runs... ]}}; {got}",
                                                ["send the list itself: {\"runs\": [{\"text\": \"...\"}, {\"quote\": \"...\", \"atom\": \"...\"}]}, "
                                                 "not {\"runs\": \"[...]\"}",
                                                 "send runs of the kinds text / quote / measure / sql / figure / table"])])
    if len(runs) > MAX_RUNS:
        return Checked(False, refusals=[Refusal("answer:size", f"{len(runs)} runs; at most {MAX_RUNS}", ["shorten the answer"])])
    for i, run in enumerate(runs):
        where = f"runs[{i}]"
        kinds = [k for k in RUN_FIELDS if isinstance(run, dict) and k in run]
        if len(kinds) != 1:
            refusals.append(Refusal("run:kind", f"a run must carry exactly one of {list(RUN_FIELDS)}, got {sorted(run) if isinstance(run, dict) else type(run).__name__}",
                                    ["split it into separate runs"], where))
            continue
        kind = kinds[0]
        extra = set(run) - RUN_FIELDS[kind]
        if extra:
            refusals.append(Refusal("run:fields", f"a {kind} run takes {sorted(RUN_FIELDS[kind])}; unexpected {sorted(extra)}",
                                    [f"remove {sorted(extra)}"], where))
            continue
        try:
            if kind == "text":
                text = run["text"]
                if not isinstance(text, str):
                    raise Refusal("text:shape", "text must be a string", where=where)
                so_far = "".join(pieces)
                nums = prose_numbers(text, line_start=not so_far or so_far.endswith("\n"))
                if nums:
                    ready = []
                    for tok in nums:
                        core = tok.strip(_STRIP)
                        if core and any(ch.isdigit() for ch in core):
                            loc = _where_written(con, flows, core)
                            if loc:
                                ready.append(f"{core!r} is written exactly so in the document (e.g. {loc}): if that is "
                                             f"what you mean (a name like this, or that value), quote it: "
                                             f"{{\"quote\": \"{core}\", \"atom\": \"{loc}\"}} — never shorten it")
                    raise Refusal("text:number", f"your own words contain number(s) {nums} — a number must come from the document, in digits or in words",
                                  ready + ["move each number into a quote run: {\"quote\": \"<exact characters>\", \"atom\": \"<id>\"}",
                                   "or compute it in a sql run (counts, sums, conversions)",
                                   "or say it without a number (\"several\", \"a\", \"each\")"], where)
                support = run.get("support") or []
                if not isinstance(support, list):
                    raise Refusal("text:support", "support must be a list of {atom, quote}", where=where)
                marks = ""
                for k, s in enumerate(support):
                    d = check_quote(con, s, f"{where}.support[{k}]", flows)
                    marks += cite({"kind": "support", "quote": s["quote"], "source": d,
                                   "strength": d.get("strength")}, s["quote"])
                if "absent" in run:
                    marks += cite(check_absent(con, run["absent"], f"{where}.absent", flows), "")
                body = text.rstrip()                   # a citation mark sits on the words, not after a line break
                pieces.append(body + marks + text[len(body):])
            elif kind in ("quote", "measure"):
                of = run.get("of")
                if "of" in run and (not isinstance(of, str) or not of.strip() or len(of) > MAX_OF_CHARS):
                    raise Refusal("quote:of", f"`of` names what the value is given for, as the document names it "
                                  f"(a non-empty string of at most {MAX_OF_CHARS} characters); got {of!r}",
                                  ["write the material, sample or condition, e.g. \"of\": \"NFA 811\"",
                                   "or leave `of` out"], where)
                if kind == "quote":
                    shown, d = run["quote"], check_quote(con, run, where, flows)
                    entry = {"kind": "quote", "quote": shown, "source": d, "strength": d.get("strength")}
                else:
                    m = check_measure(con, run["measure"], where, flows)
                    shown, d = m["text"], m["source"]
                    entry = {"kind": "quote", "quote": shown, "source": d, "strength": d.get("strength"),
                             "measure": run["measure"], "reading": m["reading"]}
                if "of" in run:
                    entry["of"] = of.strip()
                pieces.append(shown + cite(entry, shown))
            elif kind == "sql":
                fmt = run.get("fmt", "raw")
                if not isinstance(fmt, str) or not FMT.match(fmt):
                    raise Refusal("sql:fmt", f"fmt {fmt!r} is not one of raw, int, fixed0-6, pct0-3",
                                  ["use raw for text or exact numbers, fixedN for N decimals, pctN for a fraction shown as %"], where)
                value, sources, _ = lineage.cited_value(con, run.get("sql"), run.get("column"), run.get("row", 0))
                try:
                    shown = render_value(value, fmt)
                except ValueError as e:
                    raise Refusal("sql:fmt", str(e), ["use fmt raw for a text value"], where)
                if level >= 6 and fmt.startswith("pct") and _TIMES_100.search(_SQL_STRING.sub("''", run["sql"])):
                    meant = render_value(value, "fixed" + fmt[3:]) + "%"
                    raise Refusal("sql:pct-scaled",
                                  f"fmt {fmt} shows a fraction as a percent by multiplying it by 100, and this sql already "
                                  f"multiplies by 100: the answer would show {shown} where the value is {meant}",
                                  [f"keep the * 100 and use fmt fixed{fmt[3:]} (the value is already in percent; write % in "
                                   "your words after it)",
                                   f"or drop the * 100 and keep fmt {fmt}"], where)
                described = [_describe(con, s) for s in sources]
                pieces.append(shown + cite({"kind": "computed", "sql": run["sql"], "column": run.get("column"),
                                            "row": run.get("row", 0), "fmt": fmt, "value": _json_safe(value),
                                            "strength": f"computed from {_weakest([d.get('strength') for d in described])}",
                                            "n_sources": len(described), "sources": described[:60]}, shown))
            elif kind == "table":
                tid = run["table"]
                row = con.execute("SELECT id, label, page, caption, x0, top, x1, bottom FROM tables WHERE id = ?",
                                  [tid]).fetchone() if isinstance(tid, str) else None
                if row is None:
                    ids = [r[0] for r in con.execute("SELECT id FROM tables ORDER BY page").fetchall()]
                    raise Refusal("table:absent", f"there is no table {tid!r}", [f"use one of {ids}"], where)
                shown = re.sub(r"\s*\(continued\)$", "", row[1])
                pieces.append(shown + cite({"kind": "table", "source": {
                    "atom": row[0], "kind": "table", "label": row[1], "page": row[2], "caption": row[3],
                    "bbox": [round(v, 1) for v in row[4:8]], "strength": "verbatim", **_paper(con, row[0])},
                    "strength": "verbatim"}, shown))
            else:
                fid = run["figure"]
                row = con.execute("SELECT id, label, page, caption, png, png_pixels_sha256, x0, top, x1, bottom "
                                  "FROM figures WHERE id = ?", [fid]).fetchone() if isinstance(fid, str) else None
                if row is None:
                    ids = [r[0] for r in con.execute("SELECT id FROM figures WHERE label IS NOT NULL ORDER BY page").fetchall()]
                    raise Refusal("figure:absent", f"there is no figure {fid!r}", [f"use one of {ids}"], where)
                shown = row[1] or row[0]
                pieces.append(shown + cite({"kind": "figure", "source": {
                    "atom": row[0], "kind": "figure", "label": row[1], "page": row[2], "caption": row[3],
                    "png": row[4], "png_pixels_sha256": row[5], "bbox": [round(v, 1) for v in row[6:10]],
                    "strength": "verbatim", **_paper(con, row[0])}, "strength": "verbatim"}, shown))
        except Refusal as r:
            r.where = r.where or where
            refusals.append(r)
        except Exception as e:                       # the door says no; it never crashes
            refusals.append(Refusal("checker:error", f"the checker could not read this run ({type(e).__name__}: {str(e)[:200]})",
                                    ["check the run's shape against the answer format"], where))
    if refusals:
        return Checked(False, refusals=refusals)
    text = "".join(pieces)
    if level >= 5:
        refusals = _whole_cells(con, cites, run_of) + _lead_ins(text, cites, run_of)
        if refusals:
            return Checked(False, refusals=refusals)
    return Checked(True, text, cites)


def _whole_cells(con, cites, run_of) -> list[Refusal]:
    shown = {a for c in cites if c["kind"] == "quote"
             for a in (c["source"].get("atoms") or [c["source"].get("atom")])}
    out, cache = [], {}
    for c in cites:
        if c["kind"] != "quote":
            continue
        cut = _cut_cell(con, c, shown, cache)
        if not cut:
            continue
        piece, side, text = cut
        src = c["source"]
        at = (src.get("atoms") or [src["atom"]])[0 if side == "above" else -1]
        joined = f"{text} {c['quote']}" if side == "above" else f"{c['quote']} {text}"
        out.append(Refusal(
            "quote:wrapped",
            f"{c['quote']!r} stops where its table cell goes on to the printed row {side} it: the cell continues "
            f"{'from' if side == 'above' else 'with'} {piece} {text!r} (a printed row that fills at most half of the "
            f"table's columns, all under text on the row above, continues that row), so the reader would see part of "
            f"the cell",
            ["run the quote across the row break: " + json.dumps({"quote": joined, "atom": at}, ensure_ascii=False),
             f"or show {piece} with a quote run of its own, next to this one",
             "if that piece belongs to a different entry of the table, show it too and say so in your words"],
            run_of[c["n"]]))
    return out


def _lead_ins(text, cites, run_of) -> list[Refusal]:
    out = []
    for n, tail in lead_in_gaps(text, cites):
        kind = next(c["kind"] for c in cites if c["n"] == n)
        what = "support quote" if kind == "support" else "absence search"
        out.append(Refusal(
            "text:lead-in",
            f"the words before citation [{n}] end in {tail[-25:]!r} and lead into its {what}, which the reader does "
            f"not see: support quotes and searches are cited, not shown, so the answer reads {tail[-25:] + f'[{n}]'!r}",
            ["show the words the reader needs as a quote run right after the text: "
             "{\"quote\": \"<exact text>\", \"atom\": \"<id>\"}",
             "or finish the sentence in your own words before the citation, so they say what it backs"],
            run_of[n]))
    return out
