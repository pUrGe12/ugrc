"""Clauses: the paper's values bound to what they are about, decided by a judge that can only choose.

Nothing in a clause is written. Every argument is a span the deterministic reader found in the text:

  sentences  the body, abstract and captions cut into sentences; offsets map back to line atoms
  mentions   every quantity in a sentence: its text, interval and unit, parsed, not judged
  terms      every named thing in the sentence: species, abbreviations, materials, methods
  aliases    the paper's own definitions, "long form (ABBR)", matched letter by letter

What structure cannot decide, a non-generative judge (Jev, `ugrc/jev.py`) decides by choosing among
those spans and a few closed labels:

  per mention          role (result / setting / count / background / identifier), property kind, and
                       which candidate words name its quantity ("LOD", "average length") or none
  per mention x term   the term's relation to the value (about / measured by / unrelated)
  per sentence         modality and polarity

The door then holds each decision against what the text itself shows (hedge and negation words, a
term in parentheses right after a value, "KEY =value") and FLAGS a disagreement; it never corrects one.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from ugrc.answer import _join

CLAUSE_VERSION = "5"     # v2: the quantity is one choice among the candidates, not a per-term relation
                         # v3: a quantity choice that names a term judged "about" or "measured by" is withheld
                         # v4: the layout decides the quantity where it can ("X of VALUE", "KEY =VALUE", a
                         #     coordinated list shares it); the judge is asked only for the rest
                         # v5: a term printed inside the value's own text is its unit ("CFU" in "9.2 × 10^7 CFU/mL")


# ─────────────────────────── sentences ───────────────────────────

_HEADING = re.compile(r"^\d+(?:\.\d+)*\.\s+[A-Z]")
_HEADING_NUMBER = re.compile(r"^\d+(?:\.\d+)*\.?\s*")
# A period after one of these does not end a sentence ("Fig. 2", "P. aeruginosa", "et al. [4]").
ABBREVIATIONS = frozenset("Fig Figs Eq Eqs Ref Refs al No Nos vs ca approx cf Tab Sect Dr Prof St Ltd Inc "
                          "viz resp e.g i.e etc".split())
_BOUNDARY = re.compile(r"[.!?][)\]\"'”’]*\s+(?=[A-Z(\[])")


@dataclass
class Sentence:
    id: str                 # "<first atom>:<offset in that atom>", stable while the extraction is
    page: int
    kind: str               # body | heading | caption
    text: str
    atoms: list             # [(atom id, start offset of that atom's text within `text`)]

    def atoms_at(self, i: int, j: int) -> list[str]:
        """The atoms that hold text[i:j]."""
        out = []
        for k, (aid, start) in enumerate(self.atoms):
            end = self.atoms[k + 1][1] if k + 1 < len(self.atoms) else len(self.text)
            if start < j and i < end:
                out.append(aid)
        return out


def _furniture(rows) -> set:
    """Running headers and footers: a line printed with the same text at the same height on more than
    one page, and the bare page number."""
    seen = defaultdict(set)
    for aid, page, _, text, _, top in rows:
        seen[(text.strip(), round(top))].add(page)
    return {aid for aid, page, _, text, _, top in rows
            if len(seen[(text.strip(), round(top))]) > 1 or text.strip() == str(page)}


def blocks(con):
    """Runs of lines read as one text: (kind, [(atom id, text)]). Captions are their own blocks; a
    numbered heading is its own block; a change of type size ends a block. The reference list is out."""
    rows = con.execute("SELECT id, page, line_no, text, size, top FROM lines ORDER BY page, line_no").fetchall()
    furniture = _furniture(rows)
    caption_of = {}
    for owner, ids in con.execute("SELECT id, caption_lines FROM figures UNION ALL "
                                  "SELECT id, caption_lines FROM tables").fetchall():
        for aid in ids or []:
            caption_of[aid] = owner
    out, captions = [], {}
    cur, cur_size, in_heading = [], None, False

    def close(kind):
        nonlocal cur
        if cur:
            out.append((kind, cur))
        cur = []

    for aid, page, _, text, size, _ in rows:
        if text.strip().lower() == "references":
            break
        if aid in furniture:
            continue
        if aid in caption_of:
            captions.setdefault(caption_of[aid], []).append((aid, text))
            continue
        size = round(size or 0, 1)
        if in_heading:
            if text[:1].islower() or cur[-1][1].endswith(("-", "–")):
                cur.append((aid, text))
                continue
            close("heading")
            in_heading = False
        ends_sentence = not cur or cur[-1][1].rstrip().endswith((".", ":", "?", "!"))
        if _HEADING.match(text) and ends_sentence:
            close("body")
            cur, in_heading, cur_size = [(aid, text)], True, size
            continue
        if cur and size != cur_size:
            close("body")
        cur.append((aid, text))
        cur_size = size
    close("heading" if in_heading else "body")
    out += [("caption", seg) for seg in captions.values()]
    return out


def sentences(con) -> list[Sentence]:
    out = []
    for kind, seg in blocks(con):
        text, starts = _join(seg, "tight")
        cuts = [0]
        if kind != "heading":
            for m in _BOUNDARY.finditer(text):
                word = re.findall(r"[\w.]+$", text[:m.start()])
                if word and (len(word[0]) == 1 and word[0].isupper() or word[0].rstrip(".") in ABBREVIATIONS):
                    continue
                cuts.append(m.end())
        cuts.append(len(text))
        for a, b in zip(cuts, cuts[1:]):
            raw = text[a:b]
            lead = len(raw) - len(raw.lstrip())
            a, sent = a + lead, raw.strip()
            if not sent:
                continue
            atoms = [(aid, max(0, s - a)) for (aid, _), s, e in zip(seg, starts, starts[1:] + [len(text)])
                     if s < a + len(sent) and a < e]
            first, off = atoms[0][0], a - starts[[x[0] for x in seg].index(atoms[0][0])]
            page = int(first[1:first.index(".")])
            out.append(Sentence(id=f"{first}:{max(off, 0)}", page=page, kind=kind, text=sent, atoms=atoms))
    return out


# ─────────────────────────── mentions ───────────────────────────

# Spans that hold digits but no quantity: figure/table references, citation brackets, links, emails.
_ITEM = r"S?\d+[A-Za-z]?(?:\s*[-–]\s*[a-z]\b)?"
_MASKS = [
    re.compile(rf"\b(?:Figs?\.?|Figures?|Tables?|Schemes?|Eqs?\.?|Equations?|Sections?|Refs?\.?|Notes?)\s*"
               rf"{_ITEM}(?:\s*(?:[-–,]|and|&)\s*{_ITEM})*"),
    re.compile(r"\[\d+(?:\s*[,–-]\s*\d+)*\]"),
    re.compile(r"https?://\S+|\bdoi\.\s?org/\S+|\b10\.\d{4,}/\S+|[\w.+-]+@[\w-]+\.[A-Za-z]{2,}[\w.]*"),
    re.compile(r"\(cid:\d+\)"),
]
_SCI = r"\d+(?:,\d{3})*(?:\.\d+)?(?:\s?[×x]\s?10\^[−-]?\d+)?|10\^[−-]?\d+"
_RATIO = r"\d+(?::\d+)+"
QUANTITY = re.compile(rf"(?P<cmp>[<>≤≥~≈]\s?)?(?P<sign>[−-])?(?P<a>{_RATIO}|{_SCI})"
                      rf"(?:(?P<sep>\s?(?:±|–)\s?|\s+to\s+)(?P<b>{_SCI}))?")
# General laboratory units, longest first; a unit must end at a word boundary.
_UNITS = sorted("""°C ° ◦C ◦ K % ‰ nm μm µm mm cm km m Å mL μL µL nL L mg μg µg ng kg g mM μM µM nM pM M mmol μmol
µmol mol h min s ms days day d hours hour weeks rpm ×g Hz kHz MHz mV V eV mW W kJ J kPa MPa Pa bar atm kDa Da
CFU wt% ppm ppb U fold times cycles""".split(), key=len, reverse=True)
_UNIT = "|".join(re.escape(u) for u in _UNITS)
UNIT = re.compile(rf"\s?(?:-(?=fold))?(?P<u>(?:{_UNIT})(?:\s?/\s?(?:{_UNIT})|\s(?:{_UNIT})\^?[−-]\d)*)(?![\w@])")
_LEFT_OK = set(" ([{=,;:'\"“‘×+\n")
_KEY_BEFORE = re.compile(r"(?P<key>[A-Za-z][\w^]*)\s?=\s?$|(?P<ph>\bpH)\s?$")
# An unmapped glyph right before a number may be its minus sign ("(cid:0) 0.0151" is -0.0151).
_UNMAPPED_BEFORE = re.compile(r"\(cid:\d+\)\s?$")


@dataclass
class Mention:
    id: str                 # "<sentence id>#<char offset>"
    sentence: str
    start: int
    end: int                # text[start:end] is the value with its unit
    value: str              # the number(s) as printed
    unit: str | None
    key: str | None         # "OD600" in "OD600 =0.0034"
    lo: float | None
    hi: float | None
    atoms: list = field(default_factory=list)
    note: str | None = None


def _num(s: str) -> float:
    s = s.replace(",", "").replace("−", "-").replace(" ", "")
    if "^" in s:
        base, _, exp = s.partition("^")
        mant = base[:-3] if base.endswith(("×10", "x10")) else None
        return (float(mant) if mant else 1.0) * 10 ** int(exp)
    return float(s)


def _interval(m) -> tuple:
    a = m.group("a")
    if ":" in a:
        return None, None                       # a ratio has no interval
    sign = -1 if m.group("sign") else 1
    lo = hi = sign * _num(a)
    cmp, sep, b = (m.group("cmp") or "").strip(), (m.group("sep") or "").strip(), m.group("b")
    if b and sep == "±":
        lo, hi = lo - _num(b), lo + _num(b)
    elif b:
        hi = _num(b)
    if cmp in ("<", "≤"):
        lo = None
    elif cmp in (">", "≥"):
        hi = None
    return lo, hi


def masked(text: str) -> list[bool]:
    mask = [False] * len(text)
    for rx in _MASKS:
        for m in rx.finditer(text):
            mask[m.start():m.end()] = [True] * (m.end() - m.start())
    return mask


def mentions(s: Sentence) -> list[Mention]:
    text, mask = s.text, masked(s.text)
    if s.kind == "heading":
        n = _HEADING_NUMBER.match(text)
        if n:
            mask[:n.end()] = [True] * n.end()
    out = []
    for m in QUANTITY.finditer(text):
        i, j = m.start(), m.end()
        if any(mask[i:j]):
            continue
        if i > 0 and text[i - 1] not in _LEFT_OK:
            continue                             # glued to a word on the left: "OD600", "S17", "2025ZDSYS"
        u = UNIT.match(text, j)
        if u:
            unit, j2 = u.group("u"), u.end()
        else:
            unit, j2 = None, j
            nxt = text[j:j + 2]
            if nxt and (nxt[:1].isalnum() or nxt[:1] in "@_" or (nxt[:1] in "-–" and nxt[1:2].isalpha())):
                continue                         # glued to a word on the right: "2D", "4-MPBA"
        k = _KEY_BEFORE.search(text[:i])
        lo, hi = _interval(m)
        note = None
        if _UNMAPPED_BEFORE.search(text[:i]):
            lo = hi = None
            note = "an unmapped glyph precedes the number: its sign is unknown"
        out.append(Mention(id=f"{s.id}#{i}", sentence=s.id, start=i, end=j2, value=text[i:j].strip(),
                           unit=unit, key=(k.group("key") or k.group("ph")) if k else None, lo=lo, hi=hi,
                           atoms=s.atoms_at(i, j2), note=note))
    return out


# ─────────────────────────── terms and aliases ───────────────────────────

_SPECIES = re.compile(r"\b([A-Z])\.\s?([a-z]{3,})\b")
_TOKEN = re.compile(r"[A-Za-z0-9@\-–/+α-ωµ]+")


def _is_term(tok: str) -> bool:
    return (sum(c.isupper() for c in tok) >= 2 or "@" in tok) and any(c.isalpha() for c in tok)


def terms(text: str, genus_of: dict | None = None) -> list[tuple[str, int]]:
    """Named things in `text`, in order of first appearance: (surface, offset). `genus_of` maps a
    species epithet to the genus names the paper spells out for it ("aeruginosa" -> {"Pseudomonas"})."""
    mask = masked(text)
    found = {}

    def add(t, i):
        t = t.strip("-–/+")
        if t and t not in found and not any(mask[i:i + len(t)]):
            found[t] = i

    for m in _SPECIES.finditer(text):
        add(m.group(), m.start())
    for genus_epithets in (genus_of or {}).items():
        epithet, genera = genus_epithets
        for g in genera:
            for m in re.finditer(rf"\b{re.escape(g)}\s{re.escape(epithet)}\b", text):
                add(m.group(), m.start())
    for m in _TOKEN.finditer(text):
        tok = m.group().strip("-–/+")
        if not tok:
            continue
        start = m.start() + m.group().index(tok)
        parts = tok.split("/")
        if all(_is_term(p) for p in parts):
            add(tok, start)
        if len(parts) > 1:
            off = start
            for p in parts:
                if _is_term(p):
                    add(p, off)
                off += len(p) + 1
    return sorted(found.items(), key=lambda kv: kv[1])


def genus_names(all_text: str) -> dict:
    """Spelled-out genus names, only where the paper also abbreviates the same species ("P. aeruginosa"
    beside "Pseudomonas aeruginosa")."""
    abbreviated = {(m.group(1), m.group(2)) for m in _SPECIES.finditer(all_text)}
    out = defaultdict(set)
    for m in re.finditer(r"\b([A-Z][a-z]{3,})\s([a-z]{3,})\b", all_text):
        if (m.group(1)[0], m.group(2)) in abbreviated:
            out[m.group(2)].add(m.group(1))
    return dict(out)


_PAREN = re.compile(r"\(([^()]{1,60})\)")


def _long_form(abbr: str, before: str) -> str | None:
    """Schwartz & Hearst (2003): the shortest run of words before the parenthesis whose letters spell
    the abbreviation in order, the first letter starting a word."""
    letters = [c.lower() for c in abbr if c.isalnum()]
    if len(letters) < 2:
        return None
    words = before.split()
    lf = " ".join(words[-min(len(letters) + 5, 2 * len(letters)):])
    s, i = len(letters) - 1, len(lf) - 1
    while s >= 0:
        c = letters[s]
        while i >= 0 and (lf[i].lower() != c or (s == 0 and i > 0 and lf[i - 1].isalnum())):
            i -= 1
        if i < 0:
            return None
        i -= 1
        s -= 1
    start = lf.rfind(" ", 0, i + 1) + 1
    out = lf[start:].strip(" ,;:")
    return out if len(out) > len(abbr) else None


def aliases(s: Sentence) -> list[dict]:
    """The paper's own definitions in this sentence: "circular dichroism (CD)", "(4-MPBA, BA)". Every
    term listed in one parenthesis names the long form that the first matching one spells."""
    out = []
    for m in _PAREN.finditer(s.text):
        items = [x.strip() for x in re.split(r"[,;]", m.group(1))]
        abbrs = [x for x in items if x and _is_term(x) and " " not in x]
        if not abbrs:
            continue
        before = s.text[:m.start()]
        lf = next((f for f in (_long_form(a, before) for a in abbrs) if f), None)
        if lf is None:
            continue
        i = before.rindex(lf)
        for a in abbrs:
            out.append({"term": a, "long_form": lf, "sentence": s.id, "atoms": s.atoms_at(i, m.end())})
    return out


# ─────────────────────────── the judge's questions ───────────────────────────

ROLE = {
    "result": "a value this work measured, observed or obtained as an outcome",
    "setting": "an amount, condition or parameter this work chose or used in a procedure",
    "count": "how many items, samples, replicates, groups or kinds there were",
    "background": "a value from other work or general knowledge, not obtained in this work",
    "identifier": "not a quantity: part of a name, code, date, address, version or grant number",
}
PROPERTY = {
    "detection limit": "the lowest amount or concentration that can be detected",
    "concentration": "how much of a substance or organism is in a volume (molar, mass or cell concentration, optical density)",
    "amount": "a volume, mass or quantity of material taken or added",
    "temperature": "a temperature",
    "duration": "a length of time",
    "speed": "a rotation speed or centrifugal force",
    "wavelength": "a wavelength or spectral position",
    "size": "a length, diameter or other dimension",
    "ratio": "a ratio or proportion between components",
    "accuracy": "a rate of correct classification or identification",
    "share": "a percentage or fraction of a total (variance explained, yield)",
    "acidity": "a pH",
    "signal": "a measured signal or optical quantity (absorbance, dissymmetry factor, intensity)",
    "other": "none of these",
}
RELATION = {
    "about": "the value is a property or an amount of this material, organism, sample or substance",
    "measured by": "this is the technique, instrument, spectrum or signal with which the value was obtained",
    "unrelated": "this is neither what the value describes nor how it was obtained",
}
NO_QUANTITY = "none of these"
MODALITY = {
    "result": "reports what this work observed, measured or obtained",
    "method": "describes what was done, prepared or used in this work",
    "interpretation": "explains, infers or concludes why something happened or what it means",
    "possibility": "states something only as possible, likely or suggested",
    "background": "reports prior work, general knowledge, motivation or aims",
    "other": "a heading, label, name list or a statement of no claim (authorship, funding, availability)",
}
POLARITY = {
    "affirmed": "says that something is the case",
    "negated": "says that something is not the case, is absent, or fails",
}
DEFINES = {
    "yes": "the passage introduces the abbreviation as exactly this phrase",
    "no": "the phrase is not what the abbreviation stands for: wrong, with extra words, or missing words",
}
MARK = ("[[", "]]")


# Closed-class English words: a phrase next to a value stops at one of these.
DETERMINERS = frozenset("a an the each every its their this these those our such both all any some".split())
FUNCTION_WORDS = DETERMINERS | frozenset("""of in at on for with to from by into onto over under between across
among through during after before upon via and or but nor while whereas which that where when as than versus vs
was were is are be been being has have had do does did will would can could may might should must it they we
them us respectively""".split())
_WORD_TOKEN = re.compile(r"[^\s()\[\]×]+")
_PUNCT_END = ",;:."


def _phrase_forward(text: str, i: int) -> str | None:
    words = []
    for t in _WORD_TOKEN.finditer(text, i):
        if text[i:t.start()].strip():
            break                                # a bracket between words ends the phrase
        w = t.group()
        bare = w.rstrip(_PUNCT_END)
        if bare.lower() in FUNCTION_WORDS and not (not words and bare.lower() in DETERMINERS):
            break
        words.append(bare)
        i = t.end()
        if bare != w:
            break
    while words and words[0].lower() in DETERMINERS:
        words.pop(0)
    return " ".join(words) or None


def _phrase_backward(text: str, j: int) -> str | None:
    words = []
    for t in reversed(list(_WORD_TOKEN.finditer(text, 0, j))):
        w = t.group()
        if text[t.end():j].strip() or w[-1:] in _PUNCT_END or w.lower() in FUNCTION_WORDS:
            break                                # a bracket, a punctuation mark or a closed-class word
        words.insert(0, w)
        j = t.start()
    return " ".join(words) or None


def phrases(text: str, m: Mention) -> list[str]:
    """Common-noun phrases a value may be about, cut at closed-class words: "160 μL of [each bacterial
    suspension]", "[an average length] of 90 nm", "4 [signals]"."""
    out = []
    after_of = re.match(r"\s+of\s+", text[m.end:])
    if after_of:
        out.append(_phrase_forward(text, m.end + after_of.end()))
    elif m.unit is None:                         # a bare count names what it counts: "4 [signals]"
        nxt = re.match(r"\s([A-Za-z][\w-]*)", text[m.end:])
        if nxt and nxt.group(1).lower() not in FUNCTION_WORDS:
            out.append(nxt.group(1))
    before = re.search(r"(?:^|\s)of\s+(?:[A-Za-z][\w^]*\s?=\s?)?$", text[:m.start])
    if before:
        out.append(_phrase_backward(text, before.start()))
    return [p for p in out if p]


