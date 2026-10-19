"""How words become text: superscripts keep a caret, subscripts join tight, real spaces stay."""
from ugrc import extract


def w(text, x0, x1, size, top):
    return {"text": text, "x0": x0, "x1": x1, "size": size, "top": top, "bottom": top + size}


def test_an_exponent_keeps_its_caret():
    words = [w("9.2", 0, 10, 8, 100), w("×", 12, 15, 8, 100), w("10", 17, 24, 8, 100),
             w("7", 24.1, 27, 6, 97.5), w("CFU/mL", 29, 50, 8, 100)]
    assert extract._join(words) == "9.2 × 10^7 CFU/mL"


def test_a_charge_and_a_subscript():
    assert extract._join([w("CD8", 0, 12, 8, 100), w("+", 12.2, 15, 6, 97.5), w("T", 17, 20, 8, 100)]) == "CD8^+ T"
    assert extract._join([w("CO", 0, 10, 8, 100), w("2", 10.1, 13, 6, 104), w("emission", 15, 40, 8, 100)]) == "CO2 emission"


def test_a_stretched_line_stays_one_line_but_a_gutter_splits():
    words = [w("modi-", 40, 60, 8, 100), w("fication", 80, 110, 8, 100), w("with", 130, 145, 8, 100)]
    assert [ln["text"] for ln in extract._stream_lines(words, mid=300)] == ["modi- fication with"]
    words = [w("left", 250, 290, 8, 100), w("right", 310, 340, 8, 100)]
    assert [ln["text"] for ln in extract._stream_lines(words, mid=300)] == ["left", "right"]
