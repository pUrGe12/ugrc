"""Carrying work across a re-extraction: figure readings (same pixels only) and stored answers."""
import json

from tests import synth
from ugrc import __main__ as cli
from ugrc import answer, figures, store


def _read(root):
    con = store.connect_write(root)
    con.execute("INSERT INTO figure_reads VALUES ('p2.F1', 'test-model', 's', '[]', '{}', 'p', "
                "(SELECT png_pixels_sha256 FROM figures WHERE id = 'p2.F1'), 'msg', 'now')")
    store.reseal(con, "readings")
    con.close()


def test_readings_carry_over_only_onto_identical_pixels(tmp_path):
    src, dst = synth.make(tmp_path / "a"), synth.make(tmp_path / "b")
    _read(src)
    con = store.connect_write(dst)
    con.execute("DELETE FROM figure_facts")
    store.reseal(con, "readings")
    con.close()
    assert figures.adopt_readings(src, dst, log=lambda *_: None) == 1
    con = store.connect_readonly(dst)
    assert con.execute("SELECT count(*) FROM figure_facts").fetchone()[0] == 2
    con.close()

    con = store.connect_write(dst)                      # the figure's pixels now differ: nothing carries over
    con.execute("DELETE FROM figure_facts")
    con.execute("UPDATE figures SET png_pixels_sha256 = 'f' || png_pixels_sha256[2:]")
    con.close()
    messages = []
    assert figures.adopt_readings(src, dst, log=messages.append) == 0
    assert any("pixels differ" in m for m in messages)


def test_recheck_resaves_an_answer_that_still_resolves(synth_root, tmp_path):
    con = store.connect_readonly(synth_root)
    runs = [{"text": "Best yield "}, {"quote": "91.0", "atom": "p1.T1.r3c2"}]
    c = answer.check({"runs": runs}, con)
    con.close()
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"question": "best yield?", "runs": runs, "rendered": c.text,
                               "citations": c.citations, "seals": {}, "door_version": "1"}))
    assert cli.main(["recheck", str(old), "--db", str(synth_root)]) == 0
    saved = list((synth_root / "answers").glob("*.json"))
    assert len(saved) == 1
    rec = json.loads(saved[0].read_text())
    assert rec["rechecked_from"] == str(old) and rec["door_version"] == answer.DOOR_VERSION
