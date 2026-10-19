"""A corpus: several papers' substrates read as one, so a question can range over all of them.

Each paper keeps its own sealed substrate, built and checked as always (`ugrc ingest`, `ugrc verify
--pdf`). The corpus copies their rows into one DuckDB file, prefixing every id with the paper's key
("ensm-2021:p13.T4.r5c2"), and adds a `documents` relation: one row per paper with its key (`id`), file,
DOI, title, pages and the seals of the substrate it was copied from. Nothing is read from a PDF here, so
the corpus is a function of the substrates, and its receipt checks exactly that: the substrates still
carry the seals recorded, and rebuilding the corpus from them reproduces every row.

The door, the lineage and the question loop run on a corpus unchanged: an id is an id. Text runs on
across lines only within one paper's page.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import duckdb

from ugrc import store

KEY = re.compile(r"^[a-z0-9][a-z0-9._-]*$")      # a paper's key: the name of its substrate directory
# per relation, the columns that hold ids (prefixed), lists of ids (each prefixed), or a figure's PNG path
ID_COLUMNS = {
    "sources": {},
    "lines": {"id": "id", "region": "id"},
    "tables": {"id": "id", "continues": "id", "caption_lines": "ids"},
    "table_columns": {"id": "id", "table_id": "id"},
    "cells": {"id": "id", "table_id": "id"},
    "figures": {"id": "id", "caption_lines": "ids", "png": "png"},
    "figure_ocr": {"id": "id", "figure_id": "id"},
    "figure_facts": {"id": "id", "figure_id": "id"},
    "figure_reads": {"figure_id": "id"},
}
DOCUMENTS = """CREATE TABLE documents(id VARCHAR PRIMARY KEY, file VARCHAR, sha256 VARCHAR, pages INTEGER,
    doi VARCHAR, title VARCHAR, extractor_version VARCHAR, substrate VARCHAR, substrate_seals VARCHAR)"""
CORPUS_EXTRACTION = store.EXTRACTION_COVERS + ("documents",)
_DOI = re.compile(r"10\.\d{4,9}/[^\s,;()\[\]]+")


def _expr(col: str, kind: str | None, key: str) -> str:
    q = f'"{col}"'
    if kind == "id":
        return f"CASE WHEN {q} IS NULL THEN NULL ELSE '{key}:' || {q} END AS {q}"
    if kind == "ids":
        return f"list_transform({q}, x -> '{key}:' || x) AS {q}"
    if kind == "png":
        return f"'figures/{key}/' || regexp_replace({q}, '^figures/', '') AS {q}"
    return q


def _doi(src) -> str | None:
    """The first DOI printed on the paper's first two pages."""
    for (text,) in src.execute("SELECT text FROM lines WHERE page <= 2 ORDER BY page, line_no").fetchall():
        m = _DOI.search(text)
        if m:
            return m.group().rstrip(".")
    return None


def _title(src) -> str | None:
    """The first page's largest type, in reading order: the title as printed."""
    rows = src.execute("SELECT size, text FROM lines WHERE page = 1 ORDER BY line_no").fetchall()
    rows = [(s, t) for s, t in rows if len(t.split()) >= 2]
    if not rows:
        return None
    top = max(s for s, _ in rows)
    return " ".join(t for s, t in rows if s >= top - 0.5)[:400]


def _copy(con, root: Path, key: str, first: bool):
    src = duckdb.connect(str(store.db_path(root)), read_only=True)
    try:
        seals = dict(src.execute("SELECT name, sha256 FROM seals").fetchall())
        file, sha, pages, version = src.execute(
            "SELECT file, sha256, pages, extractor_version FROM sources").fetchone()
        doc = {"id": key, "file": file, "sha256": sha, "pages": pages, "doi": _doi(src), "title": _title(src),
               "extractor_version": version, "substrate": str(root.resolve()),
               "substrate_seals": json.dumps(seals, sort_keys=True)}
    finally:
        src.close()
    con.execute(f"ATTACH '{store.db_path(root)}' AS s (READ_ONLY)")
    try:
        for table, kinds in ID_COLUMNS.items():
            cols = [d[0] for d in con.execute(f'SELECT * FROM s."{table}" LIMIT 0').description]
            select = ", ".join([f"'{key}' AS doc"] + [_expr(c, kinds.get(c), key) for c in cols])
            verb = f'CREATE TABLE "{table}" AS' if first else f'INSERT INTO "{table}"'
            con.execute(f'{verb} SELECT {select} FROM s."{table}"')
        if first:
            con.execute("CREATE TABLE consts AS SELECT * FROM s.consts")
    finally:
        con.execute("DETACH s")
    store._insert(con, "documents", [doc])