def candidates(cur: Sentence, prev: Sentence | None, genus: dict, ms=()) -> list[tuple[str, str]]:
    """What a value in `cur` may be bound to: the named terms of this sentence and the one before, and
    the phrases beside every value of this sentence. (surface, "this sentence" | "the sentence before")."""
    here = [t for t, _ in terms(cur.text, genus)]
    for m in ms:
        here += [p for p in phrases(cur.text, m) if p not in here]
    before = [t for t, _ in terms(prev.text, genus)] if prev else []
    return [(t, "this sentence") for t in here] + [(t, "the sentence before") for t in before if t not in here]


def mention_request(m: Mention, cur: Sentence, prev: Sentence | None, cands, long_forms: dict) -> dict:
    marked = cur.text[:m.start] + MARK[0] + cur.text[m.start:m.end] + MARK[1] + cur.text[m.end:]
    state = (prev.text + "\n" + marked) if prev else marked
    v = cur.text[m.start:m.end]
    qs = {
        "role": {"type": "choice", "criteria": ROLE,
                 "instructions": f"What kind of number is the value marked {MARK[0]}{v}{MARK[1]}?"},
        "property": {"type": "choice", "criteria": PROPERTY,
                     "instructions": f"What property is the value marked {MARK[0]}{v}{MARK[1]} a value of?"},
    }
    for k, (t, _) in enumerate(cands):
        gloss = f" ({long_forms[t]})" if t in long_forms else ""
        qs[f"t{k}"] = {"type": "choice", "criteria": RELATION,
                       "instructions": f"How is “{t}”{gloss} related to the value marked {MARK[0]}{v}{MARK[1]}?"}
    if cands:
        options = {t: long_forms.get(t, f"the words “{t}” in the passage") for t, _ in cands}
        qs["quantity"] = {"type": "choice", "criteria": {**options, NO_QUANTITY: "no listed words name it"},
                          "instructions": f"Which words name the quantity that the value marked {MARK[0]}{v}{MARK[1]} "
                                          f"is a value of?"}
    return {"state": state, "questions": qs}


