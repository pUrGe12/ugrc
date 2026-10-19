"""The figure reader: what the model is shown, and what the machine checks of what it says."""
import pytest

from tests.fakes import FakeClient, json_response
from ugrc import figures, store, verify


def fact(statement, basis="printed", printed=(), value=None):
    return {"statement": statement, "basis": basis, "printed_text": list(printed), "quantity": None,
            "value": value, "unit": None, "condition": None, "panel": None}


def test_numbers_in_reads_grouped_and_decimal_commas():
    assert figures.numbers_in("1,234 and 3,45 and 85.2%") >= {1234.0, 3.45, 85.2}


@pytest.mark.parametrize("f,confirmed", [
    (fact("yield 85.2%", printed=["85.2%"], value=85.2), True),
    (fact("yield 85.2%", printed=["85.2 %"], value=85.2), False),     # OCR has no space there
    (fact("yield 92%", printed=["92%"], value=92), False),            # OCR never saw it
    (fact("yield 85.2%", printed=["85.2%"], value=90), False),        # the number is not the printed one
    (fact("rises with T", basis="visual"), False),
    (fact("printed, but nothing copied"), False),
])
def test_check_fact(f, confirmed):
    ok, note = figures.check_fact(f, "350 °C 85.2%")
    assert ok is confirmed and (ok or note)


def test_read_all_stores_checked_facts_pinned_to_the_pixels(synth_root):
    data = {"summary": "Yield against temperature.", "panels": [],
            "facts": [fact("The yield is 85.2% at 350 °C.", printed=["85.2%", "350 °C"], value=85.2),
                      fact("The curve rises, then falls.", basis="visual"),
                      fact("A 99% point is marked.", printed=["99%"], value=99)]}
    cl = FakeClient([json_response(data)])
    figures.read_all(synth_root, model="test-model", cl=cl, log=lambda *_: None)

    req = cl.calls[0]
    assert req["fallbacks"] == "default" and req["output_config"]["format"]["schema"] == figures.SCHEMA
    blocks = req["messages"][0]["content"]
    assert blocks[0]["type"] == "image" and "Yield versus temperature" in blocks[1]["text"]
    assert "350 °C 85.2%" not in blocks[1]["text"]          # the OCR is the independent check, never shown

    con = store.connect_readonly(synth_root)
    rows = con.execute("SELECT id, ocr_confirmed, check_note FROM figure_facts ORDER BY fact_no").fetchall()
    con.close()
    assert [(r[0], r[1]) for r in rows] == [("p2.F1.k0", False), ("p2.F1.k1", True), ("p2.F1.k2", False), ("p2.F1.k3", False)]
    assert "OCR did not find '99%'" in rows[3][2]
    assert all(ok for ok, _ in verify.verify_substrate(synth_root))
