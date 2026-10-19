"""A vision model reads each figure into facts; the machine checks what it can.

The model is shown exactly two things: the figure's pixels (the PNG whose pixel hash the substrate
pins) and its caption, verbatim from the PDF. It is NOT shown the OCR text: OCR is the second,
independent reader, and a check against text the model was handed would confirm nothing.

Each fact says whether it rests on something PRINTED in the image (a label, a number, a legend)
or on something VISUAL (a bar's height, an arrow, a colour), and for printed facts it copies the
printed strings. Then, with no model:
  - every printed string must occur in tesseract's reading of the same pixels (whitespace aside,
    character for character), and
  - a printed fact's number must be one of the numbers in its printed strings.
A fact passing both is `model-read, ocr-confirmed`; any other is `model-read`, with the reason in
`check_note`. Nothing is dropped: an unconfirmed reading is kept and labelled, never promoted.

Fact 0 of every figure is the model's summary of it.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from ugrc import llm, store

PROMPT = """This image is {label} from page {page} of the document "{file}".
Its caption, verbatim from the PDF:
<caption>
{caption}
</caption>

Read the figure and report what it shows as a list of atomic facts. For each fact:
- statement: one self-contained sentence stating something the figure shows. Name the panel, axis or element it comes from.
- basis: "printed" if the fact rests on text, numbers or labels visibly written in the image; "visual" if it rests on shapes, positions, colours, sizes, arrows or curve/bar heights.
- printed_text: for a printed fact, the strings exactly as they appear in the image that the fact relies on, copied character for character. Empty for a visual fact.
- quantity, value, unit, condition: fill these when the fact is a number (value as a number: exactly as printed for a printed fact, as best read from the graphic for a visual one); otherwise null.
- panel: the panel label (a, b, ...) when the figure has labelled panels; otherwise null.
Also give a summary of the whole figure, and list its panels.
The caption is already recorded verbatim from the PDF, so do not restate it as facts: report what the image itself shows, using the caption only to understand it. Cover everything the image communicates."""

_NULLABLE_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}
SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "panels": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["label", "description"],
            "properties": {"label": {"type": "string"}, "description": {"type": "string"}}}},
        "facts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["statement", "basis", "printed_text", "quantity", "value", "unit", "condition", "panel"],
            "properties": {
                "statement": {"type": "string"},
                "basis": {"type": "string", "enum": ["printed", "visual"]},
                "printed_text": {"type": "array", "items": {"type": "string"}},
                "quantity": _NULLABLE_STR,
                "value": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                "unit": _NULLABLE_STR, "condition": _NULLABLE_STR, "panel": _NULLABLE_STR}}},
    },
    "required": ["summary", "panels", "facts"],
    "additionalProperties": False,
}
PROMPT_SHA256 = hashlib.sha256((PROMPT + json.dumps(SCHEMA, sort_keys=True)).encode()).hexdigest()

_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def _norm(s: str) -> str:
    return " ".join(s.split())


def numbers_in(text: str) -> set[float]:
    """Every reading of every number token: 1,234 as 1234; 3,45 as 3.45 too (a decimal comma)."""
    out = set()
    for tok in _NUM.findall(text):
        for cand in {tok.replace(",", ""), tok.replace(",", ".") if tok.count(",") == 1 and "." not in tok else None}:
            if cand is None:
                continue
            try:
                out.add(float(cand))
            except ValueError:
                pass
    return out


def check_fact(fact: dict, ocr_text: str) -> tuple[bool, str | None]:
    """(ocr_confirmed, check_note) for one fact, against the figure's OCR text. Zero model."""
    if fact["basis"] != "printed":
        return False, "visual reading: nothing printed to check against"
    printed = [p for p in fact["printed_text"] if p.strip()]
    if not printed:
        return False, "printed fact with no printed_text"
    notes = []
    missing = [p for p in printed if _norm(p) not in ocr_text]
    if missing:
        notes.append("OCR did not find " + "; ".join(repr(m) for m in missing[:6]))
    if fact["value"] is not None:
        nums = set().union(*(numbers_in(p) for p in printed))
        if not any(abs(fact["value"] - n) <= 1e-9 * max(1.0, abs(n)) for n in nums):
            notes.append(f"value {fact['value']} is not a number in its printed_text")
    return not notes, ("; ".join(notes) or None)


def _fact_rows(fig, data, ocr_text, reader):
    box = {k: fig[k] for k in ("x0", "top", "x1", "bottom")}
    rows = [{"id": f"{fig['id']}.k0", "figure_id": fig["id"], "page": fig["page"], "fact_no": 0,
             "statement": data["summary"], "basis": "visual", "printed_text": [], "quantity": None,
             "value": None, "unit": None, "condition": None, "panel": None, "ocr_confirmed": False,
             "check_note": "the reader's summary of the whole figure", "reader": reader, **box}]
    for n, f in enumerate(data["facts"], 1):
        confirmed, note = check_fact(f, ocr_text)
        rows.append({"id": f"{fig['id']}.k{n}", "figure_id": fig["id"], "page": fig["page"], "fact_no": n,
                     "statement": f["statement"], "basis": f["basis"], "printed_text": f["printed_text"],
                     "quantity": f["quantity"], "value": f["value"], "unit": f["unit"],
                     "condition": f["condition"], "panel": f["panel"], "ocr_confirmed": confirmed,
                     "check_note": note, "reader": reader, **box})
    return rows


