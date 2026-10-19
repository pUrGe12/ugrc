"""A small hand-built substrate: the same schema and seals as a real one, a few atoms of each kind."""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw

from ugrc import extract, store

LINES = [
    ("p1.L1", 1, 1, "Results"),
    ("p1.L2", 1, 2, "The yield was 85.2% at 350 °C over Ni-10."),
    ("p1.L3", 1, 3, "Rate per kg: USD 3,45"),
    ("p1.L4", 1, 4, "Ni-10 and Ni-20 were both tested."),
    ("p1.L5", 1, 5, "Particles were spe-"),
    ("p1.L6", 1, 6, "cific to tumors at 120 nm, and the PLGA/"),
    ("p1.L7", 1, 7, "PLA blend gave a 3.5-fold rise."),
    ("p1.L8", 1, 8, "Each mouse received 2 \u03bcg of siRNA."),        # Greek mu
    ("p2.L1", 2, 1, "Fig. 1. Yield versus temperature."),
    ("p2.L2", 2, 2, "4-MPBA coats the rods."),
    ("p2.L3", 2, 3, "Free 4-MPBA binds the rods."),
]
CELLS = [  # id, row, col, header?, text
    ("p1.T1.r1c1", 1, 1, True, "Catalyst"), ("p1.T1.r1c2", 1, 2, True, "Yield (%)"),
    ("p1.T1.r2c1", 2, 1, False, "Ni-10"), ("p1.T1.r2c2", 2, 2, False, "85.2"),
    ("p1.T1.r3c1", 3, 1, False, "Ni-20"), ("p1.T1.r3c2", 3, 2, False, "91.0"),
    ("p1.T1.r4c1", 4, 1, False, "Co-5"), ("p1.T1.r4c2", 4, 2, False, "1.55"),
    ("p1.T1.r2c3", 2, 3, False, "143.47 ±"), ("p1.T1.r3c3", 3, 3, False, "10.34 nm"),   # one wrapped cell
]


def make(root) -> Path:
    root = Path(root)
    (root / "figures").mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (240, 120), "white")
    ImageDraw.Draw(img).text((10, 50), "350 C 85.2%", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    (root / "figures" / "p2.F1.png").write_bytes(buf.getvalue())
    ex = extract.Extraction(file="doc.pdf", sha256="a" * 64, nbytes=1, pages=2)
    ex.lines = [{"id": i, "page": p, "line_no": n, "text": t, "size": 8.0, "region": None,
                 "x0": 38.0, "top": 50.0 + 10 * n, "x1": 290.0, "bottom": 58.0 + 10 * n} for i, p, n, t in LINES]
    ex.tables = [{"id": "p1.T1", "label": "Table 1", "number": 1, "page": 1, "continues": None,
                  "columns_from": "drawn header rules", "n_rows": 4, "n_cols": 2, "x0": 38.0, "top": 200.0,
                  "x1": 300.0, "bottom": 260.0, "caption": "Table 1 Yields.", "caption_lines": []}]
    ex.columns = [{"id": f"p1.T1.c{c}", "table_id": "p1.T1", "page": 1, "col_no": c, "header": h,
                   "x_from": 38.0 + 130 * (c - 1), "x_to": 168.0 + 130 * (c - 1)}
                  for c, h in ((1, "Catalyst"), (2, "Yield (%)"))]
    ex.cells = [{"id": i, "table_id": "p1.T1", "page": 1, "row_no": r, "col_no": c, "is_header": h, "text": t,
                 "x0": 40.0 + 130 * (c - 1), "top": 200.0 + 10 * r, "x1": 100.0 + 130 * (c - 1),
                 "bottom": 207.0 + 10 * r} for i, r, c, h, t in CELLS]
    ex.figures = [{"id": "p2.F1", "label": "Fig. 1", "number": 1, "page": 2,
                   "caption": "Fig. 1. Yield versus temperature.", "caption_lines": ["p2.L1"],
                   "x0": 50.0, "top": 60.0, "x1": 290.0, "bottom": 180.0, "image_sha256": None,
                   "png": "figures/p2.F1.png", "png_pixels_sha256": extract.pixels_sha256(img),
                   "png_width": img.width, "png_height": img.height}]
    con = store.connect_write(root)
    try:
        store.load_extraction(con, ex)
        store._insert(con, "figure_ocr", [
            {"id": "p2.F1.o1", "figure_id": "p2.F1", "page": 2, "line_no": 1, "text": "350 °C 85.2%", "conf": 91.0,
             "x0": 60.0, "top": 100.0, "x1": 120.0, "bottom": 108.0, "reader": "tesseract test"}])
        box = {"x0": 50.0, "top": 60.0, "x1": 290.0, "bottom": 180.0}
        store._insert(con, "figure_facts", [
            {"id": "p2.F1.k0", "figure_id": "p2.F1", "page": 2, "fact_no": 0, "statement": "A yield curve.",
             "basis": "visual", "printed_text": [], "quantity": None, "value": None, "unit": None,
             "condition": None, "panel": None, "ocr_confirmed": False, "check_note": "summary",
             "reader": "test-model", **box},
            {"id": "p2.F1.k1", "figure_id": "p2.F1", "page": 2, "fact_no": 1,
             "statement": "The yield is 85.2% at 350 °C.", "basis": "printed", "printed_text": ["85.2%"],
             "quantity": "yield", "value": 85.2, "unit": "%", "condition": "350 °C", "panel": None,
             "ocr_confirmed": True, "check_note": None, "reader": "test-model", **box}])
        store.reseal(con, "readings")
    finally:
        con.close()
    return root
