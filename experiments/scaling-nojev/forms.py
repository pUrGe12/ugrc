"""Two condensed forms of a paper with no judge in them (PLAN.md).

  code  ugrc's own reading, code only: the sentences ugrc cuts from the PDF's line atoms (running headers, footers and
        the reference list removed by rule), kept when the value pattern finds a value in them; then the tables row
        by row and the figure facts, as the scaling test's facts form. The same as that form without Jev's filter.
  pdf   no ugrc at all: the paper's pdftotext, cut in its second half at the first line reading "References" (or
        "REFERENCES") or starting "[1] " or "(1) " (a reference list printed without a heading), split into paragraphs at blank lines and into sentences at ". " before a capital, kept when the
        sentence holds a digit. Tables come as pdftotext prints them.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "bench-llama"))
from ugrc import clauses, store  # noqa: E402
import direct  # noqa: E402

import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("scaling_run", ROOT / "experiments" / "scaling" / "run.py")
scaling = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scaling)


def code_form(paper):
    con = store.connect_question(ROOT / "runs" / "bench" / paper)
    pages = {}
    for s in clauses.sentences(con):
        if clauses.mentions(s):
            pages.setdefault(s.page, []).append(f"- {s.text}")
    scaling._tables_and_figures(con, pages)
    return "\n\n".join(f"=== page {p} ===\n" + "\n".join(lines) for p, lines in sorted(pages.items()))


_REFS = re.compile(r"^\W*references\W*$|^(?:\[1\]|\(1\))\s", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")


def pdf_form(paper):
    text = direct.paper_text(paper)[0]
    pages = text.split("\f")
    out, stop = [], False
    for n, page in enumerate(pages, 1):
        lines = page.split("\n")
        kept = []
        for i, line in enumerate(lines):
            if n > len(pages) / 2 and _REFS.match(line):
                lines, stop = lines[:i], True
                break
        for para in re.split(r"\n\s*\n", "\n".join(lines)):
            para = re.sub(r"-\n(?=[a-z])", "", para).replace("\n", " ").strip()
            kept += [s for s in _SENT.split(para) if re.search(r"\d", s)]
        if kept:
            out.append(f"=== page {n} ===\n" + "\n".join(f"- {s}" for s in kept))
        if stop:
            break
    return "\n\n".join(out)


FORMS = {"code": code_form, "pdf": pdf_form}

if __name__ == "__main__":
    print(FORMS[sys.argv[2]](sys.argv[1]))
