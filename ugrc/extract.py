"""PDF -> atoms: every text line, every table cell, every figure, each with an address.

Zero model, zero network: a function of the PDF bytes and the pinned pdfplumber (requirements.txt).
Nothing here interprets meaning: no number parsing, no deciding which numbers matter. It records
WHERE each piece of ink is, so that a later claim can point at it and a checker can look.

Atom ids (the addresses a citation points at):
    p5.L12        line 12 of page 5, in the PDF's own content-stream order (reading order)
    p6.T2         Table 2 as drawn on page 6 (p17.T3 continues p16.T3)
    p6.T2.c6      column 6's header text
    p6.T2.r3c6    the cell in visual row 3, column 6. A visual row is one printed line of the
                  table, so a table row whose text wraps occupies consecutive visual rows.
    p5.F2         Figure 2: a region of page 5, rendered to a PNG whose pixels are hashed
    p1.I1         an image with no caption (logo, cover art): recorded, never read

Every word on a page lands in exactly one atom: a table cell if it lies inside a drawn table, a
line otherwise. Tables are found only where the document DRAWS them (a full-width rule under a
"Table N" caption); columns come from the per-column header rules the document draws, and only
when it draws none, from word-free vertical strips. Figures are the embedded images that have a
"Fig. N" caption directly below them.
"""
from __future__ import annotations

import hashlib
import io
import re
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

EXTRACTOR_VERSION = "4"     # 2: images captioned "Scheme N" / "Chart N" are figures too
                            # 3: a raised superscript joins with "^" (10^7, not 107); a wide gap splits a
                            #    line only where it spans the page's centre (a stretched line stays whole)
                            # 4: on a page that prints no space glyphs, a word ends at a gap of WORD_GAP_EM of
                            #    the font size ("Advancementtimelineof..." splits); pages with space glyphs are
                            #    read exactly as in v3. Tables drawn other publishers' ways are found: a rule
                            #    drawn as touching pieces is one rule; "full width" is measured against the
                            #    rules under the caption, not the whole page (a one-column table); a table runs
                            #    on past rules inside it while the text between them is table-sized; a rule
                            #    just above the caption opens it. "FIGURE 1" on a line of its own captions.
                            #    Rotated text (a publisher's notice down the margin) is not read, by name.

# THE NAMED TOLERANCES. Each is a value, a unit and what it measures (pt = a PDF point, 1/72 inch).
# They decide what an atom id means, so EXTRACTOR_VERSION moves with any change to them.
SPACE_GLYPH_MIN_SHARE = 0.02      # a page whose characters include at least this share of space glyphs marks
                                  # its own word boundaries (prose is ~15% spaces); one below it prints none
WORD_GAP_EM = 0.15                # on a page without space glyphs, a horizontal gap wider than this share of
                                  # the font size separates two words. Measured on 7 such papers: gaps inside a
                                  # word stay under 0.14 em (an italic letter before a roman ")" leaves ~0.14),
                                  # gaps between words start at 0.17 em; a fixed 3 pt glued words in all 7
WORD_X_TOLERANCE_PT = 3.0         # on a page with space glyphs, a gap wider than this also separates two words;
                                  # and a word continues a line when it starts no more than this before the
                                  # previous word ends
WORD_Y_TOLERANCE_PT = 3.0         # vertical shift above which a character starts a new word
LINE_MAX_GAP_PT = 9.0             # a horizontal gap wider than this between two consecutive words splits
                                  # the line, IF it spans the page's vertical centre line (a two-column
                                  # gutter is ~11 pt and sits at the centre; a stretched justified line can
                                  # leave wider gaps anywhere else and stays one line)
RULE_MAX_THICKNESS_PT = 1.5       # a drawn shape thinner than this is a horizontal rule
RULE_MIN_LENGTH_PT = 20.0         # a rule shorter than this is decoration
FULL_RULE_FRACTION = 0.9          # share of the widest rule under a table caption above which a rule spans
                                  # the table
