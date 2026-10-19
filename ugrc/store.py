"""The substrate: one DuckDB file holding every atom, sealed by hash.

Two seals, because there are two kinds of rows:
  extraction  — the deterministic read of the PDF (lines, tables, cells, figures, constants).
                Re-running the extractor on the same PDF bytes must reproduce it exactly
                (`ugrc verify --pdf` does exactly that).
  readings    — what READERS said about the figures: tesseract's OCR and a vision model's facts.
                Not reproducible by re-running (a model is not a function), so the rows are pinned
                once, with who read, what they were shown (pixel hash) and when.

Atom strengths, weakest last — the vocabulary every citation is labelled with:
  verbatim                    printed text of the PDF, read by position
  canon                       a constant with an exact definition (consts)
  ocr                         text tesseract read from a figure's pixels
  model-read, ocr-confirmed   a vision model's reading whose printed words OCR also found
  model-read                  a vision model's reading, unconfirmed
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pdfplumber

from ugrc import extract

DB_NAME = "atoms.duckdb"

STRENGTH_RANK = {"verbatim": 0, "canon": 0, "ocr": 1, "model-read, ocr-confirmed": 2, "model-read": 3}

# Exact constants and unit factors: the only numbers SQL may use that are not in the document.
# Every value is a definition (2019 SI or an SI prefix), never a measurement.
CONSTS = [
    ("K.kelvin_offset", 273.15, "K", "T[K] = T[°C] + 273.15 (SI definition)"),
    ("K.gas_constant", 8.31446261815324, "J mol^-1 K^-1", "R = N_A·k (exact, 2019 SI)"),
    ("K.avogadro", 6.02214076e23, "mol^-1", "N_A (exact, 2019 SI)"),
    ("K.boltzmann", 1.380649e-23, "J K^-1", "k (exact, 2019 SI)"),
    ("K.faraday", 96485.33212331001, "C mol^-1", "F = N_A·e (exact, 2019 SI)"),
    ("K.kpa_per_atm", 101.325, "kPa atm^-1", "1 atm = 101.325 kPa (definition)"),
    ("K.per_kilo", 1000.0, "1", "SI prefix kilo/milli: 1 kg = 1000 g, 1 L = 1000 mL, 1 g = 1000 mg"),
    ("K.per_mega", 1000000.0, "1", "SI prefix mega/micro"),
    ("K.s_per_min", 60.0, "s min^-1", "1 min = 60 s"),
    ("K.min_per_h", 60.0, "min h^-1", "1 h = 60 min"),
    ("K.h_per_day", 24.0, "h day^-1", "1 day = 24 h"),
]

SCHEMA = """
CREATE TABLE sources(file VARCHAR, sha256 VARCHAR, nbytes BIGINT, pages INTEGER,
                     extractor_version VARCHAR, pdfplumber_version VARCHAR);
CREATE TABLE lines(id VARCHAR PRIMARY KEY, page INTEGER, line_no INTEGER, text VARCHAR, size DOUBLE,
                   region VARCHAR, x0 DOUBLE, top DOUBLE, x1 DOUBLE, bottom DOUBLE);
CREATE TABLE tables(id VARCHAR PRIMARY KEY, label VARCHAR, number INTEGER, page INTEGER, continues VARCHAR,
                    caption VARCHAR, caption_lines VARCHAR[], columns_from VARCHAR, n_rows INTEGER,
                    n_cols INTEGER, x0 DOUBLE, top DOUBLE, x1 DOUBLE, bottom DOUBLE);
CREATE TABLE table_columns(id VARCHAR PRIMARY KEY, table_id VARCHAR, page INTEGER, col_no INTEGER,
                           header VARCHAR, x_from DOUBLE, x_to DOUBLE);
CREATE TABLE cells(id VARCHAR PRIMARY KEY, table_id VARCHAR, page INTEGER, row_no INTEGER, col_no INTEGER,
                   is_header BOOLEAN, text VARCHAR, x0 DOUBLE, top DOUBLE, x1 DOUBLE, bottom DOUBLE);
CREATE TABLE figures(id VARCHAR PRIMARY KEY, label VARCHAR, number INTEGER, page INTEGER, caption VARCHAR,
                     caption_lines VARCHAR[], x0 DOUBLE, top DOUBLE, x1 DOUBLE, bottom DOUBLE,
                     image_sha256 VARCHAR, png VARCHAR, png_pixels_sha256 VARCHAR,
                     png_width INTEGER, png_height INTEGER);
CREATE TABLE consts(id VARCHAR PRIMARY KEY, value DOUBLE, unit VARCHAR, definition VARCHAR);
CREATE TABLE figure_ocr(id VARCHAR PRIMARY KEY, figure_id VARCHAR, page INTEGER, line_no INTEGER,
                        text VARCHAR, conf DOUBLE, x0 DOUBLE, top DOUBLE, x1 DOUBLE, bottom DOUBLE,
                        reader VARCHAR);