def sentence_request(s: Sentence, defs: list) -> dict:
    qs = {
        "modality": {"type": "choice", "criteria": MODALITY, "instructions": "What does this passage do?"},
        "polarity": {"type": "choice", "criteria": POLARITY,
                     "instructions": "Does the passage's main statement affirm or deny something?"},
    }
    for k, d in enumerate(defs):
        qs[f"d{k}"] = {"type": "choice", "criteria": DEFINES,
                       "instructions": f"Does the passage define “{d['term']}” as “{d['long_form']}”?"}
    return {"state": s.text, "questions": qs}


def decision(answer: dict) -> dict:
    """A choice as the clause keeps it: the label, its probability, and the margin to the runner-up."""
    probs = sorted(answer.get("probabilities", {}).values(), reverse=True) + [0.0, 0.0]
    return {"label": answer["choice"], "p": answer.get("probabilities", {}).get(answer["choice"]),
            "margin": round(probs[0] - probs[1], 4)}


# ─────────────────────────── the door ───────────────────────────

HEDGES = frozenset("may might could possibly possible potentially potential likely unlikely suggest suggests "
                   "suggested suggesting appear appears appeared seem seems seemed presumably probably perhaps "
                   "would putative hypothesize hypothesized".split())
NEGATIONS = frozenset("not no none neither nor without cannot never fail fails failed unable absence absent "
                      "lack lacks lacked".split())