def _assemble(out: Path, sources: list[Path]):
    """Write the corpus rows into <out>/atoms.duckdb (no PNGs, no checks)."""
    con = duckdb.connect(str(store.db_path(out)))
    try:
        con.execute(DOCUMENTS)
        for i, root in enumerate(sources):
            _copy(con, root, root.name, first=(i == 0))
        con.execute(store.SCHEMA[store.SCHEMA.index("CREATE VIEW atoms"):])
        con.execute("CREATE TABLE seals(name VARCHAR PRIMARY KEY, sha256 VARCHAR, covers VARCHAR)")
        for name, covers in (("extraction", CORPUS_EXTRACTION), ("readings", store.READINGS_COVERS)):
            con.execute("INSERT INTO seals VALUES (?, ?, ?)", [name, store.rows_sha(con, covers), ",".join(covers)])
    finally:
        con.close()


def build(out, sources, log=print) -> Path:
    """One corpus from substrate directories; each directory's name is the paper's key."""
    out = Path(out)
    if store.db_path(out).exists():
        raise SystemExit(f"{store.db_path(out)} exists — a corpus is built once; use a new --out directory")
    sources = sorted((Path(s) for s in sources), key=lambda p: p.name)
    bad = [p.name for p in sources if not KEY.match(p.name) or not store.db_path(p).exists()]
    if bad:
        raise SystemExit(f"not substrate directories with plain names (a-z, 0-9, . _ -): {bad}")
    if len({p.name for p in sources}) != len(sources):
        raise SystemExit("two substrates share a directory name; a paper's key must be unique")
    out.mkdir(parents=True, exist_ok=True)
    _assemble(out, sources)
    for root in sources:
        for png in sorted((root / "figures").glob("*.png")):
            dest = out / "figures" / root.name / png.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(png, dest)
    con = store.connect_readonly(out)
    try:
        n = con.execute("SELECT count(*) FROM atoms").fetchone()[0]
        docs = con.execute("SELECT id, doi FROM documents ORDER BY id").fetchall()
    finally:
        con.close()
    log(f"corpus: {len(docs)} documents, {n} atoms -> {store.db_path(out)}")
    for key, doi in docs:
        log(f"  {key}: {doi or 'no DOI found'}")
    return out


def is_corpus(con) -> bool:
    return con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'documents'").fetchone()[0] > 0


def verify(root) -> list[tuple[bool, str]]:
    """The corpus receipt: its rows still hash to its seals; every figure PNG holds its pinned pixels;
    each source substrate still carries the seals the corpus recorded; and rebuilding the corpus from
    those substrates reproduces both seals. (Each substrate's own receipt checks it against its PDF.)"""
    import tempfile

    from PIL import Image

    from ugrc import extract
    root = Path(root)
    out = []
    con = store.connect_readonly(root)
    try:
        seals = dict(con.execute("SELECT name, sha256 FROM seals").fetchall())
        for name, covers in (("extraction", CORPUS_EXTRACTION), ("readings", store.READINGS_COVERS)):
            got = store.rows_sha(con, covers)
            out.append((got == seals.get(name), f"corpus {name} seal {'holds' if got == seals.get(name) else 'BROKEN'}"))
        docs = con.execute("SELECT id, substrate, substrate_seals FROM documents ORDER BY id").fetchall()
        figs = con.execute("SELECT id, png, png_pixels_sha256 FROM figures ORDER BY id").fetchall()
    finally:
        con.close()
    bad_png = []
    for fid, png, pix in figs:
        p = root / png
        if not p.exists():
            bad_png.append(f"{fid} (missing)")
            continue
        with Image.open(p) as im:
            if extract.pixels_sha256(im.convert("RGB")) != pix:
                bad_png.append(fid)
    out.append((not bad_png, f"all {len(figs)} figure PNGs hold their pinned pixels" if not bad_png else
                f"figure PNGs that do NOT hold their pinned pixels: {bad_png[:6]}"))
    sources = []
    for key, substrate, recorded in docs:
        sub = Path(substrate)
        if not store.db_path(sub).exists():
            out.append((False, f"{key}: its substrate {sub} is gone"))
            continue
        c = store.connect_readonly(sub)
        now = json.dumps(dict(c.execute("SELECT name, sha256 FROM seals").fetchall()), sort_keys=True)
        c.close()
        out.append((now == recorded, f"{key}: substrate seals {'unchanged' if now == recorded else 'CHANGED'} since the corpus was built"))
        sources.append(sub)
    if len(sources) == len(docs):
        with tempfile.TemporaryDirectory() as tmp:
            _assemble(Path(tmp), sorted(sources, key=lambda p: p.name))
            c = duckdb.connect(str(store.db_path(Path(tmp))), read_only=True)
            again = dict(c.execute("SELECT name, sha256 FROM seals").fetchall())
            c.close()
        out.append((again == seals, "rebuilding the corpus from its substrates reproduces every row"
                    if again == seals else "rebuilding the corpus from its substrates gives DIFFERENT rows"))
    return out


# ─────────────────────────── the corpus's clause base ───────────────────────────

