"""Grade a clause base against a gold file (paper 2's or paper 3's format).

    python grade.py GOLD.json RUN_DIR [--errors]

Per value, as in the paper-2 grader: role; then, for quantities (gold role result / setting / count /
background), property and the three binding slots. A slot is right when every required gold item is
matched and every predicted item matches a gold item or a tolerated one (`ok`). Items match by equality
or containment, case-folded. Two more numbers per slot:

  safe      no predicted item is wrong (missing items allowed): the precision a query relies on
  wrong     how many predicted items are wrong, over all quantities: the bindings that become false rows

A gold value the clause base did not extract is right when the gold says it is not a quantity (the
phantom "1" of "L^(cid:0) 1", the "2" of "2,3-BD"), and wrong in every slot otherwise.

Paper 2's gold names, for 28 values, a true subject that v1-v5 never offered (`subject_not_a_candidate`).
v6 can offer it, so it counts as an accepted subject (and a tolerated item in any slot).
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import duckdb

QUANTITY_ROLES = {"result", "setting", "count", "background"}
# paper 2's free-text "true subject not offered" notes, as synonym lists
NOT_OFFERED = {
    "the mixture": ["mixture"], "binary bacterial mixtures": ["binary bacterial mixtures", "bacterial mixtures"],
    "bacterial mixtures": ["bacterial mixtures", "mixtures"], "tube": ["tube"], "Cys": ["Cys"],
    "released nucleic acids/proteins": ["nucleic acids", "proteins"],
    "optical density / bacterial suspensions": ["bacterial suspensions"],
    "each strain's suspension": ["strain", "suspension"], "Au/Ag growth solution": ["Au/Ag growth solution"],
    "the first discriminant factor": ["discriminant factor"], "the second discriminant factor": ["discriminant factor"],
    "these bacteria": ["bacteria"], "the first principal component": ["first principal component"],
    "four strains (unnamed)": ["strains"], "ternary mixtures": ["ternary mixtures"],
}


def _m(a: str, b: str) -> bool:
    a, b = a.casefold(), b.casefold()
    return a == b or a in b or b in a


def _items(xs) -> list[list[str]]:
    """Gold items as synonym lists: paper 2 writes strings, paper 3 writes lists."""
    return [[x] if isinstance(x, str) else list(x) for x in xs]


def judge_slot(pred: list[str], required: list[list[str]], ok: list[str], alts=()) -> tuple[bool, bool, int]:
    """(right, safe, wrong items) for one slot. `alts` are other acceptable required-item lists."""
    tolerated = [x for item in required for x in item] + [x for a in alts for item in a for x in item] + list(ok)
    wrong = [p for p in pred if not any(_m(p, t) for t in tolerated)]
    right = False
    for req in [required] + list(alts):
        missed = [item for item in req if not any(_m(p, s) for p in pred for s in item)]
        if not missed and not wrong:
            right = True
    return right, not wrong, len(wrong)


def load(run):
    con = duckdb.connect(str(Path(run) / "clauses.duckdb"), read_only=True)
    rows = con.execute("SELECT id, role, property, about, measured_by, quantity, text, flags FROM measures").fetchall()
    meta = dict(con.execute("SELECT key, value FROM clause_meta").fetchall())
    con.close()
    return {r[0]: dict(zip(("id", "role", "property", "about", "by", "quantity", "text", "flags"), r)) for r in rows}, meta


def grade(gold_path, run):
    gold = json.loads(Path(gold_path).read_text())["mentions"]
    M, meta = load(run)
    t, errors = Counter(), []
    for mid, g in gold.items():
        t["values"] += 1
        p = M.get(mid)
        quantity = bool(set(g["role"]) & QUANTITY_ROLES)
        if p is None:
            t["role ok"] += not quantity
            if quantity:
                t["quantities"] += 1
                t["not extracted"] += 1
                errors.append(f"MISSING   {mid}: a quantity the clause base did not extract")
            continue
        role_ok = p["role"] in g["role"]
        t["role ok"] += role_ok
        if not role_ok:
            errors.append(f"ROLE      {mid} [{p['text']}] judged {p['role']}, gold {'/'.join(g['role'])}")
        if not quantity:
            continue
        t["quantities"] += 1
        prop_ok = p["property"] in g["property"]
        t["property ok"] += prop_ok
        if not prop_ok:
            errors.append(f"PROPERTY  {mid} [{p['text']}] judged {p['property']}, gold {'/'.join(g['property'])}")
        ok = list(g.get("ok", []))
        alts = [_items(a) for a in g.get("about_alt", [])]
        if "subject_not_a_candidate" in g:
            syn = NOT_OFFERED[g["subject_not_a_candidate"]]
            alts.append([syn])
            ok += syn
        every = role_ok and prop_ok
        for slot, pred in (("about", p["about"]), ("by", p["by"]), ("quantity", p["quantity"])):
            right, safe, wrong = judge_slot(pred, _items(g[slot]), ok, alts if slot == "about" else ())
            t[f"{slot} ok"] += right
            t[f"{slot} safe"] += safe
            t["wrong items"] += wrong
            every = every and right
            if not right:
                errors.append(f"{slot.upper():9} {mid} [{p['text']}] predicted {pred}, gold {g[slot]}"
                              + (f" alt {g.get('about_alt')}" if slot == "about" and g.get("about_alt") else "")
                              + (f" ok {g['ok']}" if g.get("ok") else ""))
        t["every slot"] += every
    return t, errors, meta


def summary(t, meta) -> dict:
    q = t["quantities"]
    return {"served": meta.get("served_models"), "calls": int(meta.get("calls", 0)),
            "questions": int(meta.get("questions", 0) or 0), "input_tokens": int(meta.get("input_tokens", 0)),
            "values": t["values"], "quantities": q, "role": t["role ok"], "property": t["property ok"],
            "about": t["about ok"], "about_safe": t["about safe"], "by": t["by ok"], "quantity": t["quantity ok"],
            "every_slot": t["every slot"], "wrong_items": t["wrong items"], "not_extracted": t["not extracted"]}


if __name__ == "__main__":
    gold_path, run = sys.argv[1], sys.argv[2]
    t, errors, meta = grade(gold_path, run)
    s = summary(t, meta)
    q = s["quantities"]
    print(f"{run}: served by {s['served']}, {s['calls']} calls, {s['questions']} questions, {s['input_tokens']} input tokens")
    print(f"  role {s['role']}/{s['values']}   property {s['property']}/{q}   about {s['about']}/{q} "
          f"(safe {s['about_safe']}/{q})   by {s['by']}/{q}   quantity {s['quantity']}/{q}   "
          f"every slot {s['every_slot']}/{q}   wrong bindings {s['wrong_items']}   not extracted {s['not_extracted']}")
    if "--errors" in sys.argv:
        for e in errors:
            print("  " + e)