_WORDS = re.compile(r"[A-Za-z]+")


def sentence_flags(s: Sentence, modality: str, polarity: str) -> tuple[list, list, list]:
    words = {w.lower() for w in _WORDS.findall(s.text)}
    hedges, negs, flags = sorted(words & HEDGES), sorted(words & NEGATIONS), []
    if hedges and modality in ("result", "method"):
        flags.append(f"hedge word ({', '.join(hedges)}) but judged {modality}")
    if modality == "possibility" and not hedges:
        flags.append("judged possibility but no hedge word")
    if negs and polarity == "affirmed":
        flags.append(f"negation word ({', '.join(negs)}) but judged affirmed")
    if polarity == "negated" and not negs:
        flags.append("judged negated but no negation word")
    return hedges, negs, flags


_OF_BEFORE = re.compile(r"(?:^|\s)of\s+(?:[A-Za-z][\w^]*\s?=\s?)?$")
_LIST_GAP = re.compile(r"^(?:\s*,\s*(?:and\s+|or\s+)?|\s+(?:and|or)\s+)$")


def structural_bindings(m: Mention, cur: Sentence, cands) -> dict:
    """What the layout alone decides about a value, {term: (role, why)}:
      quantity  the words before "of VALUE" ("an [average length] of 90 nm", "an [LOD] of OD600 =0.0034")
                and the key of "KEY =VALUE" ("[OD600] =0.02–0.2")
      bound     the term opening a parenthesis right after the value ("0.0034 ([CD], Fig. S17a)"): it is
                bound to the value, and the judge says how
      unit      a term printed inside the value's own text ("9.2 × 10^7 [CFU]/mL")"""
    names = {t for t, _ in cands}
    out = {t: ("unit", "printed inside the value") for t in names if t in cur.text[m.start:m.end]}
    before = _OF_BEFORE.search(cur.text[:m.start])
    if before:
        q = _phrase_backward(cur.text, before.start())
        if q in names:
            out[q] = ("quantity", "the words before “of” the value")
    if m.key and m.key in names:
        out[m.key] = ("quantity", "the key of KEY =value")
    after = re.match(r"\s?\(([^,;()]+)[,;)]", cur.text[m.end:])
    if after and after.group(1).strip() in names and after.group(1).strip() not in out:
        out[after.group(1).strip()] = ("bound", "in parentheses right after the value")
    return out