CREATE TABLE figure_facts(id VARCHAR PRIMARY KEY, figure_id VARCHAR, page INTEGER, fact_no INTEGER,
                          statement VARCHAR, basis VARCHAR, printed_text VARCHAR[], quantity VARCHAR,
                          value DOUBLE, unit VARCHAR, condition VARCHAR, panel VARCHAR,
                          ocr_confirmed BOOLEAN, check_note VARCHAR, reader VARCHAR,
                          x0 DOUBLE, top DOUBLE, x1 DOUBLE, bottom DOUBLE);
CREATE TABLE figure_reads(figure_id VARCHAR PRIMARY KEY, reader VARCHAR, summary VARCHAR, panels VARCHAR,
                          raw_json VARCHAR, prompt_sha256 VARCHAR, png_pixels_sha256 VARCHAR,
                          response_id VARCHAR, read_at VARCHAR);
CREATE TABLE seals(name VARCHAR PRIMARY KEY, sha256 VARCHAR, covers VARCHAR);
CREATE VIEW atoms AS
      SELECT id, 'line' AS kind, page, text, 'verbatim' AS strength, region AS parent, x0, top, x1, bottom FROM lines
UNION ALL SELECT id, 'cell', page, text, 'verbatim', table_id, x0, top, x1, bottom FROM cells
UNION ALL SELECT id, 'column_header', page, header, 'verbatim', table_id, x_from, NULL, x_to, NULL
          FROM table_columns WHERE header IS NOT NULL
UNION ALL SELECT id, 'ocr', page, text, 'ocr', figure_id, x0, top, x1, bottom FROM figure_ocr
UNION ALL SELECT id, 'figure_fact', page, statement,
          CASE WHEN ocr_confirmed THEN 'model-read, ocr-confirmed' ELSE 'model-read' END,
          figure_id, x0, top, x1, bottom FROM figure_facts
