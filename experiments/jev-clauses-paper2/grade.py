"""Grade a clause base against gold.json, and compare two clause bases decision by decision.

    python grade.py RUN_DIR [OTHER_RUN_DIR]
"""
import json
import sys
from collections import Counter
from pathlib import Path

import duckdb

HERE = Path(__file__).parent
GOLD = json.loads((HERE / "gold.json").read_text())["mentions"]
QUANTITY_ROLES = {"result", "setting", "count"}


def _m(a, b):
    a, b = a.casefold(), b.casefold()
    return a == b or a in b or b in a


def set_ok(pred, gold, ok):
    missed = [g for g in gold if not any(_m(g, p) for p in pred)]
    extra = [p for p in pred if not any(_m(p, x) for x in gold + ok)]
    return not missed and not extra, missed, extra


def load(run):
    con = duckdb.connect(str(Path(run) / "clauses.duckdb"), read_only=True)
    rows = con.execute("SELECT id, role, property, about, measured_by, quantity, role_margin, flags, text "
                       "FROM measures").fetchall()
    calls = {sha: json.loads(resp) for sha, resp in con.execute("SELECT sha, response FROM jev_calls").fetchall()}
    meta = dict(con.execute("SELECT key, value FROM clause_meta").fetchall())
    sents = con.execute("SELECT id, modality, polarity, flags, text FROM sentences").fetchall()
    con.close()
    return {r[0]: dict(zip(("id", "role", "property", "about", "by", "quantity", "role_margin", "flags", "text"), r))
            for r in rows}, calls, meta, sents


def grade(run):
    M, _, meta, sents = load(run)
    tally, errors = Counter(), []
    for mid, g in GOLD.items():
        p = M[mid]
        tally["mentions"] += 1
        role_ok = p["role"] in g["role"]
        tally["role ok"] += role_ok
        if not role_ok:
            errors.append(f"ROLE      {mid} [{p['text']}] judged {p['role']}, gold {'/'.join(g['role'])}")
        if not set(g["role"]) & QUANTITY_ROLES:
            continue
        tally["quantities"] += 1
        prop_ok = p["property"] in g["property"]
        tally["property ok"] += prop_ok
        if not prop_ok:
            errors.append(f"PROPERTY  {mid} [{p['text']}] judged {p['property']}, gold {'/'.join(g['property'])}")
        for slot, pred in (("about", p["about"]), ("by", p["by"]), ("quantity", p["quantity"])):
            ok, missed, extra = set_ok(pred, g[slot], g["ok"])
            tally[f"{slot} ok"] += ok
            tally[f"{slot} strict"] += set_ok(pred, g[slot], [])[0]
            if slot == "about" and "subject_not_a_candidate" in g:
                tally["about: subject not a candidate"] += 1
                tally["about ok where subject not a candidate"] += ok
            if not ok:
                why = (f" missed {missed}" if missed else "") + (f" extra {extra}" if extra else "")
                note = f"  (true subject not offered: {g['subject_not_a_candidate']})" if "subject_not_a_candidate" in g else ""
                errors.append(f"{slot.upper():9} {mid} [{p['text']}]{why}{note}")
        tally["all slots ok"] += all(set_ok(pr, g[s], g["ok"])[0] for s, pr in
                                     (("about", p["about"]), ("by", p["by"]), ("quantity", p["quantity"]))) and prop_ok and role_ok
    return tally, errors, meta, sents


def compare(a, b):
    """Every question asked in both runs: did the judge pick the same label?"""
    _, ca, _, _ = load(a)
    _, cb, _, _ = load(b)
    same = differ = 0
    flips = []
    for sha in ca.keys() & cb.keys():
        for q, x in ca[sha]["answers"].items():
            y = cb[sha]["answers"].get(q)
            if y is None:
                continue
            if x.get("choice") == y.get("choice"):
                same += 1
            else:
                differ += 1
                flips.append((sha[:10], q, x.get("choice"), y.get("choice"), x.get("probabilities"), y.get("probabilities")))
    return same, differ, len(ca.keys() ^ cb.keys()), flips


if __name__ == "__main__":
    tally, errors, meta, sents = grade(sys.argv[1])
    n, q = tally["mentions"], tally["quantities"]
    print(f"{sys.argv[1]}: served by {meta['served_models']}, {meta['calls']} calls, "
          f"{meta['input_tokens']} in / {meta['output_tokens']} out tokens")
    print(f"  role        {tally['role ok']}/{n}")
    print(f"  property    {tally['property ok']}/{q}   (quantities: gold role result/setting/count)")
    print(f"  about       {tally['about ok']}/{q}   (of which {tally['about: subject not a candidate']} had the true "
          f"subject missing from the candidates; {tally['about ok where subject not a candidate']} of those bound nothing wrong)")
    print(f"  measured by {tally['by ok']}/{q}")
    print(f"  quantity    {tally['quantity ok']}/{q}")
    print(f"  every slot  {tally['all slots ok']}/{q}")
    print(f"  strict (no `ok` tolerances): about {tally['about strict']}/{q}, measured by {tally['by strict']}/{q}, "
          f"quantity {tally['quantity strict']}/{q}")
    print(f"  sentences: {Counter(s[1] for s in sents)}")
    print(f"  sentence flags: {sum(1 for s in sents if s[3])} sentences flagged")
    print("\nerrors:")
    for e in errors:
        print("  " + e)
    if len(sys.argv) > 2:
        same, differ, unmatched, flips = compare(sys.argv[1], sys.argv[2])
        print(f"\nre-run: {same} decisions identical, {differ} differ, {unmatched} requests not in both")
        for f in flips:
            print("  ", f)