RULE_JOIN_GAP_PT = 0.5            # pieces of one rule that touch end to end within this are one rule (Wiley
                                  # draws a rule as one piece per column); pieces that overlap (Elsevier's
                                  # per-column header rules) stay separate, because they mark the columns
TABLE_MIN_WIDTH_PT = 150.0        # a rule narrower than this never opens a table (a footnote separator)
CAPTION_RULE_ABOVE_PT = 12.0      # a table's top rule may sit at most this far above its caption
SAME_Y_PT = 1.0                   # rules whose tops differ by at most this are one rule line
TABLE_RULE_MAX_GAP_PT = 40.0      # a table's top rule starts at most this far below its caption
COLUMN_GUTTER_MIN_PT = 4.0        # a word-free vertical strip this wide separates two table columns
                                  # (used only when the table draws no per-column header rules)
SMALL_GLYPH_MARGIN_PT = 0.5       # a word this much smaller than a table's main size is a sub/superscript
JOIN_SHIFT_PT = 0.5               # two words whose sizes or tops differ by more than this were split by a
                                  # sub/superscript, not by a space ...
JOIN_TIGHT_GAP_PT = 0.5           # ... and join with no space when the gap between them is at most this
                                  # (a real space is ~0.25 em, about 1.5 pt even at a 6 pt table font)
CAPTION_MAX_GAP_PT = 30.0         # a figure caption starts at most this far below its image
CAPTION_SIZE_TOLERANCE_PT = 0.25  # caption continuation lines share the caption's font size within this
CAPTION_LINE_GAP_PT = 4.0         # ... and start at most this far below the previous caption line
FIGURE_DPI = 200                  # dots per inch a figure region is rendered at

# Typographic ligatures expand to their letters, so "efficiency" is quotable as typed. A closed
# table: nothing else is normalized (no NFKC — it would turn a superscript ² into a plain 2).
LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
             "ﬅ": "ft", "ﬆ": "st"}

TABLE_CAPTION = re.compile(r"^Table\s+(\d+)\b\s*(\(continued\))?")
FIGURE_CAPTION = re.compile(r"^(Fig\.|Figure|FIGURE|FIG\.|Scheme|SCHEME|Chart)\s*(\d+)\s*(?:[.:|]|$)")
# a caption line that is only the label ("FIGURE 1"), set in the margin beside the caption text: it
# need not sit horizontally under the image
_LABEL_ONLY = re.compile(r"^(?:Fig\.|Figure|FIGURE|FIG\.|Scheme|SCHEME|Chart)\s*\d+\s*[.:|]?\s*$")
# how each caption word names its figure: (id letter, label word)
FIGURE_KINDS = {"Fig.": ("F", "Fig."), "Figure": ("F", "Fig."), "FIGURE": ("F", "Fig."), "FIG.": ("F", "Fig."),
                "Scheme": ("S", "Scheme"), "SCHEME": ("S", "Scheme"), "Chart": ("C", "Chart")}


@dataclass
class Extraction:
    file: str
    sha256: str
    nbytes: int
    pages: int
    lines: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    columns: list = field(default_factory=list)
    cells: list = field(default_factory=list)
    figures: list = field(default_factory=list)
    pngs: dict = field(default_factory=dict)        # figure id -> PNG bytes
    declined: list = field(default_factory=list)    # named reasons something was not extracted


# ─────────────────────────── words and lines ───────────────────────────

def _clean(text: str) -> str:
    for k, v in LIGATURES.items():
        text = text.replace(k, v)
    return text


