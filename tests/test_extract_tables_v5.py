"""Tables extractor v5 finds in the 2026-10-30 held-out papers (skipped when the PDFs are not present)."""
from pathlib import Path

import pytest

from ugrc import extract

PAPERS = Path.home() / "Desktop" / "papers-new6"


def tables(name):
    pdf = PAPERS / f"{name}.pdf"
    if not pdf.exists():
        pytest.skip(f"{pdf} is not present")
    extract.render_region = _blank                 # figures are not under test here
    ex = extract.extract(pdf)
    return ex, {t["id"]: t for t in ex.tables}


def _blank(page, box, dpi):
    from PIL import Image
    return Image.new("RGB", (1, 1))


@pytest.fixture(autouse=True)
def _restore():
    keep = extract.render_region
    yield
    extract.render_region = keep


def test_a_caption_in_the_left_column_is_not_bounded_by_prose_higher_in_the_right():
    ex, t = tables("teak-pyrolysis")
    assert {"p3.T1", "p4.T2", "p4.T3"} <= set(t)
    rows = [c["text"] for c in ex.cells if c["table_id"] == "p4.T3"]
    assert "0.9878" in " ".join(rows)                      # a table whose rules are drawn in two halves


def test_rule_caption_rule_header_and_a_table_with_no_bottom_rule():
    ex, t = tables("aspen-transest")
    assert {"p5.T3", "p5.T4", "p7.T9"} <= set(t)
    assert t["p4.T2"]["n_rows"] == 9                        # ends at body text, no prose swallowed
    assert t["p6.T5"]["n_rows"] == 14


def test_long_captions_running_head_rules_and_sideways_pages():
    ex, t = tables("atlas-ttbar")
    assert {"p5.T2", "p31.T7", "p38.T12", "p45.T16"} <= set(t)
    assert {"p18.T3", "p19.T3", "p24.T6", "p25.T6"} <= set(t)      # landscape pages, read turned upright
    assert t["p19.T3"]["continues"] == "p18.T3"
    assert t["p37.T10"]["n_cols"] == 9
    cells = {c["id"]: c for c in ex.cells if c["table_id"] == "p18.T3"}
    assert any("154.8 ± 5.7" in c["text"] for c in cells.values())
    c = next(iter(cells.values()))
    assert 0 <= c["x0"] < c["x1"] <= 595.3 and 0 <= c["top"] < c["bottom"] <= 790.9   # stored on the page