def share_lists(ms: list, text: str, structure: dict) -> None:
    """Values in one coordinated list ("ratios of 1:0, 1:4, 1:8, and 0:1") share the quantity the layout
    gives any one of them, when it gives exactly one."""
    runs, run = [], [ms[0]] if ms else []
    for a, b in zip(ms, ms[1:]):
        if _LIST_GAP.match(text[a.end:b.start]):
            run.append(b)
        else:
            runs.append(run)
            run = [b]
    if run:
        runs.append(run)
    for run in runs:
        qs = {t for m in run for t, (role, _) in structure[m.id].items() if role == "quantity"}
        if len(run) > 1 and len(qs) == 1:
            q = qs.pop()
            for m in run:
                structure[m.id].setdefault(q, ("quantity", "shared by the list the value is in"))


def measure_flags(role: str, rel: dict, structure: dict, cands) -> list:
    where = dict(cands)
    flags = [f"“{t}” is bound by structure ({why}) but judged unrelated"
             for t, (kind, why) in structure.items() if kind == "bound" and rel.get(t) == "unrelated"]
    about = [t for t, r in rel.items() if r == "about"]
    if role in ("result", "setting") and not about:
        flags.append(f"a {role} about nothing named")
    flags += [f"“{t}” bound across sentences" for t, r in rel.items()
              if r != "unrelated" and where.get(t) == "the sentence before"]
    return flags


# ─────────────────────────── build: ask, decide, store ───────────────────────────