def _join(words) -> str:
    """Words to text, one space between words. The exception is a word split off by a size or
    baseline change that touches its neighbour:
      - a SUPERSCRIPT (smaller, raised) joins with a caret, because flattening it changes what the
        text says: 9.2 × 10^7 is not 9.2 × 107. CD8^+ and O2^- read the same way;
      - anything else (a subscript, a font change) joins tight, so mPEG2k, CO2 and NH4HCO3 stay one
        token, while "CO2 emission" keeps its space."""
    out = words[0]["text"]
    for a, b in zip(words, words[1:]):
        shifted = abs(a["size"] - b["size"]) > JOIN_SHIFT_PT or abs(a["top"] - b["top"]) > JOIN_SHIFT_PT
        if shifted and b["x0"] - a["x1"] <= JOIN_TIGHT_GAP_PT:
            raised = b["size"] < a["size"] - JOIN_SHIFT_PT and b["bottom"] < a["bottom"] - JOIN_SHIFT_PT
            out += ("^" if raised else "") + b["text"]
        else:
            out += " " + b["text"]
    return _clean(out)


def _size(words) -> float:
    """The font size carried by most of the characters."""
    c = Counter()
    for w in words:
        c[round(w["size"], 2)] += len(w["text"])
    return c.most_common(1)[0][0]


def _box(items):
    return (min(i["x0"] for i in items), min(i["top"] for i in items),
            max(i["x1"] for i in items), max(i["bottom"] for i in items))


