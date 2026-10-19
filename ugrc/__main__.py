"""ugrc command line.

    python -m ugrc ingest PAPER.pdf --out DIR       PDF -> atoms (+ OCR of figures). Zero model.
    python -m ugrc corpus --out DIR SUBSTRATE...    several papers' substrates as one, to ask across them
    python -m ugrc corpus-clauses --corpus DIR CLAUSE_DIR...   the papers' clause bases as the corpus's one
    python -m ugrc read-figures --db DIR            a vision model reads each figure into facts
    python -m ugrc adopt-readings --from OLD --db DIR
                                                    carry readings into a re-extraction (same pixels only)
    python -m ugrc ask "QUESTION" --db DIR          an answer whose every number is a checked pointer
    python -m ugrc session QUESTIONS.txt --db DIR   many questions in ONE conversation (history kept)
    python -m ugrc verify --db DIR [--pdf PAPER.pdf] [ANSWER.json ...]
                                                    the receipt: re-check everything, zero model
    python -m ugrc recheck ANSWER.json --db DIR     re-resolve a stored answer on the current substrate (no model)
    python -m ugrc clauses --db DIR --out CDIR      Jev binds every value to what it is about -> CDIR/clauses.duckdb
    python -m ugrc clauses-replay --from CDIR --db DIR --out NEW
                                                    re-decide pinned judgments under the current door (no calls)
    python -m ugrc clauses-check CDIR --db DIR [--rerun]
                                                    the clause receipt (zero model; --rerun asks Jev again)
    python -m ugrc show ID --db DIR                 one atom (or table / figure) with its location
    python -m ugrc sql "SELECT ..." --db DIR        look at the atoms yourself
"""
from __future__ import annotations

import argparse
import json
import sys

from ugrc.refusal import Refusal


def _ingest(a):
    from ugrc import ocr, store
    ex = store.build(a.pdf, a.out)
    print(f"{ex.file}: {ex.pages} pages -> {len(ex.lines)} lines, {len(ex.tables)} table parts, "
          f"{len(ex.cells)} cells, {sum(1 for f in ex.figures if f['label'])} figures "
          f"(+{sum(1 for f in ex.figures if not f['label'])} uncaptioned images)")
    for d in ex.declined:
        print("  declined:", d)
    rows, declined = ocr.ocr_figures(a.pdf, ex.figures)
    con = store.connect_write(a.out)
    try:
        store._insert(con, "figure_ocr", rows)
        store.reseal(con, "readings")
    finally:
        con.close()
    print(f"OCR: {len(rows)} lines from {len({r['figure_id'] for r in rows})} figures")
    for d in declined:
        print("  declined:", d)
    print(f"substrate: {a.out}/atoms.duckdb")


def _read_figures(a):
    from ugrc import figures
    figures.read_all(a.db, model=a.model, only=a.only)


def _adopt(a):
    from ugrc import figures
    n = figures.adopt_readings(a.source, a.db)
    print(f"{n} figure reading(s) adopted")


def _ask(a):
    from ugrc import ask
    rec = ask.ask(a.db, a.question, model=a.model, effort=a.effort,
                  log=(lambda *_: None) if a.quiet else (lambda m: print(m, file=sys.stderr)))
    path = ask.save(a.db, rec)
    print(ask.format_answer(rec))
    print(f"\n(saved with full citation metadata: {path})", file=sys.stderr)


def _session(a):
    from pathlib import Path
    from ugrc import ask
    questions = [q.strip() for q in Path(a.questions).read_text().splitlines() if q.strip()]
    log = (lambda *_: None) if a.quiet else (lambda m: print(m, file=sys.stderr))

    def show(rec):
        path = ask.save(a.db, rec)
        print(f"\n=== [{rec['session_index'] + 1}] {rec['question']}\n" + ask.format_answer(rec))
        print(f"(saved: {path})", file=sys.stderr)
    ask.session(a.db, questions, model=a.model, effort=a.effort, log=log, on_answer=show)


def _corpus(a):
    from ugrc import corpus
    corpus.build(a.out, a.substrates)


def _corpus_clauses(a):
    from ugrc import corpus
    print(f"corpus clause base -> {corpus.merge_clauses(a.corpus, a.clause_dirs)}")


def _verify(a):
    from ugrc import corpus, store, verify
    con = store.connect_readonly(a.db)
    is_corpus = corpus.is_corpus(con)
    con.close()
    lines = corpus.verify(a.db) if is_corpus else verify.verify_substrate(a.db, a.pdf)
    for p in a.answers:
        lines += [(ok, f"{p}: {m}") for ok, m in verify.verify_answer(p, a.db)]
    for ok, m in lines:
        print(("ok   " if ok else "FAIL ") + m)
    green = all(ok for ok, _ in lines)
    print("receipt: GREEN" if green else "receipt: RED")
    return 0 if green else 1