CLAUSE_DB = "clauses.duckdb"
CLAUSE_SCHEMA = """
CREATE TABLE clause_meta(key VARCHAR PRIMARY KEY, value VARCHAR);
CREATE TABLE sentences(id VARCHAR PRIMARY KEY, page INTEGER, kind VARCHAR, text VARCHAR, atoms VARCHAR[],
                       modality VARCHAR, modality_p DOUBLE, modality_margin DOUBLE,
                       polarity VARCHAR, polarity_p DOUBLE, polarity_margin DOUBLE,
                       hedges VARCHAR[], negations VARCHAR[], flags VARCHAR[]);
CREATE TABLE aliases(term VARCHAR, long_form VARCHAR, sentence VARCHAR, atoms VARCHAR[],
                     verdict VARCHAR, p DOUBLE, margin DOUBLE);
CREATE TABLE measures(id VARCHAR PRIMARY KEY, sentence VARCHAR, atoms VARCHAR[], text VARCHAR, value VARCHAR,
                      unit VARCHAR, key VARCHAR, lo DOUBLE, hi DOUBLE, note VARCHAR,
                      role VARCHAR, role_p DOUBLE, role_margin DOUBLE,
                      property VARCHAR, property_p DOUBLE, property_margin DOUBLE,
                      about VARCHAR[], measured_by VARCHAR[], quantity VARCHAR[],
                      quantity_p DOUBLE, quantity_margin DOUBLE,
                      relations JSON, structure JSON, flags VARCHAR[]);
CREATE TABLE jev_calls(sha VARCHAR PRIMARY KEY, kind VARCHAR, target VARCHAR, request JSON, response JSON,
                       model VARCHAR, called_at VARCHAR);
CREATE TABLE seals(name VARCHAR PRIMARY KEY, sha256 VARCHAR, covers VARCHAR);
"""
CLAUSE_COVERS = ("sentences", "aliases", "measures", "jev_calls")


def _sha(obj) -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def plan(con):
    """Everything deterministic: the sentences, mentions, candidates, structure and the exact request
    each judgment is asked with. Same substrate, same plan."""
    return plan_sentences(sentences(con))


def plan_sentences(S: list[Sentence]):
    genus = genus_names(" ".join(s.text for s in S))
    items = []                                   # (kind, target, request, context)
    prev = None
    for s in S:
        defs = aliases(s)
        items.append(("sentence", s.id, sentence_request(s, defs), {"sentence": s, "defs": defs}))
        ms = mentions(s)
        cands = candidates(s, prev, genus, ms) if ms else []
        long_forms = {}
        structure = {m.id: structural_bindings(m, s, cands) for m in ms}
        share_lists(ms, s.text, structure)
        for m in ms:
            items.append(("mention", m.id, mention_request(m, s, prev, cands, long_forms),
                          {"mention": m, "sentence": s, "cands": cands, "structure": structure[m.id]}))
        prev = s
    # a long form defined anywhere in the paper glosses the term in every later question
    lf = {}
    for kind, _, _, ctx in items:
        if kind == "sentence":
            for d in ctx["defs"]:
                lf.setdefault(d["term"], d["long_form"])
    for k, (kind, target, req, ctx) in enumerate(items):
        if kind == "mention":
            items[k] = (kind, target, mention_request(ctx["mention"], ctx["sentence"],
                                                      _prev_of(items, ctx["sentence"]), ctx["cands"], lf), ctx)
    return items


def _prev_of(items, s):
    prev = None
    for kind, _, _, ctx in items:
        if kind == "sentence":
            if ctx["sentence"].id == s.id:
                return prev
            prev = ctx["sentence"]
    return None


def ask_all(items, *, ask, model, workers=8, log=print):
    """One Jev call per item, in parallel. Returns {sha: (request, response, called_at)}."""
    import datetime
    from concurrent.futures import ThreadPoolExecutor
    reqs = {}
    for _, _, req, _ in items:
        reqs.setdefault(_sha({**req, "model": model}), req)
    done = {}

    def one(sha_req):
        sha, req = sha_req
        resp = ask(req["state"], req["questions"], model=model)
        return sha, req, resp, datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n, (sha, req, resp, at) in enumerate(pool.map(one, reqs.items()), 1):
            done[sha] = (req, resp, at)
            if n % 50 == 0 or n == len(reqs):
                log(f"  jev: {n}/{len(reqs)} calls")
    return done