def _center(w):
    return (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2


def _inside(w, box, pad=SAME_Y_PT):
    cx, cy = _center(w)
    return box[0] - pad <= cx <= box[2] + pad and box[1] - pad <= cy <= box[3] + pad


def _upright(page):
    """The page without its rotated characters: a download notice set down the margin would otherwise
    become one line per letter. What is left out is declined by name in `extract`."""
    return page.filter(lambda o: o.get("object_type") != "char" or o.get("upright", True))


def _page_words(page):
    page = _upright(page)
    chars = page.chars
    spaced = sum(1 for c in chars if c["text"] == " ") >= SPACE_GLYPH_MIN_SHARE * len(chars)
    gap = {"x_tolerance": WORD_X_TOLERANCE_PT} if spaced else {"x_tolerance_ratio": WORD_GAP_EM}
    return page.extract_words(**gap, y_tolerance=WORD_Y_TOLERANCE_PT,
                              use_text_flow=True, extra_attrs=["size"])


def _stream_lines(words, mid) -> list[dict]:
    """Lines in the PDF's own content-stream order, which for a typeset paper is reading order
    (left column, then right). A word continues the current line when it overlaps the line
    vertically, moves forward, and does not jump a column gutter: a gap wider than LINE_MAX_GAP_PT
    that spans the page's centre `mid`."""
    lines, cur = [], None
    for w in words:
        if cur is not None:
            prev = cur["words"][-1]
            gutter = w["x0"] - prev["x1"] > LINE_MAX_GAP_PT and prev["x1"] <= mid <= w["x0"]
            if (w["top"] < cur["bottom"] and w["bottom"] > cur["top"]
                    and w["x0"] >= prev["x1"] - WORD_X_TOLERANCE_PT and not gutter):
                cur["words"].append(w)
                cur["top"], cur["bottom"] = min(cur["top"], w["top"]), max(cur["bottom"], w["bottom"])
                continue
        cur = {"words": [w], "top": w["top"], "bottom": w["bottom"]}
        lines.append(cur)
    for ln in lines:
        ln["text"] = _join(ln["words"])
        ln["x0"], ln["top"], ln["x1"], ln["bottom"] = _box(ln["words"])
        ln["size"] = _size(ln["words"])
    return lines


def _folio_top(lines, page_height) -> float:
    """Top of the page-number line (the bottom-most line, when it is a bare number), else the page
    height. A table with no bottom rule runs down to here and no further."""
    if lines:
        last = max(lines, key=lambda ln: ln["top"])
        if last["text"].strip().isdigit():
            return last["top"]
    return page_height


# ─────────────────────────── rules and tables ───────────────────────────

def _rule_rows(page) -> list[dict]:
    """Thin horizontal shapes (lines, rects or curves — a typesetter draws rules any of the three
    ways), grouped into rule lines by y. `run` is the widest stretch of pieces that touch end to end."""
    rules = sorted((o["top"], o["x0"], o["x1"]) for o in page.lines + page.rects + page.curves
                   if o["bottom"] - o["top"] <= RULE_MAX_THICKNESS_PT
                   and o["x1"] - o["x0"] >= RULE_MIN_LENGTH_PT)
    if not rules:
        return []
    rows = []
    for y, x0, x1 in rules:
        if rows and y - rows[-1]["y"] <= SAME_Y_PT:
            rows[-1]["segs"].append((x0, x1))
        else:
            rows.append({"y": y, "segs": [(x0, x1)]})
    for r in rows:
        r["segs"].sort()
        runs, cur = [], list(r["segs"][0])
        for a, b in r["segs"][1:]:
            if abs(a - cur[1]) <= RULE_JOIN_GAP_PT:
                cur[1] = max(cur[1], b)
            else:
                runs.append(cur)
                cur = [a, b]
        runs.append(cur)
        r["run"] = max(b - a for a, b in runs)
        r["x0"], r["x1"] = min(a for a, _ in r["segs"]), max(b for _, b in r["segs"])
    return rows


def _gutter_bounds(words, x0, x1) -> list[float]:
    """Column boundaries at the middle of every word-free vertical strip at least
    COLUMN_GUTTER_MIN_PT wide."""
    spans = sorted((w["x0"], w["x1"]) for w in words)
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    mids = [(p[1] + q[0]) / 2 for p, q in zip(merged, merged[1:]) if q[0] - p[1] >= COLUMN_GUTTER_MIN_PT]
    return [x0] + mids + [x1]


def _visual_rows(words) -> list[dict]:
    """Printed lines of a table. Rows are built from the main-size words only (a word joins a row
    when its vertical centre lies within the row); sub- and superscripts then attach to the row
    whose centre is nearest, so a small raised glyph can never bridge two rows."""
    main_size = _size(words)
    main = [w for w in words if w["size"] >= main_size - SMALL_GLYPH_MARGIN_PT]
    small = [w for w in words if w["size"] < main_size - SMALL_GLYPH_MARGIN_PT]
    rows = []
    for w in sorted(main, key=lambda w: (w["top"], w["x0"])):
        cy = _center(w)[1]
        if rows and rows[-1]["top"] <= cy <= rows[-1]["bottom"]:
            r = rows[-1]
            r["words"].append(w)
            r["top"], r["bottom"] = min(r["top"], w["top"]), max(r["bottom"], w["bottom"])
        else:
            rows.append({"words": [w], "top": w["top"], "bottom": w["bottom"]})
    for w in small:
        if rows:
            cy = _center(w)[1]
            min(rows, key=lambda r: abs((r["top"] + r["bottom"]) / 2 - cy))["words"].append(w)
        else:
            rows.append({"words": [w], "top": w["top"], "bottom": w["bottom"]})
    return rows


def _find_tables(pageno, plines, rule_rows, folio_top, declined, body_size) -> list[dict]:
    """Table regions on one page: a "Table N" caption, a full-width rule within
    TABLE_RULE_MAX_GAP_PT below it (or just above it), optional per-column header rules, and a bottom
    rule (or, for a table continued on the next page, the last ink above the folio). A rule is
    full-width when it spans the widest rule under the caption: a one-column table's rules span its
    column. The table runs on past further full-width rules while the text between them is smaller
    than the paper's body text (`body_size`), as when rules separate groups of rows."""
    found = []
    caps = [ln for ln in plines if TABLE_CAPTION.match(ln["text"])]
    for i, cap in enumerate(caps):
        m = TABLE_CAPTION.match(cap["text"])
        limit = caps[i + 1]["top"] if i + 1 < len(caps) else folio_top
        below = [r for r in rule_rows if cap["bottom"] <= r["y"] < limit]
        above = [r for r in rule_rows if cap["top"] - CAPTION_RULE_ABOVE_PT <= r["y"] < cap["top"]][-1:]
        widest = max((r["run"] for r in above + below), default=0.0)

        def full(r):
            return r["run"] >= FULL_RULE_FRACTION * widest and r["run"] >= TABLE_MIN_WIDTH_PT

        top = next((r for r in below if full(r)), None)
        box_top = None
        if above and full(above[0]) and any(full(r) for r in below):
            top = above[0]                                # "rule / Table 1. caption / header / rule / rows / rule"
            block = []
            for ln in _caption_lines(plines, cap) or [cap]:
                block.append(ln)
                if ln["text"].rstrip().endswith("."):
                    break                                 # the caption ends at its full stop; the header row follows
            box_top = block[-1]["bottom"]
        elif top is None or top["y"] - cap["bottom"] > TABLE_RULE_MAX_GAP_PT:
            declined.append(f"p{pageno}: line {cap['text'][:40]!r} starts like a table caption but no "
                            f"full-width rule follows within {TABLE_RULE_MAX_GAP_PT:g} pt — read as prose")
            continue
        after = [r for r in below if r["y"] > top["y"] + SAME_Y_PT]
        header = None
        if after and not full(after[0]) and len(after[0]["segs"]) >= 2:
            header, after = after[0], after[1:]
        fulls = [r for r in after if full(r)]
        if header is None and len(fulls) >= 2:
            header, fulls = fulls[0], fulls[1:]          # a full-width rule under the header row
        x0, x1 = top["x0"], top["x1"]

        def inside(ln):
            return ln["x0"] >= x0 - SAME_Y_PT and ln["x1"] <= x1 + SAME_Y_PT

        if fulls:
            y1 = fulls[0]["y"]
            for nxt in fulls[1:]:                         # rules between groups of rows
                between = [ln for ln in plines if y1 < ln["top"] and ln["bottom"] <= nxt["y"] and inside(ln)]
                if not between or any(ln["size"] >= body_size - SMALL_GLYPH_MARGIN_PT for ln in between):
                    break
                y1 = nxt["y"]
        else:                                             # continues on the next page
            start = (header or top)["y"]
            ink = [ln["bottom"] for ln in plines
                   if ln["top"] > start and ln["bottom"] <= limit and inside(ln)]
            y1 = max(ink, default=start)
        found.append({"caption": cap, "number": int(m.group(1)), "continued": bool(m.group(2)),
                      "box": (x0, box_top if box_top is not None else top["y"], x1, y1), "header": header})
    return found


def _table_atoms(pageno, t, words):
    """Cells of one table region, and its column headers."""
    tid = f"p{pageno}.T{t['number']}"
    x0, y0, x1, y1 = t["box"]
    region = [w for w in words if _inside(w, t["box"])]
    header = t["header"]
    if header is not None and len(header["segs"]) >= 2:
        segs = header["segs"]
        bounds = [segs[0][0]] + [(a[1] + b[0]) / 2 for a, b in zip(segs, segs[1:])] + [segs[-1][1]]
        columns_from = "drawn header rules"
    else:
        bounds = _gutter_bounds(region, x0, x1)
        columns_from = "whitespace gutters"
    ncols = len(bounds) - 1
    rows = _visual_rows(region) if region else []
    cells, header_parts = [], {c: [] for c in range(1, ncols + 1)}
    for r_no, row in enumerate(rows, 1):
        is_header = header is not None and (row["top"] + row["bottom"]) / 2 < header["y"]
        by_col = {}
        for w in sorted(row["words"], key=lambda w: w["x0"]):
            c = min(max(bisect_right(bounds, w["x0"]), 1), ncols)
            by_col.setdefault(c, []).append(w)
        for c, ws in sorted(by_col.items()):
            text = _join(ws)
            bx = _box(ws)
            cells.append({"id": f"{tid}.r{r_no}c{c}", "table_id": tid, "page": pageno,
                          "row_no": r_no, "col_no": c, "is_header": is_header, "text": text,
                          "x0": bx[0], "top": bx[1], "x1": bx[2], "bottom": bx[3]})
            if is_header:
                header_parts[c].append(text)
    columns = [{"id": f"{tid}.c{c}", "table_id": tid, "page": pageno, "col_no": c,
                "header": " ".join(header_parts[c]) or None, "x_from": bounds[c - 1], "x_to": bounds[c]}
               for c in range(1, ncols + 1)]
    table = {"id": tid, "label": t["caption"]["text"] if t["continued"] else f"Table {t['number']}",
             "number": t["number"], "page": pageno, "continues": None, "columns_from": columns_from,
             "n_rows": len(rows), "n_cols": ncols, "x0": x0, "top": y0, "x1": x1, "bottom": y1}
    return table, columns, cells


# ─────────────────────────── figures ───────────────────────────

def _find_figures(pageno, page, plines) -> list[dict]:
    """Embedded images grouped under the caption directly below them ("Fig. N", "Scheme N", "Chart N");
    an image with no caption below it stays an uncaptioned image."""
    caps = [ln for ln in plines if FIGURE_CAPTION.match(ln["text"])]
    grouped, loose = {}, []
    for im in page.images:
        box = (max(im["x0"], 0), max(im["top"], 0), min(im["x1"], page.width), min(im["bottom"], page.height))
        if box[2] <= box[0] or box[3] <= box[1]:
            continue                                      # drawn entirely off the page
        under = [c for c in caps if -SAME_Y_PT <= c["top"] - box[3] <= CAPTION_MAX_GAP_PT
                 and ((c["x0"] < box[2] and c["x1"] > box[0]) or _LABEL_ONLY.match(c["text"]))]
        if under:
            cap = min(under, key=lambda c: c["top"] - box[3])
            grouped.setdefault(id(cap), {"caption": cap, "images": []})["images"].append((box, im))
        else:
            loose.append((box, im))
    figs = []
    for g in grouped.values():
        m = FIGURE_CAPTION.match(g["caption"]["text"])
        letter, word = FIGURE_KINDS[m.group(1)]
        num = int(m.group(2))
        figs.append({"id": f"p{pageno}.{letter}{num}", "label": f"{word} {num}", "number": num,
                     "caption_line": g["caption"], "images": g["images"]})
    for k, (box, im) in enumerate(sorted(loose, key=lambda bi: (bi[0][1], bi[0][0])), 1):
        figs.append({"id": f"p{pageno}.I{k}", "label": None, "number": None,
                     "caption_line": None, "images": [(box, im)]})
    for f in figs:
        boxes = [b for b, _ in f["images"]]
        f["box"] = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                    max(b[2] for b in boxes), max(b[3] for b in boxes))
    return figs


