"""OCR of figure pixels with tesseract: text the PDF does not carry as text.

A figure in a paper is usually a raster image, so its labels, axis ticks and annotations exist only
as pixels. Tesseract reads them into `figure_ocr` rows (strength `ocr`), each placed back on the
page in PDF points. These rows serve twice: as atoms a citation can quote, and as the independent
second reader that confirms (or fails to confirm) what the vision model says is printed.

Tesseract is a model too — a small fixed one — so its rows are readings, not extraction: they are
sealed with the readings seal and carry the exact tesseract version that produced them.
"""
from __future__ import annotations

import csv
import io
import shutil
import subprocess
import tempfile
from pathlib import Path

import pdfplumber

from ugrc import extract

OCR_DPI = 300           # dots per inch a figure is rendered at for tesseract (its sweet spot is ~300)
OCR_TIMEOUT_S = 120     # seconds one figure may take before it is declined


def tesseract_version() -> str | None:
    exe = shutil.which("tesseract")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    first = (out.stdout or out.stderr).splitlines()
    return first[0].strip() if first else None


def _tsv_lines(tsv: str):
    """Tesseract's word table grouped into lines: (text, mean confidence, pixel box)."""
    groups = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row.get("level") != "5" or not (row.get("text") or "").strip():
            continue
        key = (int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
        groups.setdefault(key, []).append(row)
    out = []
    for key in sorted(groups):
        words = groups[key]
        text = " ".join(w["text"].strip() for w in words)
        if not any(ch.isalnum() for ch in text):
            continue                      # rules, arrows and specks read as | — ~ carry no text
        confs = [float(w["conf"]) for w in words if float(w["conf"]) >= 0]
        left = min(int(w["left"]) for w in words)
        top = min(int(w["top"]) for w in words)
        right = max(int(w["left"]) + int(w["width"]) for w in words)
        bottom = max(int(w["top"]) + int(w["height"]) for w in words)
        out.append((text, sum(confs) / len(confs) if confs else None, (left, top, right, bottom)))
    return out


def ocr_figures(pdf_path, figures: list[dict]) -> tuple[list[dict], list[str]]:
    """OCR rows for every captioned figure, and named declines for what could not be read."""
    version = tesseract_version()
    if version is None:
        return [], ["tesseract is not installed — figures carry no OCR rows (install tesseract-ocr)"]
    rows, declined = [], []
    scale = 72.0 / OCR_DPI
    with pdfplumber.open(str(pdf_path)) as pdf, tempfile.TemporaryDirectory() as tmp:
        for fig in figures:
            if not fig["label"]:
                continue                  # uncaptioned images (logos) are recorded, never read
            page = pdf.pages[fig["page"] - 1]
            img = extract.render_region(page, (fig["x0"], fig["top"], fig["x1"], fig["bottom"]), OCR_DPI)
            png = Path(tmp) / f"{fig['id']}.png"
            img.save(png)
            try:
                res = subprocess.run(["tesseract", str(png), "-", "tsv"], capture_output=True,
                                     text=True, timeout=OCR_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                declined.append(f"{fig['id']}: tesseract ran past {OCR_TIMEOUT_S}s — no OCR rows")
                continue
            if res.returncode != 0:
                declined.append(f"{fig['id']}: tesseract failed ({res.stderr.strip()[:200]})")
                continue
            for n, (text, conf, (l, t, r, b)) in enumerate(_tsv_lines(res.stdout), 1):
                rows.append({"id": f"{fig['id']}.o{n}", "figure_id": fig["id"], "page": fig["page"],
                             "line_no": n, "text": text, "conf": conf,
                             "x0": fig["x0"] + l * scale, "top": fig["top"] + t * scale,
                             "x1": fig["x0"] + r * scale, "bottom": fig["top"] + b * scale,
                             "reader": f"{version} @ {OCR_DPI} dpi"})
    return rows, declined