# per clause relation, the columns that hold ids (prefixed) or lists of ids (each prefixed)
CLAUSE_ID_COLUMNS = {
    "terms": {"sentence": "id"},
    "phrases": {"sentence": "id"},
    "sentences": {"id": "id", "atoms": "ids"},
    "aliases": {"sentence": "id", "atoms": "ids"},
    "measures": {"id": "id", "sentence": "id", "atoms": "ids"},
    "jev_calls": {"target": "id"},
}


def merge_clauses(root, clause_dirs) -> Path:
    """<root>/clauses.duckdb: the papers' clause bases as one, every id prefixed with its paper's key and a
    `doc` column added. Each part is matched to its paper by the substrate seals both recorded, so a clause
    base built on another version of a paper is refused, and the result records the corpus's own seals
    (the question loop attaches it only to this corpus)."""
    import datetime

    from ugrc import clauses
    root = Path(root)
    out = root / store.CLAUSE_DB
    if out.exists():
        raise SystemExit(f"{out} exists: build a new corpus clause base into a fresh corpus copy or remove it first")
    con = store.connect_readonly(root)
    try:
        docs = {k: (sub, json.loads(s)) for k, sub, s in
                con.execute("SELECT id, substrate, substrate_seals FROM documents").fetchall()}
        corpus_seals = dict(con.execute("SELECT name, sha256 FROM seals").fetchall())
    finally:
        con.close()
    parts = {}
    for d in clause_dirs:
        db = Path(d) / clauses.CLAUSE_DB
        c = duckdb.connect(str(db), read_only=True)
        meta = dict(c.execute("SELECT key, value FROM clause_meta").fetchall())
        seal = c.execute("SELECT sha256 FROM seals WHERE name = 'clauses'").fetchone()[0]
        c.close()
        built_on = json.loads(meta["substrate_seals"])
        same = [k for k, (_, s) in docs.items() if s == built_on]
        key = next((k for k in same if docs[k][0] == meta.get("substrate")), same[0] if len(same) == 1 else None)
        if key is None:
            raise SystemExit(f"{db}: built on {meta.get('substrate')}, which is no paper of this corpus "
                             "(no paper has its substrate seals, or several do and none its path)")
        if key in parts:
            raise SystemExit(f"{db}: a second clause base for {key}")
        parts[key] = {"path": db, "meta": meta, "seal": seal}
    missing = sorted(set(docs) - set(parts))
    if missing:
        raise SystemExit(f"no clause base for {missing}")
    versions = {p["meta"]["clause_version"] for p in parts.values()}
    if versions != {clauses.CLAUSE_VERSION}:
        raise SystemExit(f"the parts were built by clause door v{sorted(versions)}; this is v{clauses.CLAUSE_VERSION}")
    db = duckdb.connect(str(out))
    try:
        for i, key in enumerate(sorted(parts)):
            db.execute(f"ATTACH '{parts[key]['path']}' AS p (READ_ONLY)")
            for table, kinds in CLAUSE_ID_COLUMNS.items():
                cols = [r[0] for r in db.execute(f"DESCRIBE p.main.{table}").fetchall()]
                select = f"SELECT '{key}' AS doc, " + ", ".join(_expr(c, kinds.get(c), key) for c in cols) + \
                         f" FROM p.main.{table}"
                db.execute((f"CREATE TABLE {table} AS " if i == 0 else f"INSERT INTO {table} ") + select)
            db.execute("DETACH p")
        db.execute("CREATE TABLE clause_meta(key VARCHAR PRIMARY KEY, value VARCHAR)")
        db.execute("CREATE TABLE seals(name VARCHAR PRIMARY KEY, sha256 VARCHAR, covers VARCHAR)")
        total = lambda k: str(sum(int(p["meta"].get(k, 0)) for p in parts.values()))
        meta = {"clause_version": clauses.CLAUSE_VERSION,
                "requested_model": ",".join(sorted({p["meta"]["requested_model"] for p in parts.values()})),
                "served_models": ",".join(sorted({m for p in parts.values() for m in p["meta"]["served_models"].split(",")})),
                "substrate": str(root.resolve()), "substrate_seals": json.dumps(corpus_seals, sort_keys=True),
                "parts": json.dumps({k: {"clause_base": str(p["path"].resolve()), "clauses_seal": p["seal"],
                                         "built_at": p["meta"]["built_at"]} for k, p in sorted(parts.items())}),
                "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "calls": total("calls"), "questions": total("questions"),
                "input_tokens": total("input_tokens"), "output_tokens": total("output_tokens")}
        db.executemany("INSERT INTO clause_meta VALUES (?, ?)", list(meta.items()))
        db.execute("INSERT INTO seals VALUES (?, ?, ?)",
                   ["clauses", store.rows_sha(db, clauses.CLAUSE_COVERS), ",".join(clauses.CLAUSE_COVERS)])
    finally:
        db.close()
    return out
