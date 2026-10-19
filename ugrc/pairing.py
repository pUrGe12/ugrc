"""The pairing gate: a quoted value said to be OF something is checked against the sentence that holds it.

answer.check proves that a quote's characters are in the document; it cannot tell whether "≈205" is NFA
811's capacity or NFA-F's. A quote run may name what its value is given for ({"quote", "atom", "of"}), and so
may a measure run ({"measure", "of"}: a clause-base value the machine quoted); for each such quote, once the
door has accepted the answer, this gate:
  1. finds the sentence of the prose that holds the quote (the clause base's `sentences`);
  2. lets the pairing stand when the clause base already gives this value for that thing (no call);
  3. otherwise asks the judge one yes/no question on that sentence, and refuses below CONFIRM_MIN,
     naming what the clause base gives the value for.
A quote outside the prose (a table cell, a figure fact) is left unchecked and recorded so; so is every
quote when no clause base is attached or the judge cannot be reached. Every verdict, with the judge's
request and response, goes into the answer's record: the receipt replays nothing and calls no model.
"""
from __future__ import annotations

import re

from ugrc import clauses, jev, store
from ugrc.refusal import Refusal

_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def _norm(s: str) -> str:
    return " ".join(s.casefold().split())


def _pattern(quote: str) -> re.Pattern:
    """The quote as it may sit in a sentence: any spacing between words, and a hyphen where a line broke
    a word ("discharge" in "dis-charge"); never inside a longer word or number."""
    words = []
    for w in quote.split():
        piece = ""
        for i, ch in enumerate(w):
            piece += re.escape(ch)
            if i + 1 < len(w) and ch.isalnum() and w[i + 1].isalnum():
                piece += r"(?:-\s?)?"
        words.append(piece)
    lead = r"(?<![\w.])" if quote[:1].isalnum() else ""
    tail = r"(?![\w])" if quote[-1:].isalnum() else ""
    return re.compile(lead + r"\s+".join(words) + tail, re.IGNORECASE)


def _sentence(con, atoms: list[str], quote: str):
    """(sentence id, text, start, end) of the prose sentence holding the quote, or None."""
    pat = _pattern(quote)
    for sid, text in con.execute("SELECT id, text FROM sentences WHERE list_contains(atoms, ?) ORDER BY id",
                                 [atoms[0]]).fetchall():
        m = pat.search(text or "")
        if m:
            return sid, text, m.start(), m.end()
    return None


def _same_value(measure_text: str, quote: str) -> bool:
    a, b = _NUM.findall(measure_text or ""), _NUM.findall(quote)
    return bool(a and b) and a[0] == b[0]


def _names(of: str, thing: str) -> bool:
    """`of` names this thing: the same words, or the thing's name standing whole inside `of`
    ("NFA 811 cathode" names "NFA 811"; "NFA" does not)."""
    o, t = _norm(of), _norm(thing)
    return o == t or re.search(r"(?<![\w])" + re.escape(t) + r"(?![\w])", o) is not None


def request(text: str, start: int, end: int, of: str) -> dict:
    """The judge's question: the sentence with the value marked, and one yes/no on the pairing."""
    v = "[[" + text[start:end] + "]]"
    q, yes, no = (t.format(value=v, x=f"“{of}”", the_property="a value") for t in clauses.CONFIRM["what"])
    return {"state": text[:start] + v + text[end:],
            "questions": {"c_of": {"type": "noul", "instructions": q, "criteria": {"true": yes, "false": no}}}}


def _one(con, entry: dict, judge) -> dict:
    quote, of = entry["quote"], entry["of"]
    src = entry.get("source") or {}
    atoms = src.get("atoms") or [src.get("atom")]
    base = {"quote": quote, "atom": atoms[0], "of": of}
    if not store.has_clauses(con):
        return {**base, "verdict": "unchecked", "why": "no clause base"}
    found = _sentence(con, atoms, quote)
    if found is None:
        return {**base, "verdict": "unchecked", "why": "not in a sentence of the prose (a table cell, a figure fact?)"}
    sid, text, start, end = found
    given = con.execute("SELECT text, about FROM measures WHERE sentence = ? AND len(list_intersect(atoms, ?)) > 0",
                        [sid, atoms]).fetchall()
    about = sorted({x for t, ab in given if _same_value(t, quote) for x in (ab or [])})
    if any(_names(of, x) for x in about):
        return {**base, "sentence": sid, "verdict": "agrees", "by": "clause base", "clause_about": about}
    req = request(text, start, end, of)
    try:
        resp = (judge or jev.ask)(req["state"], req["questions"])
        p = resp["answers"]["c_of"]["noul"]
    except (jev.JevError, KeyError, TypeError) as e:
        return {**base, "sentence": sid, "verdict": "unchecked", "why": f"judge unavailable: {e}", "request": req}
    ok = p >= clauses.CONFIRM_MIN
    return {**base, "sentence": sid, "verdict": "agrees" if ok else "refused", "by": "judge", "p": p,
            "clause_about": about, "request": req, "response": resp}


def _cites(run: dict) -> int:
    """How many citations answer.check made for this run, in order."""
    if "text" in run:
        return len(run.get("support") or []) + (1 if "absent" in run else 0)
    return 1


def check(con, runs: list, citations: list, judge=None) -> tuple[list[Refusal], list[dict]]:
    """(refusals, verdicts) for every quote of an accepted answer that names what it is a value `of`."""
    refusals, verdicts, k = [], [], 0
    for i, run in enumerate(runs):
        entry = citations[k] if ("quote" in run or "measure" in run) and k < len(citations) else None
        k += _cites(run)
        if not entry or not entry.get("of"):
            continue
        v = {**_one(con, entry, judge), "run": i}
        verdicts.append(v)
        if v["verdict"] == "refused":
            about = v.get("clause_about") or []
            refusals.append(Refusal(
                "pairing:judge",
                f"the judge reads {v['sentence']} as not giving {v['quote']!r} for {v['of']!r} (yes {v['p']:.2f})"
                + (f"; the clause base gives it for {', '.join(about)}" if about else ""),
                ["set `of` to what the sentence gives this value for"
                 + (f', e.g. "of": "{about[0]}"' if about else ""),
                 f"or quote the value the document gives for {v['of']}",
                 "or leave `of` out when the value is not given for one particular thing"],
                f"runs[{i}]"))
    return refusals, verdicts