def decide(items, responses, model):
    """Turn the judge's answers into clause rows, with the door's flags."""
    import json
    sent_rows, alias_rows, measure_rows = [], [], []
    for kind, target, req, ctx in items:
        ans = responses[_sha({**req, "model": model})][1]["answers"]
        if kind == "sentence":
            s = ctx["sentence"]
            mod, pol = decision(ans["modality"]), decision(ans["polarity"])
            hedges, negs, flags = sentence_flags(s, mod["label"], pol["label"])
            sent_rows.append({"id": s.id, "page": s.page, "kind": s.kind, "text": s.text,
                              "atoms": [a for a, _ in s.atoms],
                              "modality": mod["label"], "modality_p": mod["p"], "modality_margin": mod["margin"],
                              "polarity": pol["label"], "polarity_p": pol["p"], "polarity_margin": pol["margin"],
                              "hedges": hedges, "negations": negs, "flags": flags})
            for k, d in enumerate(ctx["defs"]):
                v = decision(ans[f"d{k}"])
                alias_rows.append({**d, "verdict": v["label"], "p": v["p"], "margin": v["margin"]})
            continue
        m, s, cands, structure = ctx["mention"], ctx["sentence"], ctx["cands"], ctx["structure"]
        role, prop = decision(ans["role"]), decision(ans["property"])
        rel = {t: decision(ans[f"t{k}"]) for k, (t, _) in enumerate(cands)}
        q = decision(ans["quantity"]) if "quantity" in ans else None
        labels = {t: d["label"] for t, d in rel.items()}
        notes = []
        for t, (kind, _) in structure.items():
            if kind == "unit":
                labels[t] = "unit"
        by_layout = [t for t, (kind, _) in structure.items() if kind == "quantity"]
        if by_layout:
            # The layout decides; the judge's answers on those words are kept as a second reading.
            quantity = by_layout
            for t in by_layout:
                if labels.get(t) in ("about", "measured by"):
                    notes.append(f"“{t}” is the quantity by layout; the judge read it as {labels[t]}")
                labels[t] = "quantity"
        else:
            choice = q["label"] if q and q["label"] != NO_QUANTITY else None
            quantity = [choice] if choice else []
            # Two judgments that disagree are not reconciled by preferring one. The per-term question can
            # say "unrelated"; the quantity question is one forced choice. So the per-term answer stands,
            # and a quantity choice naming a term it judged "about" or "measured by" is withheld.
            if choice and labels.get(choice) in ("about", "measured by"):
                notes.append(f"quantity choice “{choice}” withheld: the same words are judged {labels[choice]}")
                quantity = []
            elif choice:
                labels[choice] = "quantity"
        measure_rows.append({
            "id": m.id, "sentence": s.id, "atoms": m.atoms, "text": s.text[m.start:m.end], "value": m.value,
            "unit": m.unit, "key": m.key, "lo": m.lo, "hi": m.hi, "note": m.note,
            "role": role["label"], "role_p": role["p"], "role_margin": role["margin"],
            "property": prop["label"], "property_p": prop["p"], "property_margin": prop["margin"],
            "about": [t for t, l in labels.items() if l == "about"],
            "measured_by": [t for t, l in labels.items() if l == "measured by"],
            "quantity": quantity,
            "quantity_p": None if by_layout or not q else q["p"],
            "quantity_margin": None if by_layout or not q else q["margin"],
            "relations": json.dumps({t: {**d, "where": dict(cands)[t]} for t, d in rel.items()}, ensure_ascii=False),
            "structure": json.dumps({t: {"role": r, "why": w} for t, (r, w) in structure.items()}, ensure_ascii=False),
            "flags": measure_flags(role["label"], labels, structure, cands) + notes})
    # consistency: one subject, method and quantity reported with two different values
    groups = defaultdict(list)
    for r in measure_rows:
        if r["role"] == "result" and r["about"]:
            groups[(tuple(sorted(r["about"])), tuple(sorted(r["measured_by"])), tuple(sorted(r["quantity"])),
                    r["property"], r["unit"])].append(r)
    for rows in groups.values():
        if len({(r["lo"], r["hi"], r["value"]) for r in rows}) > 1:
            for r in rows:
                others = [o["id"] for o in rows if o is not r and o["value"] != r["value"]]
                if others:
                    r["flags"] = r["flags"] + [f"same subject, method and quantity as {', '.join(others)} "
                                               f"with a different value"]
    return sent_rows, alias_rows, measure_rows


def _write(out, root, items, responses, model, log):
    import datetime
    import json
    from pathlib import Path

    import duckdb

    from ugrc import store
    out = Path(out)
    if (out / CLAUSE_DB).exists():
        raise SystemExit(f"{out / CLAUSE_DB} exists: a clause base is built once; use a new --out")
    con = store.connect_readonly(root)
    seals = dict(con.execute("SELECT name, sha256 FROM seals").fetchall())
    con.close()
    sent_rows, alias_rows, measure_rows = decide(items, responses, model)
    out.mkdir(parents=True, exist_ok=True)
    db = duckdb.connect(str(out / CLAUSE_DB))
    try:
        db.execute(CLAUSE_SCHEMA)
        kinds = {_sha({**r, "model": model}): (k, t) for k, t, r, _ in items}
        store._insert(db, "jev_calls", [
            {"sha": sha, "kind": kinds[sha][0], "target": kinds[sha][1],
             "request": json.dumps(req, ensure_ascii=False), "response": json.dumps(resp, ensure_ascii=False),
             "model": resp.get("model"), "called_at": at} for sha, (req, resp, at) in responses.items()])
        store._insert(db, "sentences", sent_rows)
        store._insert(db, "aliases", alias_rows)
        store._insert(db, "measures", measure_rows)
        usage = [r[1].get("usage", {}) for r in responses.values()]
        meta = {"clause_version": CLAUSE_VERSION, "requested_model": model,
                "served_models": ",".join(sorted({r[1].get("model", "?") for r in responses.values()})),
                "substrate": str(Path(root).resolve()), "substrate_seals": json.dumps(seals, sort_keys=True),
                "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "calls": str(len(responses)),
                "input_tokens": str(sum(u.get("input_tokens", 0) for u in usage)),
                "output_tokens": str(sum(u.get("output_tokens", 0) for u in usage))}
        db.executemany("INSERT INTO clause_meta VALUES (?, ?)", list(meta.items()))
        db.execute("INSERT INTO seals VALUES (?, ?, ?)",
                   ["clauses", store.rows_sha(db, CLAUSE_COVERS), ",".join(CLAUSE_COVERS)])
    finally:
        db.close()
    log(f"clauses: {len(sent_rows)} sentences, {len(measure_rows)} measures, {len(alias_rows)} aliases "
        f"-> {out / CLAUSE_DB}  ({meta['calls']} calls, {meta['input_tokens']} in / {meta['output_tokens']} out tokens)")
    return out / CLAUSE_DB


