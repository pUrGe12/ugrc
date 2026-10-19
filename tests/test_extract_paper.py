"""Extraction invariants on the real paper (skipped when the PDF is not present)."""
import pdfplumber

from tests.conftest import PAPER
from ugrc import extract, store, verify


def test_tables_are_found_where_drawn(paper_root):
    con = store.connect_readonly(paper_root)
    parts = con.execute("SELECT id, label, continues, columns_from FROM tables ORDER BY page").fetchall()
    assert [p[0] for p in parts] == ["p2.T1", "p6.T2", "p16.T3", "p17.T3"]
    assert parts[3][2] == "p16.T3" and all(p[3] == "drawn header rules" for p in parts)
    heads = [h for (h,) in con.execute("SELECT header FROM table_columns WHERE table_id = 'p6.T2' ORDER BY col_no").fetchall()]
    assert heads == ["Target type", "Materials", "Shell/ Decoration", "Drug delivery", "Target", "Particle size",
                     "Release mechanism", "Ref."]
    assert con.execute("SELECT text FROM cells WHERE id = 'p6.T2.r3c6'").fetchone()[0] == "~98 nm"
    assert con.execute("SELECT text FROM cells WHERE id = 'p6.T2.r4c6'").fetchone()[0] == "90–100 nm"


def test_figures_are_the_captioned_images(paper_root):
    con = store.connect_readonly(paper_root)
    figs = con.execute("SELECT id, caption FROM figures WHERE label IS NOT NULL ORDER BY page").fetchall()
    assert [f[0] for f in figs] == ["p4.F1", "p5.F2", "p9.F3", "p10.F4"]
    assert all(cap.startswith(f"Fig. {n}.") for n, (_, cap) in enumerate(figs, 1))
    assert con.execute("SELECT count(*) FROM figures WHERE label IS NULL").fetchone()[0] == 2


def test_every_glyph_lands_in_exactly_one_atom(paper_root):
    con = store.connect_readonly(paper_root)
    with pdfplumber.open(str(PAPER)) as pdf:
        for pageno in (1, 5, 6, 16, 17, 24):
            words = extract._page_words(pdf.pages[pageno - 1])
            ink = sum(len(extract._clean(w["text"]).replace("^", "")) for w in words)
            atoms = con.execute("SELECT text FROM lines WHERE page = ? UNION ALL SELECT text FROM cells WHERE page = ?",
                                [pageno, pageno]).fetchall()
            # spaces and superscript carets are added by joining; every character of ink is there once
            assert ink == sum(len(t.replace(" ", "").replace("^", "")) for (t,) in atoms), f"page {pageno}"


def test_reextracting_the_pdf_reproduces_every_atom(paper_root):
    lines = verify.verify_substrate(paper_root, PAPER)
    assert all(ok for ok, _ in lines), lines
