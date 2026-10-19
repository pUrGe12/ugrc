"""The receipt: re-check a substrate and a stored answer with no model in the loop.

  substrate   the stored rows still hash to their seals; with --pdf, the PDF's bytes hash to the
              recorded sha256 AND re-extracting them reproduces the extraction seal (the atoms are
              a function of the PDF, not a copy someone could edit); every figure PNG still holds
              the pixels its row pins, and every reading is pinned to those same pixels.
  answer      running the door again (the door that accepted it: the current one, or an older one it
              re-checks) on the stored runs reproduces the same text and the same citations, against the
              same seals; an answer that shows values of the clause base, or quotes a line found by a
              clause-base id, also needs that clause base, still holding the rows its seal and the answer
              pinned.

Green means the pointers re-resolve. It does not mean the answer is good: whether the right atoms
were cited for the question is a judgment, and the citations are there so a reader can make it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
from PIL import Image

from ugrc import answer, extract, store


def verify_substrate(root, pdf=None) -> list[tuple[bool, str]]:
    root = Path(root)
    con = store.connect_readonly(root)
    out = []
    try:
        seals = dict(con.execute("SELECT name, sha256 FROM seals").fetchall())
        for name, covers in (("extraction", store.EXTRACTION_COVERS), ("readings", store.READINGS_COVERS)):
            got = store.rows_sha(con, covers)
            out.append((got == seals.get(name), f"{name} seal {'holds' if got == seals.get(name) else 'BROKEN'} "
                                                 f"({got[:12]} vs pinned {str(seals.get(name))[:12]})"))
        file, sha, built_by, built_plumber = con.execute(
            "SELECT file, sha256, extractor_version, pdfplumber_version FROM sources").fetchone()
        for fid, png, pix in con.execute("SELECT id, png, png_pixels_sha256 FROM figures ORDER BY id").fetchall():
            p = root / png
            if not p.exists():
                out.append((False, f"{fid}: {png} is missing"))
                continue
            with Image.open(p) as im:
                ok = extract.pixels_sha256(im.convert("RGB")) == pix
            out.append((ok, f"{fid}: PNG {'holds' if ok else 'does NOT hold'} the pinned pixels"))
        for fid, read_pix, pix in con.execute(
                "SELECT r.figure_id, r.png_pixels_sha256, f.png_pixels_sha256 FROM figure_reads r "
                "JOIN figures f ON f.id = r.figure_id ORDER BY 1").fetchall():
            out.append((read_pix == pix, f"{fid}: reading {'is' if read_pix == pix else 'is NOT'} pinned to the figure's pixels"))
        if pdf is not None:
            data = Path(pdf).read_bytes()
            ok = hashlib.sha256(data).hexdigest() == sha
            out.append((ok, f"{Path(pdf).name}: bytes {'match' if ok else 'do NOT match'} the ingested {file}"))
            ex = extract.extract(pdf)
            mem = duckdb.connect()
            ex.file = file                              # the name it was ingested under
            store.load_extraction(mem, ex, versions=(built_by, built_plumber))
            again = store.rows_sha(mem, store.EXTRACTION_COVERS)
            mem.close()
            ok = again == seals.get("extraction")
            now = f"extractor v{extract.EXTRACTOR_VERSION}"
            built = "" if built_by == extract.EXTRACTOR_VERSION else f" (the substrate was built by extractor v{built_by})"
            out.append((ok, f"re-extracting the PDF with {now} " +
                        ("reproduces every atom" if ok else "gives DIFFERENT atoms") + built))
    finally:
        con.close()
    return out


def verify_answer(answer_path, root) -> list[tuple[bool, str]]:
    rec = json.loads(Path(answer_path).read_text())
    con = store.connect_question(root)
    out = []
    try:
        version = rec.get("door_version", "1")
        if version != answer.DOOR_VERSION and version not in answer.RECHECKS:
            out.append((False, f"answer was checked by door v{version}; the current door is v{answer.DOOR_VERSION} "
                               "and renders and cites differently — ask again to check it under the current door"))
            return out
        seals = dict(con.execute("SELECT name, sha256 FROM seals").fetchall())
        same = rec.get("seals") == seals
        out.append((same, "answer was checked against the current seals" if same else
                    f"seals moved since the answer was checked ({rec.get('seals')} -> {seals})"))
        if any(isinstance(r, dict) and "measure" in r for r in rec.get("runs") or []) or \
                any((c.get("source") or {}).get("named_by") for c in rec.get("citations") or []):
            pinned, now = store.clause_seal(con)
            if pinned is None:
                out.append((False, "the answer shows values of a clause base or quotes found by its ids, and no "
                                   "clause base built on this substrate is beside it"))
                return out
            ok = pinned == now == rec.get("clause_seal")
            out.append((ok, "the clause base holds the rows the answer was checked against" if ok else
                        f"the clause base changed (answer pinned {str(rec.get('clause_seal'))[:12]}, seal {pinned[:12]}, "
                        f"rows hash to {now[:12]})"))
        checked = answer.check({"runs": rec["runs"]}, con, door=version)
        if not checked.ok:
            out.append((False, "the door now REFUSES the stored answer:\n" + checked.refusal_text()))
            return out
        out.append((checked.text == rec["rendered"], "the answer text re-renders " +
                    ("identically" if checked.text == rec["rendered"] else "DIFFERENTLY")))
        a = json.dumps(checked.citations, sort_keys=True, default=str)
        b = json.dumps(rec["citations"], sort_keys=True, default=str)
        out.append((a == b, f"all {len(checked.citations)} citations re-resolve " +
                    ("identically" if a == b else "DIFFERENTLY")))
    finally:
        con.close()
    return out