UNION ALL SELECT id, 'const', NULL, definition, 'canon', NULL, NULL, NULL, NULL, NULL FROM consts;
"""

# The relations a model may read. Each has an `id` column holding an atom id (or a table/figure
# id), which is what row-level lineage records. Everything else in the file is bookkeeping.
QUERYABLE = ("atoms", "lines", "tables", "table_columns", "cells", "figures",
             "figure_ocr", "figure_facts", "consts", "documents")    # documents: a corpus's papers

# The clause base built on a substrate (clauses.duckdb beside it): what the judge read from the prose.
# The question loop may read these two relations to FIND things; an answer never cites them.
CLAUSE_DB = "clauses.duckdb"
CLAUSE_RELATIONS = ("measures", "sentences")

EXTRACTION_COVERS = ("sources", "lines", "tables", "table_columns", "cells", "figures", "consts")
READINGS_COVERS = ("figure_ocr", "figure_facts", "figure_reads")


def db_path(root) -> Path:
    return Path(root) / DB_NAME


def connect_readonly(root):
    """A read-only connection with external access off: no file reads, no COPY, no ATTACH — the
    only thing a query can see is this substrate."""
    return duckdb.connect(str(db_path(root)), read_only=True, config={"enable_external_access": False})


def connect_write(root):
    return duckdb.connect(str(db_path(root)))


def _sql_path(p: Path) -> str:
    return "'" + str(p.resolve()).replace("'", "''") + "'"


def connect_question(root):
    """The question loop's connection: the substrate, read-only, and, when <root>/clauses.duckdb was built
    on exactly this substrate (its recorded seals equal the substrate's), the clause base as the relations
    `measures` and `sentences`. External access is then switched off and the configuration locked, so a
    query sees these files and nothing else. A stale clause base is not attached."""
    root = Path(root)
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH {_sql_path(db_path(root))} AS s (READ_ONLY)")
    con.execute("USE s")
    clause_db = root / CLAUSE_DB
    if clause_db.exists():
        con.execute(f"ATTACH {_sql_path(clause_db)} AS c (READ_ONLY)")
        meta = dict(con.execute("SELECT key, value FROM c.main.clause_meta").fetchall())
        seals = dict(con.execute("SELECT name, sha256 FROM seals").fetchall())
        if json.loads(meta.get("substrate_seals") or "{}") == seals:
            _clause_views(con)
        else:
            con.execute("DETACH c")
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con


def _clause_views(con):
    """The clause base as the question loop reads it: plain names, the judge's probabilities rounded."""
    doc = "m.doc, " if "doc" in {r[0] for r in con.execute("DESCRIBE c.main.measures").fetchall()} else ""
    con.execute(f"""CREATE TEMP VIEW measures AS
        SELECT {doc}m.id, m.text, m.value, m.unit, m.key, m.lo, m.hi, m.role, round(m.role_p, 2) AS role_p,
               m.property, round(m.property_p, 2) AS property_p, m.about, m.measured_by AS method, m.quantity,
               s.page, s.modality, s.polarity, m.sentence, m.atoms
        FROM c.main.measures m LEFT JOIN c.main.sentences s ON s.id = m.sentence""")
    con.execute(f"""CREATE TEMP VIEW sentences AS
        SELECT {doc.replace('m.', 's.')}s.id, s.page, s.kind, s.text, s.modality, round(s.modality_p, 2) AS modality_p,
               s.polarity, round(s.polarity_p, 2) AS polarity_p, s.atoms
        FROM c.main.sentences s""")


def has_clauses(con) -> bool:
    return con.execute("SELECT count(*) FROM duckdb_views() WHERE temporary AND view_name = 'measures'").fetchone()[0] > 0


def clause_seal(con) -> tuple[str | None, str | None]:
    """(pinned, recomputed) seal of the clause base attached to a question connection; (None, None) when
    none is attached. The two differ when its rows were changed after it was sealed."""
    if not has_clauses(con):
        return None, None
    from ugrc.clauses import CLAUSE_COVERS
    pinned = con.execute("SELECT sha256 FROM c.main.seals WHERE name = 'clauses'").fetchone()
    return (pinned[0] if pinned else None), rows_sha(con, CLAUSE_COVERS, schema="c.main")


def rows_sha(con, tables, schema=None) -> str:
    """One hash over the named tables' rows in a canonical order. The same function writes and
    checks every seal, so writer and checker cannot drift. `schema` reads the tables of an attached
    file (the clause base beside a substrate); the hash is the same as reading that file directly."""
    h = hashlib.sha256()
    for t in tables:
        h.update(t.encode() + b"\0")
        rel = f'{schema}."{t}"' if schema else f'"{t}"'
        h.update(repr(con.execute(f"SELECT * FROM {rel} ORDER BY ALL").fetchall()).encode())
    return h.hexdigest()


def reseal(con, name):
    covers = EXTRACTION_COVERS if name == "extraction" else READINGS_COVERS
    con.execute("DELETE FROM seals WHERE name = ?", [name])
    con.execute("INSERT INTO seals VALUES (?, ?, ?)", [name, rows_sha(con, covers), ",".join(covers)])


def _insert(con, table, rows):
    if not rows:
        return
    cols = list(rows[0].keys())
    con.executemany(f'INSERT INTO "{table}" ({", ".join(cols)}) VALUES ({", ".join("?" * len(cols))})',
                    [[r[c] for c in cols] for r in rows])


def load_extraction(con, ex: extract.Extraction, versions=None):
    """Write one extraction into an empty substrate and seal it. `versions` (extractor, pdfplumber)
    defaults to the running ones; the receipt passes a stored substrate's own, so that re-extracting
    compares atoms with atoms and a version difference is reported on its own line."""
    con.execute(SCHEMA)
    extractor_version, plumber_version = versions or (extract.EXTRACTOR_VERSION, pdfplumber.__version__)
    con.execute("INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?)",
                [ex.file, ex.sha256, ex.nbytes, ex.pages, extractor_version, plumber_version])
    _insert(con, "lines", ex.lines)
    _insert(con, "tables", [{**t, "caption_lines": t.get("caption_lines", [])} for t in ex.tables])
    _insert(con, "table_columns", ex.columns)
    _insert(con, "cells", ex.cells)
    _insert(con, "figures", ex.figures)
    _insert(con, "consts", [dict(zip(("id", "value", "unit", "definition"), c)) for c in CONSTS])
    reseal(con, "extraction")
    reseal(con, "readings")


def build(pdf_path, root) -> extract.Extraction:
    """Extract the PDF into <root>/atoms.duckdb and <root>/figures/*.png. Refuses to overwrite an
    existing substrate: a rebuilt substrate under existing answers would move what they point at."""
    root = Path(root)
    if db_path(root).exists():
        raise SystemExit(f"{db_path(root)} exists — a substrate is built once; use a new --out directory")
    ex = extract.extract(pdf_path)
    (root / "figures").mkdir(parents=True, exist_ok=True)
    for fid, png in ex.pngs.items():
        (root / "figures" / f"{fid}.png").write_bytes(png)
    con = connect_write(root)
    try:
        load_extraction(con, ex)
    finally:
        con.close()
    (root / "manifest.json").write_text(json.dumps(
        {"file": ex.file, "sha256": ex.sha256, "pages": ex.pages, "lines": len(ex.lines),
         "tables": len(ex.tables), "cells": len(ex.cells), "figures": len(ex.figures),
         "declined": ex.declined}, indent=2))
    return ex
