"""The receipt catches tampering: an edited atom, swapped pixels, an answer whose pointers moved."""
import json
import shutil

from PIL import Image

from ugrc import answer, store, verify


def _ok(lines):
    return all(ok for ok, _ in lines)


def test_a_fresh_substrate_is_green(synth_root):
    assert _ok(verify.verify_substrate(synth_root))


def test_an_edited_atom_breaks_the_seal(synth_root):
    con = store.connect_write(synth_root)
    con.execute("UPDATE cells SET text = '99.9' WHERE id = 'p1.T1.r3c2'")
    con.close()
    lines = verify.verify_substrate(synth_root)
    assert not _ok(lines) and any("extraction seal BROKEN" in m for _, m in lines)


def test_swapped_pixels_are_caught(synth_root):
    Image.new("RGB", (240, 120), "black").save(synth_root / "figures" / "p2.F1.png")
    lines = verify.verify_substrate(synth_root)
    assert any("does NOT hold the pinned pixels" in m for _, m in lines)


def test_an_answer_whose_atom_changed_is_caught(synth_root, tmp_path):
    con = store.connect_readonly(synth_root)
    checked = answer.check({"runs": [{"text": "Yield "}, {"quote": "91.0", "atom": "p1.T1.r3c2"}]}, con)
    seals = dict(con.execute("SELECT name, sha256 FROM seals").fetchall())
    con.close()
    rec = {"runs": [{"text": "Yield "}, {"quote": "91.0", "atom": "p1.T1.r3c2"}], "rendered": checked.text,
           "citations": checked.citations, "seals": seals, "door_version": answer.DOOR_VERSION}
    path = tmp_path / "a.json"
    path.write_text(json.dumps(rec))
    assert _ok(verify.verify_answer(path, synth_root))

    con = store.connect_write(synth_root)
    con.execute("UPDATE cells SET text = '19.0' WHERE id = 'p1.T1.r3c2'")
    con.close()
    lines = verify.verify_answer(path, synth_root)
    assert not _ok(lines) and any("REFUSES" in m for _, m in lines)


def test_an_answer_from_an_older_door_is_reported_not_rechecked(synth_root, tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"runs": [{"text": "x"}], "rendered": "x", "citations": [], "seals": {}}))
    lines = verify.verify_answer(path, synth_root)
    assert len(lines) == 1 and not lines[0][0] and "door v1" in lines[0][1]