def _recheck(a):
    """Re-run the door on a stored answer against the current substrate (e.g. after re-extraction).
    No model: the runs are the model's pointers; if every one still resolves, the answer stands and
    is saved again with the current seals, recording where it came from."""
    import json
    from datetime import datetime, timezone
    from pathlib import Path
    from ugrc import answer, ask, store
    rec = json.loads(Path(a.answer).read_text())
    con = store.connect_question(a.db)          # with its clause base, when one was built on this substrate
    checked = answer.check({"runs": rec["runs"]}, con)
    if not checked.ok:
        print(f"{a.answer}: no longer resolves on {a.db}\n" + checked.refusal_text())
        return 1
    seals = dict(con.execute("SELECT name, sha256 FROM seals").fetchall())
    same = checked.text == rec.get("rendered") and checked.citations == rec.get("citations")
    new = dict(rec, rendered=checked.text, citations=checked.citations, seals=seals, clause_seal=store.clause_seal(con)[0],
               door_version=answer.DOOR_VERSION, rechecked_from=str(a.answer),
               rechecked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    path = ask.save(a.db, new)
    print(f"{path}: every pointer resolves; " + ("text and citations identical" if same else
          "text " + ("identical" if checked.text == rec.get("rendered") else "CHANGED") + ", citations changed"))
    return 0


def _clauses(a):
    from ugrc import clauses
    clauses.build(a.db, a.out, workers=a.workers, log=lambda m: print(m, file=sys.stderr))


def _clauses_replay(a):
    from ugrc import clauses
    clauses.replay(a.db, a.source, a.out, log=lambda m: print(m, file=sys.stderr))


def _clauses_check(a):
    from ugrc import clauses
    lines = clauses.recheck(a.db, a.clauses, rerun=a.rerun, log=lambda m: print(m, file=sys.stderr))
    for ok, m in lines:
        print(("ok   " if ok else "FAIL ") + m)
    green = all(ok for ok, _ in lines)
    print("clause receipt: GREEN" if green else "clause receipt: RED")
    return 0 if green else 1


def _show(a):
    from ugrc import answer, store
    con = store.connect_readonly(a.db)
    print(json.dumps(answer._describe(con, a.id), indent=2, ensure_ascii=False, default=str))


def _sql(a):
    from ugrc import lineage, store
    con = store.connect_readonly(a.db)
    print(lineage.explore(con, a.query, max_rows=a.limit))


def main(argv=None):
    p = argparse.ArgumentParser(prog="ugrc", description="cite, don't find — for one PDF")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ingest"); s.add_argument("pdf"); s.add_argument("--out", required=True); s.set_defaults(fn=_ingest)
    s = sub.add_parser("corpus"); s.add_argument("--out", required=True); s.add_argument("substrates", nargs="+")
    s.set_defaults(fn=_corpus)
    s = sub.add_parser("corpus-clauses"); s.add_argument("--corpus", required=True); s.add_argument("clause_dirs", nargs="+")
    s.set_defaults(fn=_corpus_clauses)
    s = sub.add_parser("read-figures"); s.add_argument("--db", required=True); s.add_argument("--model")
    s.add_argument("--only", nargs="*"); s.set_defaults(fn=_read_figures)
    s = sub.add_parser("adopt-readings"); s.add_argument("--from", dest="source", required=True)
    s.add_argument("--db", required=True); s.set_defaults(fn=_adopt)
    s = sub.add_parser("ask"); s.add_argument("question"); s.add_argument("--db", required=True)
    s.add_argument("--model"); s.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    s.add_argument("--quiet", action="store_true"); s.set_defaults(fn=_ask)
    s = sub.add_parser("session"); s.add_argument("questions", help="a file with one question per line")
    s.add_argument("--db", required=True); s.add_argument("--model")
    s.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    s.add_argument("--quiet", action="store_true"); s.set_defaults(fn=_session)
    s = sub.add_parser("verify"); s.add_argument("answers", nargs="*"); s.add_argument("--db", required=True)
    s.add_argument("--pdf"); s.set_defaults(fn=_verify)
    s = sub.add_parser("recheck"); s.add_argument("answer"); s.add_argument("--db", required=True)
    s.set_defaults(fn=_recheck)
    s = sub.add_parser("clauses"); s.add_argument("--db", required=True); s.add_argument("--out", required=True)
    s.add_argument("--workers", type=int, default=8); s.set_defaults(fn=_clauses)
    s = sub.add_parser("clauses-replay"); s.add_argument("--from", dest="source", required=True)
    s.add_argument("--db", required=True); s.add_argument("--out", required=True); s.set_defaults(fn=_clauses_replay)
    s = sub.add_parser("clauses-check"); s.add_argument("clauses"); s.add_argument("--db", required=True)
    s.add_argument("--rerun", action="store_true"); s.set_defaults(fn=_clauses_check)
    s = sub.add_parser("show"); s.add_argument("id"); s.add_argument("--db", required=True); s.set_defaults(fn=_show)
    s = sub.add_parser("sql"); s.add_argument("query"); s.add_argument("--db", required=True)
    s.add_argument("--limit", type=int, default=80); s.set_defaults(fn=_sql)
    a = p.parse_args(argv)
    try:
        return a.fn(a) or 0
    except Refusal as r:
        print(r.render(), file=sys.stderr)
        return 2
    except Exception as e:
        name = type(e).__name__
        if name == "JevError":                   # first: its message names JEV_API_KEY, not Claude's key
            print(f"{e} (Jev is reached with JEV_API_KEY)", file=sys.stderr)
            return 3
        if name in ("AuthenticationError", "PermissionDeniedError") or "api_key" in str(e).lower() \
                or "authentication" in str(e).lower():
            print("No Claude credentials: export ANTHROPIC_API_KEY=... (or run `ant auth login`) and retry.", file=sys.stderr)
            return 3
        raise


if __name__ == "__main__":
    sys.exit(main())