def _image_sha(images) -> str | None:
    """sha256 over the embedded image streams' own bytes, in drawing order — the image as the PDF
    stores it, before any rendering."""
    h = hashlib.sha256()
    try:
        for _, im in images:
            h.update(im["stream"].get_rawdata())
    except Exception:
        return None
    return h.hexdigest()


def render_region(page, box, dpi):
    """The region rendered to an RGB image (PIL). The same bytes and the same pdfium render the
    same pixels; pixels_sha256 is what a reading of the figure is pinned to."""
    return page.crop(box, strict=False).to_image(resolution=dpi).original.convert("RGB")


def pixels_sha256(img) -> str:
    return hashlib.sha256(f"{img.width}x{img.height}:".encode() + img.tobytes()).hexdigest()


def _caption_lines(lines, start) -> list[dict]:
    """The caption's first line and the lines that continue it: next in reading order, same font
    size, starting right under the previous caption line."""
    try:
        i = next(k for k, ln in enumerate(lines)
                 if abs(ln["top"] - start["top"]) < 0.01 and abs(ln["x0"] - start["x0"]) < 0.01)
    except StopIteration:
        return []
    out = [lines[i]]
    for ln in lines[i + 1:]:
        prev = out[-1]
        if (abs(ln["size"] - prev["size"]) <= CAPTION_SIZE_TOLERANCE_PT
                and 0 <= ln["top"] - prev["bottom"] <= CAPTION_LINE_GAP_PT):
            out.append(ln)
        else:
            break
    return out