def read_figure(cl, model, file, fig, png: bytes) -> tuple[dict, str]:
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": base64.standard_b64encode(png).decode()}},
        {"type": "text", "text": PROMPT.format(label=fig["label"], page=fig["page"], file=file,
                                               caption=fig["caption"] or "(no caption text)")},
    ]
    resp = llm.create(cl, model=model, max_tokens=16000,
                      output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
                      messages=[{"role": "user", "content": content}])
    if resp.stop_reason == "max_tokens":
        raise RuntimeError(f"{fig['id']}: the reading ran past max_tokens and is incomplete")
    return json.loads(llm.text_of(resp)), resp.id


def read_all(root, model=None, only=None, cl=None, log=print):
    """Read every captioned figure (or the ids in `only`) and store the facts, resealing readings."""
    root = Path(root)
    model = model or llm.MODEL
    cl = cl or llm.client()
    con = store.connect_write(root)
    try:
        file = con.execute("SELECT file FROM sources").fetchone()[0]
        cols = [d[0] for d in con.execute("SELECT * FROM figures LIMIT 0").description]
        figs = [dict(zip(cols, r)) for r in con.execute(
            "SELECT * FROM figures WHERE label IS NOT NULL ORDER BY page, id").fetchall()]
        if only:
            figs = [f for f in figs if f["id"] in set(only)]
        for fig in figs:
            png_path = root / fig["png"]
            png = png_path.read_bytes()
            from PIL import Image
            with Image.open(png_path) as im:
                from ugrc.extract import pixels_sha256
                if pixels_sha256(im.convert("RGB")) != fig["png_pixels_sha256"]:
                    raise SystemExit(f"{png_path} does not hold the pixels the substrate pinned — refusing to read it")
            log(f"reading {fig['id']} ({fig['label']}, page {fig['page']}) with {model} ...")
            data, response_id = read_figure(cl, model, file, fig, png)
            ocr_text = _norm(" ".join(t for (t,) in con.execute(
                "SELECT text FROM figure_ocr WHERE figure_id = ? ORDER BY line_no", [fig["id"]]).fetchall()))
            rows = _fact_rows(fig, data, ocr_text, model)
            con.execute("DELETE FROM figure_facts WHERE figure_id = ?", [fig["id"]])
            con.execute("DELETE FROM figure_reads WHERE figure_id = ?", [fig["id"]])
            store._insert(con, "figure_facts", rows)
            con.execute("INSERT INTO figure_reads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [fig["id"], model, data["summary"], json.dumps(data["panels"]), json.dumps(data),
                         PROMPT_SHA256, fig["png_pixels_sha256"], response_id,
                         datetime.now(timezone.utc).isoformat(timespec="seconds")])
            store.reseal(con, "readings")
            n_conf = sum(1 for r in rows if r["ocr_confirmed"])
            log(f"  {len(rows) - 1} facts ({n_conf} ocr-confirmed) + summary")
    finally:
        con.close()


def adopt_readings(src_root, dst_root, log=print) -> int:
    """Carry figure readings (facts and read records) from an older substrate of the SAME PDF into a
    re-extracted one, figure by figure, only where the figure's pinned pixels are identical: a reading
    is a reading of pixels, so identical pixels mean the reading still applies. Anything else is
    skipped by name. OCR is not carried: re-extraction re-runs it. Returns the figures adopted."""
    src = store.connect_readonly(src_root)
    dst = store.connect_write(dst_root)
    adopted = 0
    try:
        if src.execute("SELECT sha256 FROM sources").fetchone() != dst.execute("SELECT sha256 FROM sources").fetchone():
            raise SystemExit("the two substrates were built from different PDFs — readings cannot be carried across")
        cols_f = [d[0] for d in src.execute("SELECT * FROM figure_facts LIMIT 0").description]
        cols_r = [d[0] for d in src.execute("SELECT * FROM figure_reads LIMIT 0").description]
        for fid, pix in dst.execute("SELECT id, png_pixels_sha256 FROM figures WHERE label IS NOT NULL ORDER BY id").fetchall():
            row = src.execute("SELECT png_pixels_sha256 FROM figures WHERE id = ?", [fid]).fetchone()
            reads = src.execute("SELECT * FROM figure_reads WHERE figure_id = ?", [fid]).fetchall()
            if row is None or row[0] != pix:
                log(f"  {fid}: skipped — its pixels differ between the substrates (re-read it)")
                continue
            if not reads:
                log(f"  {fid}: skipped — never read in the source substrate")
                continue
            facts = src.execute("SELECT * FROM figure_facts WHERE figure_id = ?", [fid]).fetchall()
            dst.execute("DELETE FROM figure_facts WHERE figure_id = ?", [fid])
            dst.execute("DELETE FROM figure_reads WHERE figure_id = ?", [fid])
            store._insert(dst, "figure_facts", [dict(zip(cols_f, f)) for f in facts])
            store._insert(dst, "figure_reads", [dict(zip(cols_r, r)) for r in reads])
            adopted += 1
            log(f"  {fid}: adopted {len(facts) - 1} facts + summary (pixels identical)")
        store.reseal(dst, "readings")
    finally:
        src.close()
        dst.close()
    return adopted