def _plan_of(root, log):
    from ugrc import store
    con = store.connect_readonly(root)
    try:
        items = plan(con)
    finally:
        con.close()
    log(f"plan: {sum(k == 'sentence' for k, *_ in items)} sentences, {sum(k == 'mention' for k, *_ in items)} "
        f"mentions, {sum(len(r['questions']) for _, _, r, _ in items)} questions")
    return items


def pinned(clause_dir) -> tuple[dict, str]:
    """The judgments a clause base pinned: ({sha: (request, response, called_at)}, requested model)."""
    import json
    from pathlib import Path

    import duckdb
    db = duckdb.connect(str(Path(clause_dir) / CLAUSE_DB), read_only=True)
    try:
        calls = {sha: (json.loads(req), json.loads(resp), at) for sha, req, resp, at in
                 db.execute("SELECT sha, request, response, called_at FROM jev_calls").fetchall()}
        model = db.execute("SELECT value FROM clause_meta WHERE key = 'requested_model'").fetchone()[0]
    finally:
        db.close()
    return calls, model


def _missing(items, responses, model) -> list[str]:
    return [target for _, target, req, _ in items if _sha({**req, "model": model}) not in responses]


def build(root, out, *, ask=None, model=None, workers=8, log=print):
    """Plan, ask Jev, decide, and write <out>/clauses.duckdb (sealed). Never touches the substrate."""
    from ugrc import jev
    ask = ask or jev.ask
    model = model or jev.MODEL
    items = _plan_of(root, log)
    responses = ask_all(items, ask=ask, model=model, workers=workers, log=log)
    return _write(out, root, items, responses, model, log)


def replay(root, source, out, *, log=print):
    """Rebuild a clause base from another one's pinned judgments: zero calls. Refuses if the plan asks
    anything the source never asked (the substrate or the questions moved)."""
    items = _plan_of(root, log)
    responses, model = pinned(source)
    missing = _missing(items, responses, model)
    if missing:
        raise SystemExit(f"{len(missing)} planned question set(s) were never asked in {source}: {missing[:5]}")
    used = {_sha({**r, "model": model}) for _, _, r, _ in items}
    return _write(out, root, items, {k: v for k, v in responses.items() if k in used}, model, log)


def recheck(root, clause_dir, *, rerun=False, ask=None, workers=8, log=print) -> list[tuple[bool, str]]:
    """The clause receipt. Zero model by default:
      - the clause base's seal covers its rows;
      - it was built on this substrate (same seals);
      - re-planning from the substrate asks exactly the pinned questions;
      - re-deciding from the pinned answers reproduces every stored row (the door is a function).
    With rerun=True, every pinned question is asked again and each decision is compared by label."""
    import json
    from pathlib import Path

    import duckdb

    from ugrc import jev, store
    out = []
    path = Path(clause_dir) / CLAUSE_DB
    db = duckdb.connect(str(path), read_only=True)
    try:
        sealed = db.execute("SELECT sha256 FROM seals WHERE name = 'clauses'").fetchone()[0]
        out.append((sealed == store.rows_sha(db, CLAUSE_COVERS), "clause seal covers its rows"))
        meta = dict(db.execute("SELECT key, value FROM clause_meta").fetchall())
        stored = {t: db.execute(f'SELECT * FROM "{t}" ORDER BY ALL').fetchall()
                  for t in ("sentences", "aliases", "measures")}
    finally:
        db.close()
    if meta.get("clause_version") != CLAUSE_VERSION:
        out.append((False, f"built by clause door v{meta.get('clause_version')}, this is v{CLAUSE_VERSION}: "
                           f"replay it into a new directory to re-decide"))
        return out
    con = store.connect_readonly(root)
    seals = dict(con.execute("SELECT name, sha256 FROM seals").fetchall())
    con.close()
    out.append((json.loads(meta["substrate_seals"]) == seals, "built on this substrate (seals equal)"))
    items = _plan_of(root, lambda *_: None)
    responses, model = pinned(clause_dir)
    missing = _missing(items, responses, model)
    out.append((not missing, f"the plan asks exactly the pinned questions ({len(items)} sets"
                             + (f"; {len(missing)} never asked: {missing[:3]}" if missing else "") + ")"))
    if missing:
        return out
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, root, items, responses, model, lambda *_: None)
        db = duckdb.connect(str(Path(tmp) / CLAUSE_DB), read_only=True)
        again = {t: db.execute(f'SELECT * FROM "{t}" ORDER BY ALL').fetchall() for t in stored}
        db.close()
    for t in stored:
        out.append((again[t] == stored[t], f"re-deciding from the pinned answers reproduces {t} ({len(stored[t])} rows)"))
    if rerun:
        ask = ask or jev.ask
        fresh = ask_all(items, ask=ask, model=model, workers=workers, log=log)
        same = differ = 0
        for sha, (_, resp, _) in responses.items():
            for q, a in resp["answers"].items():
                b = fresh[sha][1]["answers"].get(q, {})
                if a.get("choice") == b.get("choice"):
                    same += 1
                else:
                    differ += 1
                    out.append((False, f"re-asked: {q} of {sha[:10]} chose {b.get('choice')!r}, pinned "
                                       f"{a.get('choice')!r} (pinned margin {decision(a)['margin']})"))
        out.append((differ == 0, f"re-asked every pinned question: {same} decisions identical, {differ} differ"))
    return out