# ─────────────────────────── the whole document ───────────────────────────

def _body_size(pages) -> float:
    """The font size most of the paper's characters are set in: its body text."""
    c = Counter()
    for page in pages:
        for ch in page.chars:
            if not ch["text"].isspace():
                c[round(ch["size"], 1)] += 1
    return c.most_common(1)[0][0] if c else 0.0


def extract(pdf_path) -> Extraction:
    pdf_path = Path(pdf_path)
    data = pdf_path.read_bytes()
    ex = Extraction(file=pdf_path.name, sha256=hashlib.sha256(data).hexdigest(), nbytes=len(data), pages=0)
    last_part = {}                                        # table number -> id of its latest part
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        ex.pages = len(pdf.pages)
        body_size = _body_size(pdf.pages)
        for pageno, page in enumerate(pdf.pages, 1):
            rotated = sum(1 for c in page.chars if not c.get("upright", True))
            if rotated:
                ex.declined.append(f"p{pageno}: {rotated} characters set rotated (a margin notice or rotated "
                                   f"labels) — not read")
            words = _page_words(page)
            plines = _stream_lines(words, page.width / 2) if words else []
            folio = _folio_top(plines, page.height)
            found = _find_tables(pageno, plines, _rule_rows(page), folio, ex.declined, body_size)
            figs = _find_figures(pageno, page, plines)

            # tables first: their words become cells and leave the line stream
            in_table = set()
            for t in found:
                table, columns, cells = _table_atoms(pageno, t, words)
                if table["n_rows"] == 0:
                    ex.declined.append(f"p{pageno}: {table['label']} region holds no words")
                    continue
                if t["continued"]:
                    table["continues"] = last_part.get(t["number"])
                last_part[t["number"]] = table["id"]
                t["table"] = table
                ex.tables.append(table)
                ex.columns.extend(columns)
                ex.cells.extend(cells)
                in_table.update(id(w) for w in words if _inside(w, t["box"]))

            rest = [w for w in words if id(w) not in in_table]
            lines = _stream_lines(rest, page.width / 2) if rest else []
            fig_boxes = [(f["id"], f["box"]) for f in figs if f["label"]]
            for n, ln in enumerate(lines, 1):
                ln["id"] = f"p{pageno}.L{n}"
                region = next((fid for fid, box in fig_boxes if all(_inside(w, box, 0) for w in ln["words"])), None)
                ex.lines.append({"id": ln["id"], "page": pageno, "line_no": n, "text": ln["text"],
                                 "size": ln["size"], "region": region,
                                 "x0": ln["x0"], "top": ln["top"], "x1": ln["x1"], "bottom": ln["bottom"]})

            for t in found:                                # table captions: the lines above the top rule
                if "table" not in t:
                    continue
                x0, y0, x1, _ = t["box"]
                cap = [ln for ln in lines if t["caption"]["top"] - SAME_Y_PT <= ln["top"] and ln["bottom"] <= y0
                       and ln["x0"] < x1 and ln["x1"] > x0]
                t["table"]["caption"] = " ".join(ln["text"] for ln in cap)
                t["table"]["caption_lines"] = [ln["id"] for ln in cap]

            for f in figs:
                cap = _caption_lines(lines, f["caption_line"]) if f["caption_line"] else []
                img = render_region(page, f["box"], FIGURE_DPI)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                ex.pngs[f["id"]] = buf.getvalue()
                ex.figures.append({"id": f["id"], "label": f["label"], "number": f["number"], "page": pageno,
                                   "caption": " ".join(ln["text"] for ln in cap) or None,
                                   "caption_lines": [ln["id"] for ln in cap],
                                   "x0": f["box"][0], "top": f["box"][1], "x1": f["box"][2], "bottom": f["box"][3],
                                   "image_sha256": _image_sha(f["images"]), "png": f"figures/{f['id']}.png",
                                   "png_pixels_sha256": pixels_sha256(img),
                                   "png_width": img.width, "png_height": img.height})
    return ex
