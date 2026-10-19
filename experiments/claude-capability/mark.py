"""Mark, for every Claude answer, what in it rests on Claude being a strong reasoning model.

    python mark.py            # writes MARKS.md and marks.json from answers/*.json (+ grades.json if present)

Every mark is a fact read off the saved record, not a judgment of the text:
  the trace     each tool call: the SQL the model wrote, figures it viewed, refused submissions
  the runs      what it submitted: quotes, computed values, absence searches, its own prose
  the citations where the pointers landed: pages, and kinds of atom
  the probe     its category (a binding trap, a false premise, a cross-source check ...)

A mark says "a weaker model would have had to do this too", and names what could do it instead, so a
mark is also a to-do item for moving work off the LLM. Correctness comes from grades.json, written by
hand against each probe's expected answer; an answer that is right AND carries heavy marks is one whose
correctness may be owed to the model's capability.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).parent
# Claude Opus 5.5, $ per million tokens: input, output, cache write (5-minute, 1.25x input), cache read
PRICE = {"input_tokens": 4.00, "output_tokens": 20.00, "cache_creation_input_tokens": 5.00,
         "cache_read_input_tokens": 0.20}

# mark -> (what the model had to do, what could do it instead)
MARKS = {
    "sql":       ("wrote non-trivial SQL to find things (joins, aggregates, regex, subqueries)",
                  "code retrieves candidates by fixed queries; Jev picks among them"),
    "compute":   ("computed a value in SQL (a count, max, difference, ratio)",
                  "fixed query templates over the clause base; Jev picks the template and its rows"),
    "synthesis": ("combined facts from several places (pages, or text with tables and figures)",
                  "Jev selects the relevant atoms per sub-question; code assembles them"),
    "judgment":  ("had to resolve a trap: a binding, a false premise, a conflict between sources",
                  "Jev yes/no checks of each claimed binding and premise against the cited atoms"),
    "repair":    ("recovered from refusals (door or SQL engine) by reading the feedback and fixing it",
                  "the machine builds quotes and citations itself, so there is less to get wrong"),
    "absence":   ("decided the paper does not say something, and chose the search terms",
                  "Jev asks of the retrieved candidates whether any says it; code runs the searches"),
    "vision":    ("looked at a figure image",
                  "the stored figure readings (made once) are atoms Jev can select like any other"),
    "search":    ("ran a long search (many tool calls or turns)",
                  "retrieval by code, so the model does not navigate the database"),
    "prose":     ("put claims in its own words that no pointer checks (reasoning, comparisons)",
                  "Jev yes/no: does the cited atom support this sentence?"),
}
JUDGMENT_CATS = {"binding", "cross-source", "false premise", "false-premise", "bad-reading", "comparison"}
_SQL_HARD = [("join", r"\bjoin\b|\bfrom\s+\w+\s*(?:\w+\s*)?,\s*\w+"), ("aggregate", r"\b(?:count|sum|avg|min|max)\s*\(|\bgroup\s+by\b"),
             ("regex", r"regexp_|\blike\b.*%.*%|\bsimilar\s+to\b"), ("subquery", r"\(\s*select\b"), ("cte", r"^\s*with\b"),
             ("cast", r"\bcast\s*\(|\btry_cast\b")]
CLAIM_WORDS = re.compile(r"\b(higher|lower|more|less|larger|smaller|than|because|therefore|so|thus|while|whereas|"
                         r"both|only|all|none|every|inconsisten\w*|contradict\w*|differ\w*|same|likely|suggest\w*)\b", re.I)


def sql_features(q: str) -> set[str]:
    q = (q or "").lower()
    return {name for name, rx in _SQL_HARD if re.search(rx, q, re.S)}


def cost(usage: dict) -> float:
    return sum(usage.get(k, 0) * p for k, p in PRICE.items()) / 1e6


def facts(rec: dict) -> dict:
    trace = rec.get("trace") or []
    runs = rec.get("runs") or []
    cites = rec.get("citations") or []
    queries = [s.get("query") for s in trace if s["tool"] == "sql"]
    feats = set().union(*(sql_features(q) for q in queries)) if queries else set()
    computed = [r for r in runs if "sql" in r]
    for r in computed:
        feats |= sql_features(r["sql"])
    pages = {(c.get("source") or {}).get("page") for c in cites if (c.get("source") or {}).get("page") is not None}
    for c in cites:
        for s in c.get("sources") or []:
            if s.get("page") is not None:
                pages.add(s["page"])
    kinds = {(c.get("source") or {}).get("kind") for c in cites if c.get("source")}
    kinds |= {s.get("kind") for c in cites for s in c.get("sources") or []}
    kinds &= {"line", "cell", "column_header", "figure_fact", "ocr", "figure", "table"}
    prose = [r["text"] for r in runs if "text" in r and not r.get("support") and "absent" not in r]
    unchecked = [t for t in prose if len(t.strip()) > 60 and CLAIM_WORDS.search(t)]
    return {
        "sql_calls": len(queries), "sql_features": sorted(feats),
        "sql_refused": sum(1 for s in trace if s["tool"] == "sql" and s["refused"]),
        "door_refused": len(rec.get("door_refusals") or []),
        "refused_rules": sorted({r["rule"] for rr in rec.get("door_refusals") or [] for r in rr}),
        "figures_viewed": sum(1 for s in trace if s["tool"] == "view_figure"),
        "computed": len(computed), "quotes": sum(1 for r in runs if "quote" in r),
        "support": sum(1 for r in runs if r.get("support")), "absent": sum(1 for r in runs if "absent" in r),
        "pages": len(pages), "atom_kinds": sorted(k for k in kinds if k),
        "unchecked_prose": len(unchecked), "tool_calls": rec.get("tool_calls", 0), "turns": rec.get("turns", 0),
        "cost": round(cost(rec.get("usage") or {}), 4),
    }


def marks(f: dict, cat: str) -> list[str]:
    out = []
    if set(f["sql_features"]) - {"cast"}:
        out.append("sql")
    if f["computed"]:
        out.append("compute")
    if f["pages"] >= 3 or len(set(f["atom_kinds"]) & {"line", "cell", "figure_fact", "ocr"}) >= 2:
        out.append("synthesis")
    if cat in JUDGMENT_CATS:
        out.append("judgment")
    if f["door_refused"] or f["sql_refused"]:
        out.append("repair")
    if f["absent"]:
        out.append("absence")
    if f["figures_viewed"] or set(f["atom_kinds"]) & {"figure_fact", "ocr"}:
        out.append("vision")
    if f["tool_calls"] >= 7 or f["turns"] >= 6:
        out.append("search")
    if f["unchecked_prose"]:
        out.append("prose")
    return out


def level(ms: list[str]) -> str:
    heavy = {"compute", "judgment", "synthesis", "prose"}
    if len(ms) >= 4 or len(set(ms) & heavy) >= 2:
        return "high"
    return "medium" if len(ms) >= 2 else "low"


if __name__ == "__main__":
    grades = json.loads((HERE / "grades.json").read_text()) if (HERE / "grades.json").exists() else {}
    rows = []
    for p in sorted((HERE / "answers").glob("*.json")):
        rec = json.loads(p.read_text())
        f = facts(rec)
        ms = marks(f, rec.get("cat", ""))
        g = grades.get(p.stem, {})
        rows.append({"id": p.stem, "cat": rec.get("cat"), "question": rec["question"], "verdict": g.get("verdict"),
                     "note": g.get("note"), "marks": ms, "level": level(ms), **f})
    (HERE / "marks.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    lines = ["| id | category | verdict | capability level | marks | tools | SQL written | refused | $ |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | {r['cat']} | {r['verdict'] or '?'} | {r['level']} | {', '.join(r['marks']) or '-'} | "
                     f"{r['tool_calls']} | {', '.join(r['sql_features']) or '-'} | {r['door_refused'] + r['sql_refused']} | "
                     f"{r['cost']:.3f} |")
    (HERE / "MARKS.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
