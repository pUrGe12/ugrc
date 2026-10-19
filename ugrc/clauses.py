"""Clauses: the paper's values bound to what they are about, decided by a judge that can only choose.

Nothing in a clause is written. Every argument is a span the deterministic reader found in the text:

  sentences  the body, abstract and captions cut into sentences; offsets map back to line atoms
  mentions   every quantity in a sentence: its text, interval and unit, parsed, not judged
  terms      every named thing: species, abbreviations, strain and part codes, materials, methods
  phrases    the nominals beside them ("the above solution", "these bacteria", "fed-batch fermentation")
  aliases    the paper's own definitions, "long form (ABBR)", matched letter by letter

The layout decides what it can, and the unit decides the kind of property it can. What is left, a
non-generative judge (Jev, `ugrc/jev.py`, or any model behind the same API) decides by choosing.

HOW THE JUDGE IS ASKED. Every question is built so that a small, weak model can answer it, not only a
strong one: the clause base should outlive any one judge.
  1. One decision per question, with at most MAX_OPTIONS spans to choose from.
  2. Options are typed. The kind of every named term (organism, substance, biological part, method,
     measure) is asked once per paper; a question about which organism offers only organisms.
  3. Every question whose answer may be absent offers "none of these".
  4. The state is the one sentence, with the value marked once; the question repeats the value.
  5. What the layout already says is never asked: "65 mM [NaCl]", "320 μL of [the above solution]",
     "an [LOD] of 0.0034", "9.2 × 10^7 CFU/mL ([P. aeruginosa])", "4 [signals]", "X, Y and Z ...
     respectively", a unit that fixes the property (°C is a temperature).
  6. Every binding the judge chose is asked again as a yes/no about that one span, and kept only when
     both forms agree; a disagreement is withheld and flagged, never resolved by preferring one.

Three rounds, each planned from the answers before it: (1) the kind of every term, and each sentence's
modality and polarity; (2) per value: amount or label, origin, property, who, what, method, quantity;
(3) the yes/no confirmations. Every request and answer is pinned, so a replay re-derives every row.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from ugrc.answer import NUMBER_WORDS, _join

CLAUSE_VERSION = "8"     # v2: the quantity is one choice among the candidates, not a per-term relation
                         # v3: a quantity choice that names a term judged "about" or "measured by" is withheld
                         # v4: the layout decides the quantity where it can ("X of VALUE", "KEY =VALUE", a
                         #     coordinated list shares it); the judge is asked only for the rest
                         # v5: a term printed inside the value's own text is its unit ("CFU" in "9.2 × 10^7 CFU/mL")
                         # v6: questions a weak judge can answer: typed slots chosen competitively with "none",
                         #     term kinds asked once, unit-narrowed properties, more layout, yes/no confirmation;
                         #     candidates add strain codes and nominal phrases; units read "L^(cid:0) 1"
                         # v7: an organism is asked for as what a value is reported for, not as what the value
                         #     is "the concentration of": a titer is of the product, made by the strain; "using"
                         #     is a verb
                         # v8: battery papers: the reference list ends the prose however it is headed; battery
                         #     and energy units, spaced and positive exponents, scale words ("11 million metric
                         #     tons"), hyphen ranges ("10-15 min"); a label stays inside its name ("NFA 811")


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


# The reference list ends the prose: a heading spelling "References" whatever its glyphs ("■ REFERENCES"),
# or, where none is printed, the list's first entry written as a citation ("[1] A. Manthiram",
# "[1] a) D. Song", "(1) Li, H.;") in the paper's second half.
_REF_HEADING = re.compile(r"^(?:references|referencesandnotes|notesandreferences|literaturecited|bibliography)$")
_REF_FIRST = re.compile(r"^\s*(?:\[1\]|\(1\))\s+(?:[a-z]\)\s+)?[A-Z][A-Za-z'’\-]*[.,]")


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

    half = max((r[1] for r in rows), default=0) / 2
    for aid, page, _, text, size, _ in rows:
        if _REF_HEADING.match(re.sub(r"[^a-z]", "", text.lower())) or (page > half and _REF_FIRST.match(text)):
            break                                # the reference list, headed or not
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
# Chemical locants are part of a name, not quantities: the 2 of "2,3-butanediol", "1,8-cineole",
# "2,2′-bipyrrole", the 3 of "3′ UTRs". A thousands separator has three digits, so "1,000-fold" stays.
_LOCANT = re.compile(r"(?<![\w.,])\d{1,2}(?:,\d{1,2})+[′']?[-–](?=[\w(α-ω])|(?<![\w.])\d+[′'](?!\d)")
_SCI = r"\d+(?:,\d{3})*(?:\.\d+)?(?:\s?[×x]\s?10\^\s?[−-]?\s?\d+)?|10\^\s?[−-]?\s?\d+"
_RATIO = r"\d+(?::\d+)+"
QUANTITY = re.compile(rf"(?P<cmp>[<>≤≥~≈]\s?)?(?P<sign>[−-])?(?P<a>{_RATIO}|{_SCI})"
                      rf"(?:(?P<sep>\s?(?:±|–)\s?|-(?=\d)|\s+to\s+)(?P<b>{_SCI}))?")
# General laboratory units, longest first; a unit must end at a word boundary.
_UNITS = sorted("""°C ° ◦C ◦ K % ‰ nm μm µm mm cm km m Å mL μL µL nL L mg μg µg ng kg g mM μM µM nM pM M mmol μmol
µmol mol h min s ms days day hours hour weeks week months month years year rpm ×g Hz kHz MHz mV V eV mW W kW MW kJ J
kPa MPa Pa bar atm kDa Da CFU wt% wt.% vol% at.% mol% ppm ppb U fold times cycles bp kb kbp Mb nt mAh Ah μAh mA μA A
Wh kWh MWh GWh mWh ¢ miles mile mi tons tonnes Mt kt S mS""".split() + ["metric tons"], key=len, reverse=True)
_UNIT = "|".join(re.escape(u) for u in _UNITS)
# An exponent after a unit: "mL^-1", "g^− 1" (spaced), "cm^2", or "L^(cid:0) 1" where the font left the minus
# sign unmapped. The first unit may carry one too ("871 cm^−1").
_EXP = r"(?:\^\s?[−-]?\s?\d+|\^\(cid:\d+\)\s?\d|[−-]\d)"
UNIT = re.compile(rf"\s?(?:-(?=fold))?(?P<u>(?:{_UNIT})(?:{_EXP})?(?:\s?/\s?(?:{_UNIT})(?:{_EXP})?|\s(?:{_UNIT}){_EXP})*)"
                  rf"(?![\w@])")
# a scale word between a number and its unit is part of the value: "11 million metric tons"
_SCALE = re.compile(r"\s(thousand|million|billion|trillion)\b")
_SCALE_FACTOR = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
_LEFT_OK = set(" ([{=,;:'\"“‘×+\n")
_KEY_BEFORE = re.compile(r"(?P<key>[A-Za-z][\w^]*)\s?=\s?$|(?P<ph>\bpH)\s?$")
# An unmapped glyph right before a number may be its minus sign ("(cid:0) 0.0151" is -0.0151).
_UNMAPPED_BEFORE = re.compile(r"\(cid:\d+\)\s?$")
# What lies between two items of one coordinated list: ", ", " and ", ", and ", " or ".
_LIST_GAP = re.compile(r"^(?:\s*,\s*(?:and\s+|or\s+)?|\s+(?:and|or)\s+)$")


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


def masked(text: str, extra=()) -> list[bool]:
    mask = [False] * len(text)
    for rx in list(_MASKS) + list(extra):
        for m in rx.finditer(text):
            mask[m.start():m.end()] = [True] * (m.end() - m.start())
    return mask


def _add_note(m: Mention, note: str):
    m.note = f"{m.note}; {note}" if m.note else note


def mentions(s: Sentence) -> list[Mention]:
    text, mask = s.text, masked(s.text, [_LOCANT])
    if s.kind == "heading":
        n = _HEADING_NUMBER.match(text)
        if n:
            mask[:n.end()] = [True] * n.end()
    out, covered = [], 0
    for m in QUANTITY.finditer(text):
        i, j = m.start(), m.end()
        if i < covered or any(mask[i:j]):
            continue                             # inside the last value's unit ("L^(cid:0) 1"), or masked
        if i > 0 and text[i - 1] not in _LEFT_OK:
            continue                             # glued to a word on the left: "OD600", "S17", "2025ZDSYS"
        scale = _SCALE.match(text, j)
        factor = 1.0
        if scale:
            factor, j = _SCALE_FACTOR[scale.group(1)], scale.end()
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
        lo, hi = (None if lo is None else lo * factor), (None if hi is None else hi * factor)
        note = None
        if _UNMAPPED_BEFORE.search(text[:i]):
            lo = hi = None
            note = "an unmapped glyph precedes the number: its sign is unknown"
        out.append(Mention(id=f"{s.id}#{i}", sentence=s.id, start=i, end=j2, value=text[i:m.end()].strip(),
                           unit=unit, key=(k.group("key") or k.group("ph")) if k else None, lo=lo, hi=hi,
                           atoms=s.atoms_at(i, j2), note=note))
        covered = j2
    # "70.50, 60.32, and 102.3 g L^-1": a unit printed once after a list belongs to every number in it. A
    # list ends in "and" or "or" before its last item; a bare comma ("By 2030, 11 million tons") is not one.
    listed = set()
    for a, b in reversed(list(zip(out, out[1:]))):
        gap = text[a.end:b.start]
        closes = re.search(r"\b(?:and|or)\b", gap) is not None
        if (a.unit is None and b.unit and a.key is None and ":" not in a.value and _LIST_GAP.match(gap)
                and (closes or id(b) in listed)):
            a.unit = b.unit
            listed.add(id(a))
            _add_note(a, "unit printed once after the list")
    return out


# ─────────────────────────── terms, phrases and aliases ───────────────────────────

_SPECIES = re.compile(r"\b([A-Z])\.\s?([a-z]{3,})\b")
_TOKEN = re.compile(r"[A-Za-z0-9@\-–/+α-ωµ′]+(?:,\d+[A-Za-z0-9@\-–/+α-ωµ′]*)*")
# A strain or part code: one capital, a few letters, then digits ("R82", "H32", "P6", "MG1", "SK4–72").
_CODE = re.compile(r"[A-Z][A-Za-z]{0,4}\d[\w–\-]*")


def _is_term(tok: str, known=()) -> bool:
    if tok in known:
        return True
    return any(c.isalpha() for c in tok) and (sum(c.isupper() for c in tok) >= 2 or "@" in tok
                                              or bool(_CODE.fullmatch(tok)))


def terms(text: str, genus_of: dict | None = None, known=()) -> list[tuple[str, int]]:
    """Named things in `text`, in order of first appearance: (surface, offset). `genus_of` maps a
    species epithet to the genus names the paper spells out for it ("aeruginosa" -> {"Pseudomonas"});
    `known` holds the abbreviations the paper defines anywhere, which are names however they are spelled."""
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
        if all(_is_term(p, known) for p in parts):
            add(tok, start)
        if len(parts) > 1:
            off = start
            for p in parts:
                if _is_term(p, known):
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


# Closed-class English words: a phrase stops at one of these.
DETERMINERS = frozenset("a an the each every its their this these those our such both all any some".split())
FUNCTION_WORDS = DETERMINERS | frozenset("""of in at on for with to from by into onto over under between across
among through during after before upon via and or but nor while whereas which that where when as than versus vs
was were is are be been being has have had do does did will would can could may might should must it they we
them us respectively et al also only further then thus however here there not no furthermore moreover
therefore hence additionally notably similarly conversely accordingly finally about approximately around nearly
up down within without until once since per toward towards along against beyond despite throughout if
so because even either whether how what who whose whom more less most least""".split())
# Signs between words that end a phrase as punctuation does: "4 signals × 7 bacteria".
_SIGNS = frozenset("× ± ~ ≈ < > ≤ ≥ = + / – - — →".split())
# Verbs a scientific paper writes in the present tense; past tenses and participles are caught by
# their ending. Words that are also nouns ("yields", "results") are left out on purpose.
VERBS = frozenset("""survives grows tolerates maintains reaches shows displays exhibits presents achieves produces
increases decreases reduces remains contains reveals indicates demonstrates enables requires provides allows
leads uses comprises depends suggests harbors exceeds outperforms improves inhibits promotes induces binds forms
becomes accounts differs using contain survive grow tolerate display exhibit achieve produce reduce remain reveal
indicate demonstrate enable require provide allow comprise depend suggest harbor exceed outperform improve inhibit
promote induce bind become differ reach act cause affect manifest remove""".split())
_NOUN_ING = frozenset("loading binding screening sequencing staining imaging monitoring signaling coating "
                      "labeling engineering processing spacing".split())
PHRASE_MAX_WORDS = 4
# A word: a run of non-separators, which may hold short parenthesised groups and locant commas
# ("(E)-nerolidol", "(2R,3R)-2,3-BD", "((cid:0) )-α-bisabolol").
_PWORD = re.compile(r"(?:\((?:[^\s()]|\(cid:\d+\)\s?){1,12}\)|\(cid:\d+\)|\d,(?=\d)|[^\s,;:()\[\]{}\"“”])+")


def _verb_like(w: str) -> bool:
    low = w.lower()
    if low in VERBS:
        return True
    low = re.sub(r"[-–]", "", low)               # "con-structed" broken at a line end, "CTAB-stabilized"
    if not low.isalpha():
        return False                             # a name with digits or signs ("4-MPBA-derived")
    return ((low.endswith("ed") and len(low) > 4) or (low.endswith("ing") and len(low) > 5 and low not in _NOUN_ING)
            or (low.endswith("ly") and len(low) > 4))


def noun_phrases(text: str, values=()) -> list[tuple[str, int]]:
    """Runs of content words, the nominals a value may be about: "the above solution" -> "above
    solution", "a 1.5 mL tube" -> "tube", "these bacteria" -> "bacteria". A run ends at punctuation, a
    closed-class word, a value (`values`: their (start, end)), a verb-like word or an adverb; leading
    determiners and number words are dropped, and at most PHRASE_MAX_WORDS words are kept, from the end,
    where an English noun phrase keeps its head. Each phrase is a verbatim span: (text, offset)."""
    mask = [False] * len(text)
    for rx in _MASKS[:3]:                        # references, citations, links; not glyphs inside names
        for r in rx.finditer(text):
            mask[r.start():r.end()] = [True] * (r.end() - r.start())
    for i, j in values:
        mask[i:j] = [True] * (j - i)
    out, seen, cur, prev_end = [], set(), [], None

    def flush():
        nonlocal cur
        while cur and (cur[0][0].lower() in DETERMINERS or cur[0][0].lower() in NUMBER_WORDS):
            cur.pop(0)
        cur = cur[-PHRASE_MAX_WORDS:]
        if cur:
            i, j = cur[0][1], cur[-1][2]
            p = text[i:j]
            bare = re.sub(r"\(cid:\d+\)", "", p)
            if (sum(c.isalpha() for c in bare) > 1 and p not in seen and p not in _UNITS
                    and not re.match(r"\s*et\s+al\b", text[j:])):
                seen.add(p)
                out.append((p, i))
        cur = []

    for m in _PWORD.finditer(text):
        w, i, j = m.group(), m.start(), m.end()
        if prev_end is not None and text[prev_end:i].strip():
            flush()                              # punctuation between two words ends a phrase
        core = w.rstrip(".")
        if re.fullmatch(r"[A-Z]\.", w) or core in ABBREVIATIONS:
            core = w                             # a genus initial ("S. marcescens") keeps its point
        low = core.lower()
        if (not core or any(mask[i:j]) or (low in FUNCTION_WORDS and low not in DETERMINERS) or _verb_like(core)
                or core in _SIGNS or core[:1] in "+×±~≈<>≤≥=" or (core.rstrip(".") in ABBREVIATIONS and not re.fullmatch(r"[A-Z]\.", core))):
            flush()
        elif low in DETERMINERS:
            flush()                              # a determiner opens a new phrase (and is dropped from it)
            cur.append((core, i, i + len(core)))
        else:
            cur.append((core, i, i + len(core)))
        if core != w:
            flush()                              # a full stop ends it too
        prev_end = j
    flush()
    return out


# ─────────────────────────── what kind of thing a span names ───────────────────────────

KIND = {
    "organism": "a species, strain, cell line or other living thing, or a sample of one",
    "material or thing": "a chemical, material, product, solution, particle, gene, enzyme, container or process step",
    "method": "a technique, instrument, assay, spectrum or analysis used to measure or study something",
    "measure": "a property or quantity that takes values, such as a length, concentration, limit, intensity or peak",
    "other": "a person, place, institution, date, unit, quality or anything else",
}
THING = "material or thing"
# The head noun of a phrase settles its kind where a closed list can: these are words, not judgments.
ORGANISM_HEADS = frozenset("""strain strains bacteria bacterium cells cell isolates isolate species mice mouse rats
rat patients patient colonies colony organisms organism microorganisms microbes host hosts mutant mutants wild-type
chassis tumors tumor""".split())
MEASURE_HEADS = frozenset("""length lengths size sizes diameter diameters width thickness height depth area volume
volumes mass weight concentration concentrations titer titers titre titres yield yields productivity ratio ratios
proportion fraction percentage share variance accuracy efficiency efficiencies rate rates intensity intensities
signal signals absorbance absorption emission limit limits range ranges temperature temperatures time times duration
speed density densities purity conversion content contents level levels value values amount amounts dose doses
activity potential charge frequency increase decrease change difference reduction inhibition survival sensitivity
specificity score number numbers resolution optimum maximum minimum ph peak peaks gradient gradients capacity
capacities voltage voltages current currents energy energies power retention loading loadings hysteresis conductivity
conductivities diffusivity diffusivities resistance impedance strain strains stress modulus porosity selectivity
permeability flux pressure pressures viscosity""".split())
METHOD_HEADS = frozenset("""analysis analyses spectroscopy spectrometry spectrum spectra method methods assay assays
microscopy test tests measurement measurements technique techniques imaging staining sequencing chromatography
electrophoresis cytometry calorimetry diffraction titration counting monitoring""".split())


def head_word(phrase: str) -> str:
    """The head of a nominal: its last word, or the last word before "of" ("limit of detection")."""
    words = phrase.split()
    lows = [w.lower() for w in words]
    if "of" in lows[1:]:
        words = words[:lows.index("of")]
    return re.sub(r"[-–]", "", words[-1].lower().strip(".,;:()[]")) if words else ""


def lexicon_kind(phrase: str) -> str | None:
    h = head_word(phrase)
    if h in ORGANISM_HEADS:
        return "organism"
    if h in MEASURE_HEADS:
        return "measure"
    if h in METHOD_HEADS:
        return "method"
    return None


def term_kind_by_rule(term: str, long_form: str | None) -> str | None:
    """A term's kind when a rule settles it: a species name is an organism; a definition's head noun
    ("limit of detection" -> limit) settles the rest it can. None leaves it to the judge."""
    if _SPECIES.fullmatch(term) or re.fullmatch(r"[A-Z][a-z]{3,}\s[a-z]{3,}", term):
        return "organism"
    return lexicon_kind(long_form) if long_form else None


# ─────────────────────────── candidates and slots ───────────────────────────

MAX_OPTIONS = 6               # spans offered in one question, nearest to the value first
NONE = "none of these"
# Which kinds of span may fill each slot of a clause.
SLOTS = {"who": ("organism",), "what": (THING,),
         "method": ("method",), "quantity": ("measure",)}
# A clause boundary that a value's subject seldom crosses: "A had x versus y, while B had z versus w".
_CLAUSE_BREAK = re.compile(r";\s+|,\s+(?:while|whereas|but)\s+|\s+(?:while|whereas)\s+")


@dataclass
class Cand:
    text: str
    start: int
    kind: str                 # organism | material or thing | method | measure
    gloss: str | None = None  # the paper's long form, when it defines the term

    @property
    def end(self) -> int:
        return self.start + len(self.text)


def sentence_candidates(s: Sentence, ms, kinds: dict, genus: dict, known, long_forms: dict) -> list[Cand]:
    """Every named term and nominal phrase of the sentence that has a slot kind, in text order."""
    out = {}
    for t, i in terms(s.text, genus, known):
        k = kinds.get(t)
        if k in ("organism", THING, "method", "measure"):
            out[t] = Cand(t, i, k, long_forms.get(t))
    for p, i in noun_phrases(s.text, _value_spans(s.text, ms)):
        k = kinds.get((s.id, p)) or lexicon_kind(p)
        if p not in out and k in ("organism", THING, "method", "measure"):
            out[p] = Cand(p, i, k)
    return sorted(out.values(), key=lambda c: c.start)


def _value_spans(text: str, ms) -> list[tuple[int, int]]:
    """The spans a phrase may not run through: every value except a label, which stays inside its name
    ("NFA 811", "MTCC 4822")."""
    return [(m.start, m.end) for m in ms if not _label_before(text, m)]


def _window(text: str, i: int) -> tuple[int, int]:
    cuts = [0] + [m.end() for m in _CLAUSE_BREAK.finditer(text)] + [len(text)]
    return next(((a, b) for a, b in zip(cuts, cuts[1:]) if a <= i < b), (0, len(text)))


def groups(text: str, pool: list[Cand]) -> list[list[Cand]]:
    """Coordinated lists among the candidates: "P. aeruginosa, E. coli and S. aureus"."""
    out, run = [], pool[:1]
    for a, b in zip(pool, pool[1:]):
        if b.start >= a.end and _LIST_GAP.match(text[a.end:b.start]):
            run.append(b)
        else:
            if len(run) > 1:
                out.append(run)
            run = [b]
    if len(run) > 1:
        out.append(run)
    return out


def slot_options(slot: str, m: Mention, text: str, cands: list[Cand]) -> list:
    """The spans a slot of this value is chosen from: candidates of the slot's kinds, from the value's
    own clause when it has any, the MAX_OPTIONS nearest, in text order; then the coordinated lists
    they belong to, as one option each."""
    pool = [c for c in cands if c.kind in SLOTS[slot] and not (c.start < m.end and m.start < c.end)]
    a, b = _window(text, m.start)
    near = [c for c in pool if a <= c.start < b] or pool
    near = sorted(sorted(near, key=lambda c: abs(c.start - m.start))[:MAX_OPTIONS], key=lambda c: c.start)
    opts = list(near)
    for g in groups(text, pool):
        if any(c in near for c in g):
            opts.append(tuple(g))
    return opts


def option_label(o) -> str:
    return "all of: " + ", ".join(c.text for c in o) if isinstance(o, tuple) else o.text


def option_members(o) -> list[str]:
    return [c.text for c in o] if isinstance(o, tuple) else [o.text]


# ─────────────────────────── the layout decides what it can ───────────────────────────

_OF_BEFORE = re.compile(r"(?:^|\s)of\s+(?:[A-Za-z][\w^]*\s?=\s?)?$")
_UNIT_CLASSES = {
    "temperature": {"°C", "◦C", "K", "°", "◦"},
    "duration": {"h", "min", "s", "ms", "days", "day", "d", "hours", "hour", "weeks", "week", "months", "month",
                 "years", "year"},
    "speed": {"rpm", "×g"},
    "concentration": {"mM", "μM", "µM", "nM", "pM", "M", "ppm", "ppb", "wt%"},
    "amount": {"mL", "μL", "µL", "nL", "L", "mg", "μg", "µg", "ng", "kg", "g", "mmol", "μmol", "µmol", "mol", "U"},
    "length": {"nm", "μm", "µm", "mm", "cm", "km", "m", "Å"},
    "sequence": {"bp", "kb", "kbp", "Mb", "nt"},
    "fold": {"fold", "times"},
    "percent": {"%", "‰"},
    "count": {"cycles"},
}
_DETECTION = re.compile(r"\bLOD\b|limit of detection|detection limit|\bLOQ\b", re.I)
_ACCURACY = re.compile(r"accura", re.I)


def unit_class(unit: str | None) -> str | None:
    if not unit:
        return None
    if "/" in unit or "^" in unit:
        num = re.split(r"\s?/\s?|\s", unit)[0]
        if num in _UNIT_CLASSES["amount"] | _UNIT_CLASSES["concentration"] or num == "CFU":
            return "per"
        return "compound"
    return next((k for k, units in _UNIT_CLASSES.items() if unit in units), "other")


def property_options(m: Mention, quantity_words: list[str]) -> list[str]:
    """The property kinds this value can be, given its unit and the words the layout names as its
    quantity. One option means the property is decided and not asked."""
    words = " ".join(quantity_words + ([m.key] if m.key else []))
    if m.key == "pH":
        return ["acidity"]
    if _DETECTION.search(words):
        return ["detection limit"]
    if ":" in m.value:
        return ["ratio"]
    uc = unit_class(m.unit)
    fixed = {"temperature": ["temperature"], "duration": ["duration"], "speed": ["speed"],
             "concentration": ["concentration"], "per": ["concentration"], "amount": ["amount"],
             "sequence": ["size"], "fold": ["ratio"], "count": ["count"],
             "length": ["size", "wavelength"], "compound": ["concentration", "ratio", "other"],
             "other": ["signal", "size", "other"]}
    if uc == "percent":
        return ["accuracy"] if _ACCURACY.search(words) else ["share", "accuracy", "concentration", "ratio", "other"]
    if uc:
        return fixed[uc]
    if re.fullmatch(r"\d+", m.value):
        return ["count", "ratio", "signal", "other"]
    return ["concentration", "signal", "ratio", "share", "detection limit", "other"]


def _phrase_backward(text: str, j: int) -> str | None:
    words = []
    for t in reversed(list(re.finditer(r"[^\s()\[\]×]+", text[:j]))):
        w = t.group()
        if text[t.end():j].strip() or w[-1:] in ",;:." or w.lower() in FUNCTION_WORDS:
            break                                # a bracket, a punctuation mark or a closed-class word
        words.insert(0, w)
        j = t.start()
    return " ".join(words) or None


def _phrase_at(text: str, phrases: list[tuple[str, int]], i: int) -> str | None:
    """The phrase that starts at offset i, past only the determiners and number words it dropped."""
    for p, at in phrases:
        if at >= i:
            gap = text[i:at].split()
            return p if all(w.lower() in DETERMINERS or w.lower() in NUMBER_WORDS for w in gap) else None
    return None


def _phrase_ending(text: str, phrases: list[tuple[str, int]], j: int) -> str | None:
    """The phrase that ends at offset j (spaces aside)."""
    j = len(text[:j].rstrip())
    return next((p for p, at in phrases if at + len(p) == j), None)


def layout(m: Mention, s: Sentence, cands: list[Cand], ms: list[Mention], phrases) -> dict:
    """What the layout alone says about a value: {slot: [(span, why)]}, plus {"count": True} when the
    value counts the thing printed right after it.
      quantity  "an [LOD] of 0.0034", "[OD600] =0.02–0.2", "0.1% of the [total variance]"
      who/what  "65 mM [NaCl]", "320 μL of [the above solution]", "9.2 × 10^7 CFU/mL ([P. aeruginosa])",
                "4 [signals]", "X, Y and Z reached a, b and c, respectively"
      method    "0.0034 ([CD], Fig. S17a)"
      unit      a term printed inside the value's own text ("[CFU]" in "9.2 × 10^7 CFU/mL")"""
    text = s.text
    by = {c.text: c for c in cands}
    out = defaultdict(list)

    def put(slot_of_kind, span, why):
        kind = by[span].kind if span in by else lexicon_kind(span)
        slot = slot_of_kind or next((k for k, kinds in SLOTS.items() if kind in kinds), None)
        if slot and span not in [x for x, _ in out[slot]]:
            out[slot].append((span, why))

    for c in cands:
        if m.start <= c.start and c.end <= m.end:
            out["unit"].append((c.text, "printed inside the value"))
    before = _OF_BEFORE.search(text[:m.start])
    if before:
        q = _phrase_backward(text, before.start())
        if q and (lexicon_kind(q) == "measure" or (q in by and by[q].kind == "measure")):
            out["quantity"].append((q, "the words before “of” the value"))
    if m.key:
        out["quantity"].append((m.key, "the key of KEY =value, or the pH it is"))
    # what is printed right after the value is the most specific: "65 mM [NaCl]", "4 [signals]", "(E. coli)"
    uc = unit_class(m.unit)
    integer = m.unit is None and m.key is None and re.fullmatch(r"\d+", m.value) is not None
    rest = text[m.end:]
    after = re.match(r"\s?\(([^,;()]+)[,;)]", rest)
    if after and after.group(1).strip() in by:
        c = by[after.group(1).strip()]
        if c.kind in ("organism", THING, "method"):
            put(None, c.text, "in parentheses right after the value")
    of = re.match(r"\s+of\s+", rest)
    if of and (uc in ("amount", "concentration", "per", "percent") or integer):
        p = _phrase_at(text, phrases, m.end + of.end())
        if p:
            put(None, p, "the words after the value and “of”")
    elif (uc in ("amount", "concentration", "per") or integer) and re.match(r"\s\S", rest):
        p = _phrase_at(text, phrases, m.end + 1)
        if p and integer and not p.split()[-1][:1].islower():
            p = None                             # "12 September", "2026 Elsevier": a date or a name, not a count
        if p:
            if integer:
                slot = "who" if (by.get(p) and by[p].kind == "organism") or lexicon_kind(p) == "organism" else "what"
                out[slot].append((p, "the words the count is printed before"))
                out["count"] = True
            else:
                put(None, p, "the words printed right after the value")
    # then what the value is given after, when nothing after it named a subject
    subject = bool(out.get("who") or out.get("what"))
    opened = re.search(r"\s?\((?:pH\s?)?$", text[:m.start])
    if opened:                                   # "4-MPBA solution (10 mM ...)", "KOH solution (pH 11)"
        np_ = _phrase_ending(text, phrases, opened.start())
        kind = (by[np_].kind if np_ in by else lexicon_kind(np_)) if np_ else None
        if kind == "measure" or (kind in ("organism", THING) and not subject):
            put(None, np_, "the words the value is given in parentheses after")
    first = m                                    # "increasing NaCl from 65 mM to 95 mM"
    if re.search(r"\sto\s+$", text[:m.start]):
        first = next((o for o in reversed(ms) if o.end <= m.start and re.fullmatch(r"\s+to\s+", text[o.end:m.start])),
                     None)
    fr = re.search(r"\s?\bfrom\s+$", text[:first.start]) if first is not None else None
    if fr and not subject:
        np_ = _phrase_ending(text, phrases, fr.start())
        if np_:
            put(None, np_, "the words before “from” the value")
    for q, _ in list(out.get("quantity", [])):    # "a [4-MPBA] concentration of 165 μM": the term it is of
        for c in cands:
            if c.text != q and c.kind != "measure" and re.search(rf"(?<!\S){re.escape(c.text)}(?!\S)", q):
                put(None, c.text, "named inside the quantity the layout gives")
    return out


_LABEL_WORD = re.compile(r"(?:^|[\s(])([A-Z][A-Za-z]*)\s$")


def _label_before(text: str, m: Mention) -> str | None:
    """"Phase 1", "Cohort 2", "MTCC 4822", "June 2026", "Origin 2026": a bare integer printed right after
    a capitalised word (not a closed-class one) is part of a name or a date, not a quantity."""
    if m.unit or m.key or not re.fullmatch(r"\d+", m.value):
        return None
    w = _LABEL_WORD.search(text[:m.start])
    return w.group(1) if w and w.group(1).lower() not in FUNCTION_WORDS else None


def respectively(s: Sentence, ms: list[Mention], cands: list[Cand]) -> dict:
    """"limonene and nerolidol reaching 14.12 and 32.33 g L^-1, respectively": a list of values and a
    list of the same length, paired in order. {mention id: (span, slot)}."""
    if "respectively" not in s.text:
        return {}
    runs, run = [], ms[:1]
    for a, b in zip(ms, ms[1:]):
        if _LIST_GAP.match(s.text[a.end:b.start]):
            run.append(b)
        else:
            runs.append(run)
            run = [b]
    runs.append(run)
    word = s.text.index("respectively")
    runs = [r for r in runs if len(r) > 1 and r[-1].end <= word]
    if not runs:
        return {}
    vr = max(runs, key=lambda r: r[-1].end)                # the list of values the word closes
    subjects = [c for c in cands if c.kind in SLOTS["who"] + SLOTS["what"]]
    lists = [g for g in groups(s.text, subjects) if len(g) == len(vr)]
    if not lists:
        return {}
    g = min(lists, key=lambda g: abs(g[0].start - vr[0].start))
    return {m.id: (c.text, "who" if c.kind == "organism" else "what") for m, c in zip(vr, g)}


def share_quantity(ms: list, text: str, lay: dict) -> None:
    """Values in one coordinated list ("ratios of 1:0, 1:4, 1:8, and 0:1") share the quantity the layout
    gives any one of them, when it gives exactly one."""
    runs, run = [], ms[:1]
    for a, b in zip(ms, ms[1:]):
        if _LIST_GAP.match(text[a.end:b.start]):
            run.append(b)
        else:
            runs.append(run)
            run = [b]
    if run:
        runs.append(run)
    for run in runs:
        qs = {q for m in run for q, _ in lay[m.id].get("quantity", [])}
        if len(run) > 1 and len(qs) == 1:
            q = qs.pop()
            for m in run:
                if not lay[m.id].get("quantity"):
                    lay[m.id]["quantity"] = [(q, "shared by the list the value is in")]


# ─────────────────────────── the judge's questions ───────────────────────────

PROPERTY = {
    "detection limit": "the lowest amount or concentration that can be detected",
    "concentration": "how much of a substance or organism is in a volume (molar, mass or cell concentration, optical density)",
    "amount": "a volume, mass or quantity of material taken or added",
    "temperature": "a temperature",
    "duration": "a length of time",
    "speed": "a rotation speed or centrifugal force",
    "wavelength": "a wavelength or spectral position",
    "size": "a length, diameter or other dimension",
    "ratio": "a ratio, fold change or proportion between two things",
    "accuracy": "a rate of correct classification or identification",
    "share": "a percentage or fraction of a total (variance explained, yield, efficiency)",
    "acidity": "a pH",
    "signal": "a measured signal or optical quantity (absorbance, dissymmetry factor, intensity)",
    "count": "how many items, samples, replicates, groups or kinds there are",
    "other": "none of these",
}
PROPERTY_NOUN = {"detection limit": "detection limit", "concentration": "concentration", "amount": "amount",
                 "temperature": "temperature", "duration": "duration", "speed": "speed", "wavelength": "wavelength",
                 "size": "size", "ratio": "ratio", "accuracy": "accuracy", "share": "percentage", "acidity": "pH",
                 "signal": "signal", "count": "count"}
IS_AMOUNT = {
    "amount": "a quantity: a measured, chosen or counted amount, size, level, time, temperature, ratio or percentage",
    "label": "not a quantity: part of a name, code, date, year, address, reference or version",
}
ORIGIN = {
    "measured": "an outcome: something reported as measured, observed, produced or obtained",
    "chosen": "a condition: an amount, setting or parameter that was chosen, used or applied",
    "cited": "from earlier work or general knowledge, not obtained in the work being described",
}
ROLE_OF_ORIGIN = {"measured": "result", "chosen": "setting", "cited": "background"}
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
SLOT_QUESTION = {
    "who": "Which organism, strain or cells is {value} reported for (measured in, made by, or given for)?",
    "what": "Which substance, material or thing is {value} {the_property} of?",
    "method": "Which technique or instrument was {value} measured with?",
    "quantity": "Which words name what {value} measures?",
}
CONFIRM = {
    "who": ("Is {value} reported for {x} (measured in it, made by it, or given for it)?",
            "the passage gives {value} as measured in {x}, made by {x}, or given for {x}",
            "{value} is given for another organism, or the passage does not connect it to {x}"),
    "what": ("Is {value} {the_property} of {x}?", "the passage gives {value} for {x}, or for something {x} has, makes or contains",
             "{value} is given for something else, or the passage does not connect it to {x}"),
    "method": ("Was {value} measured with {x}?", "{x} is the technique, instrument or signal that gave {value}",
               "{value} was obtained some other way, or the passage does not say"),
    "quantity": ("Is {value} a value of {x}?", "{value} is a value of {x}", "{value} is a value of something else"),
}
CONFIRM_MIN = 0.5             # a yes/no below this does not confirm the judge's choice


def kind_request(state: str, pending: list[tuple[str, str | None]], prefix: str = "k") -> dict:
    qs = {f"{prefix}{n}": {"type": "choice", "criteria": KIND,
                           "instructions": f"In this passage, what is “{t}”" + (f" ({g})" if g else "") + "?"}
          for n, (t, g) in enumerate(pending)}
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


def _marked(s: Sentence, m: Mention) -> str:
    return s.text[:m.start] + MARK[0] + s.text[m.start:m.end] + MARK[1] + s.text[m.end:]


def _the_property(prop_opts: list[str]) -> str:
    return f"the {PROPERTY_NOUN[prop_opts[0]]}" if len(prop_opts) == 1 and prop_opts[0] in PROPERTY_NOUN else "a value"


def _option_text(o) -> str:
    if isinstance(o, tuple):
        return "every one of them"
    return o.gloss or f"the words “{o.text}” in the passage"


def value_request(m: Mention, s: Sentence, plan: dict) -> dict:
    """The questions for one value: only what neither the layout nor the unit has settled."""
    v = MARK[0] + s.text[m.start:m.end] + MARK[1]
    qs = {}
    if plan["layout"].get("label"):
        return None                              # the layout says it is a label: nothing to ask
    if m.unit is None and not plan["layout"].get("count"):
        qs["amount"] = {"type": "choice", "criteria": IS_AMOUNT, "instructions": f"Is {v} a quantity or a label?"}
    qs["origin"] = {"type": "choice", "criteria": ORIGIN, "instructions": f"Where does the value {v} come from?"}
    if len(plan["property"]) > 1:
        qs["property"] = {"type": "choice", "criteria": {p: PROPERTY[p] for p in plan["property"]},
                          "instructions": f"What is the value {v}?"}
    the_property = _the_property(plan["property"])
    for slot, opts in plan["ask"].items():
        crit = {option_label(o): _option_text(o) for o in opts}
        crit[NONE] = "the value is not given for any of these" if slot in ("who", "what") else "none of these"
        qs[slot] = {"type": "choice", "criteria": crit,
                    "instructions": SLOT_QUESTION[slot].format(value=v, the_property=the_property)}
    return {"state": _marked(s, m), "questions": qs}


def confirm_request(m: Mention, s: Sentence, chosen: dict, prop_opts: list[str]) -> dict:
    v = MARK[0] + s.text[m.start:m.end] + MARK[1]
    the_property = _the_property(prop_opts)
    qs = {}
    for slot, label in chosen.items():
        x = label.replace("all of: ", "each of ")
        q, yes, no = (t.format(value=v, x=f"“{x}”", the_property=the_property) for t in CONFIRM[slot])
        qs[f"c_{slot}"] = {"type": "noul", "instructions": q, "criteria": {"true": yes, "false": no}}
    return {"state": _marked(s, m), "questions": qs}


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
NEAR_TIE = 0.2                # a choice whose margin to the runner-up is below this is flagged


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


# ─────────────────────────── rounds: plan, ask, decide ───────────────────────────

CLAUSE_DB = "clauses.duckdb"
CLAUSE_SCHEMA = """
CREATE TABLE clause_meta(key VARCHAR PRIMARY KEY, value VARCHAR);
CREATE TABLE terms(term VARCHAR PRIMARY KEY, kind VARCHAR, p DOUBLE, margin DOUBLE, decided_by VARCHAR,
                   sentence VARCHAR);
CREATE TABLE phrases(sentence VARCHAR, phrase VARCHAR, kind VARCHAR, p DOUBLE, margin DOUBLE,
                     PRIMARY KEY (sentence, phrase));
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
CLAUSE_COVERS = ("terms", "phrases", "sentences", "aliases", "measures", "jev_calls")


def _sha(obj) -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _key(req, model) -> str:
    return _sha({**req, "model": model})


@dataclass
class Paper:
    """Everything deterministic about one paper's sentences: the ground the three rounds stand on."""
    S: list
    genus: dict
    long_forms: dict          # term -> the long form the paper first defines it with
    known: frozenset          # every abbreviation the paper defines
    defs: dict                # sentence id -> its definitions
    ms: dict                  # sentence id -> its mentions


def read_paper(S: list[Sentence]) -> Paper:
    genus = genus_names(" ".join(s.text for s in S))
    defs = {s.id: aliases(s) for s in S}
    long_forms = {}
    for s in S:
        for d in defs[s.id]:
            long_forms.setdefault(d["term"], d["long_form"])
    return Paper(S, genus, long_forms, frozenset(long_forms), defs, {s.id: mentions(s) for s in S})


def plan_round1(P: Paper) -> list:
    """The kind of every named term that a value's sentence holds (asked once, in the sentence that
    defines it or else first uses it), and every sentence's modality and polarity."""
    items, intro, pending = [], {}, defaultdict(list)
    for s in P.S:
        for d in P.defs[s.id]:
            intro.setdefault(d["term"], s)
    first = {}
    for s in P.S:
        for t, _ in terms(s.text, P.genus, P.known):
            first.setdefault(t, s)
    needed = {t for s in P.S if P.ms[s.id] for t, _ in terms(s.text, P.genus, P.known)}
    for t in sorted(needed, key=lambda t: (first[t].page, P.S.index(first[t]), t)):
        if term_kind_by_rule(t, P.long_forms.get(t)) is None:
            pending[intro.get(t, first[t]).id].append(t)
    by_id = {s.id: s for s in P.S}
    for sid, ts in pending.items():
        items.append(("term", sid, kind_request(by_id[sid].text, [(t, P.long_forms.get(t)) for t in ts]),
                      {"terms": ts}))
    for s in P.S:                                # the nominal phrases no word list settles, in their own sentence
        if not P.ms[s.id]:
            continue
        named = {t for t, _ in terms(s.text, P.genus, P.known)}
        ps = [p for p, _ in noun_phrases(s.text, _value_spans(s.text, P.ms[s.id]))
              if p not in named and lexicon_kind(p) is None]
        if ps:
            items.append(("phrase", s.id, kind_request(s.text, [(p, None) for p in ps], "p"), {"phrases": ps}))
    for s in P.S:
        items.append(("sentence", s.id, sentence_request(s, P.defs[s.id]), {"sentence": s, "defs": P.defs[s.id]}))
    return items


def decide_kinds(P: Paper, items1, responses, model) -> dict:
    """{term: (kind, p, margin, decided_by, sentence)} for every named term a value's sentence holds."""
    out = {}
    for s in P.S:
        if not P.ms[s.id]:
            continue
        for t, _ in terms(s.text, P.genus, P.known):
            k = term_kind_by_rule(t, P.long_forms.get(t))
            if k and t not in out:
                out[t] = (k, None, None, "rule", s.id)
    for kind, target, req, ctx in items1:
        if kind == "term":
            ans = responses[_key(req, model)][1]["answers"]
            for n, t in enumerate(ctx["terms"]):
                d = decision(ans[f"k{n}"])
                out[t] = (d["label"], d["p"], d["margin"], "judge", target)
        elif kind == "phrase":                   # keyed by (sentence, phrase): a phrase's kind is local
            ans = responses[_key(req, model)][1]["answers"]
            for n, ph in enumerate(ctx["phrases"]):
                d = decision(ans[f"p{n}"])
                out[(target, ph)] = (d["label"], d["p"], d["margin"], "judge", target)
    return out


def plan_value(P: Paper, s: Sentence, kinds: dict) -> dict:
    """Per value of the sentence: the layout's bindings, the property options, and the slots to ask."""
    ms = P.ms[s.id]
    k = {t: v[0] for t, v in kinds.items()}
    cands = sentence_candidates(s, ms, k, P.genus, P.known, P.long_forms)
    phrases = noun_phrases(s.text, _value_spans(s.text, ms))
    lay = {m.id: layout(m, s, cands, ms, phrases) for m in ms}
    share_quantity(ms, s.text, lay)
    for mid, (span, slot) in respectively(s, ms, cands).items():
        lay[mid][slot] = [(span, "paired in order by “respectively”")]
    out = {}
    for m in ms:
        L = lay[m.id]
        decided = {slot for slot in SLOTS if L.get(slot)}
        if L.get("count"):
            decided |= set(SLOTS)                    # a count's subject is the thing it counts: nothing else to ask
        ask = {}
        for slot in SLOTS:
            if slot in decided:
                continue
            opts = slot_options(slot, m, s.text, cands)
            if opts:
                ask[slot] = opts
        props = ["count"] if L.get("count") else property_options(m, [q for q, _ in L.get("quantity", [])])
        label = _label_before(s.text, m)
        if label:
            L = {"label": [(label, "a bare integer printed right after a capitalised word")]}
            ask, props = {}, ["other"]
        out[m.id] = {"mention": m, "layout": dict(L), "property": props, "ask": ask}
    return out


def plan_round2(P: Paper, kinds: dict) -> tuple[list, dict]:
    items, plans = [], {}
    for s in P.S:
        if not P.ms[s.id]:
            continue
        for mid, pl in plan_value(P, s, kinds).items():
            pl["sentence"] = s
            plans[mid] = pl
            req = value_request(pl["mention"], s, pl)
            items.append(("mention" if req else "label", mid, req, {"plan": pl}))
    return items, plans


def _chosen(items2, responses, model) -> dict:
    """{mention id: {question: decision}} from round 2."""
    return {target: {q: decision(a) for q, a in responses[_key(req, model)][1]["answers"].items()}
            for kind, target, req, _ in items2 if req is not None}


def plan_round3(items2, responses, model) -> list:
    """A yes/no for every span the judge chose (not for what the layout decided)."""
    items, ch = [], _chosen(items2, responses, model)
    for kind, target, _, ctx in items2:
        if kind == "label":
            continue
        pl = ctx["plan"]
        picked = {slot: ch[target][slot]["label"] for slot in pl["ask"] if ch[target][slot]["label"] != NONE}
        if picked:
            items.append(("confirm", target, confirm_request(pl["mention"], pl["sentence"], picked, pl["property"]),
                          {"plan": pl, "picked": picked}))
    return items


def decide(P: Paper, rounds, responses, model):
    """Turn the judge's answers into rows, with the door's flags."""
    import json
    items1, items2, items3 = rounds
    kinds = decide_kinds(P, items1, responses, model)
    term_rows = [{"term": t, "kind": k, "p": p, "margin": mg, "decided_by": by, "sentence": sid}
                 for t, (k, p, mg, by, sid) in sorted((t, v) for t, v in kinds.items() if isinstance(t, str))]
    phrase_rows = [{"sentence": sid, "phrase": ph, "kind": k, "p": p, "margin": mg}
                   for (sid, ph), (k, p, mg, _, _) in sorted((t, v) for t, v in kinds.items() if isinstance(t, tuple))]
    sent_rows, alias_rows = [], []
    for kind, target, req, ctx in items1:
        if kind != "sentence":
            continue
        ans = responses[_key(req, model)][1]["answers"]
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
    ch = _chosen(items2, responses, model)
    confirmed = {target: responses[_key(req, model)][1]["answers"] for _, target, req, _ in items3}
    measure_rows = []
    for _, target, _, ctx in items2:
        pl, d = ctx["plan"], ch.get(target, {})
        m, s, L = pl["mention"], pl["sentence"], pl["layout"]
        flags = []
        slots = {slot: [span for span, _ in L.get(slot, [])] for slot in SLOTS}
        relations = {}
        for slot, opts in pl["ask"].items():
            c = d[slot]
            rel = {"options": [option_label(o) for o in opts], "choice": c["label"], "p": c["p"], "margin": c["margin"]}
            if c["label"] != NONE:
                yes = confirmed.get(target, {}).get(f"c_{slot}", {}).get("noul")
                rel["confirmed"] = yes
                if yes is not None and yes >= CONFIRM_MIN:
                    opt = next(o for o in opts if option_label(o) == c["label"])
                    slots[slot] = option_members(opt)
                else:
                    flags.append(f"{slot}: the judge chose “{c['label']}” but did not confirm it (yes {yes})")
            if c["margin"] is not None and c["margin"] < NEAR_TIE:
                flags.append(f"{slot}: near tie (margin {c['margin']})")
            relations[slot] = rel
        if "property" in d:
            prop, prop_p, prop_margin = d["property"]["label"], d["property"]["p"], d["property"]["margin"]
        else:
            prop, prop_p, prop_margin = pl["property"][0], None, None
        if L.get("label"):
            role, role_p, role_margin = "identifier", None, None
        elif "amount" in d and d["amount"]["label"] == "label":
            role, role_p, role_margin = "identifier", d["amount"]["p"], d["amount"]["margin"]
            slots = {slot: [] for slot in SLOTS}
        elif prop == "count":
            role, role_p, role_margin = "count", d["origin"]["p"], d["origin"]["margin"]
        else:
            role = ROLE_OF_ORIGIN[d["origin"]["label"]]
            role_p, role_margin = d["origin"]["p"], d["origin"]["margin"]
        q = d.get("quantity")
        measure_rows.append({
            "id": m.id, "sentence": s.id, "atoms": m.atoms, "text": s.text[m.start:m.end], "value": m.value,
            "unit": m.unit, "key": m.key, "lo": m.lo, "hi": m.hi, "note": m.note,
            "role": role, "role_p": role_p, "role_margin": role_margin,
            "property": prop, "property_p": prop_p, "property_margin": prop_margin,
            "about": slots["who"] + [x for x in slots["what"] if x not in slots["who"]],
            "measured_by": slots["method"], "quantity": slots["quantity"],
            "quantity_p": q["p"] if q and "quantity" in pl["ask"] else None,
            "quantity_margin": q["margin"] if q and "quantity" in pl["ask"] else None,
            "relations": json.dumps(relations, ensure_ascii=False),
            "structure": json.dumps({slot: [{"span": x, "why": w} for x, w in v] if isinstance(v, list) else v
                                     for slot, v in L.items()}, ensure_ascii=False),
            "flags": flags})
    # consistency: one subject, method and quantity reported with two different values
    groups_ = defaultdict(list)
    for r in measure_rows:
        if r["role"] == "result" and r["about"]:
            groups_[(tuple(sorted(r["about"])), tuple(sorted(r["measured_by"])), tuple(sorted(r["quantity"])),
                     r["property"], r["unit"])].append(r)
    for rows in groups_.values():
        if len({(r["lo"], r["hi"], r["value"]) for r in rows}) > 1:
            for r in rows:
                others = [o["id"] for o in rows if o is not r and o["value"] != r["value"]]
                if others:
                    r["flags"] = r["flags"] + [f"same subject, method and quantity as {', '.join(others)} "
                                               f"with a different value"]
    return term_rows, phrase_rows, sent_rows, alias_rows, measure_rows


def ask_all(items, *, ask, model, workers=8, log=print):
    """One judge call per distinct request, in parallel. Returns {sha: (request, response, called_at)}."""
    import datetime
    from concurrent.futures import ThreadPoolExecutor
    reqs = {}
    for _, _, req, _ in items:
        if req is not None:
            reqs.setdefault(_key(req, model), req)
    done = {}

    def one(sha_req):
        sha, req = sha_req
        resp = ask(req["state"], req["questions"], model=model)
        return sha, req, resp, datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n, (sha, req, resp, at) in enumerate(pool.map(one, reqs.items()), 1):
            done[sha] = (req, resp, at)
            if n % 50 == 0 or n == len(reqs):
                log(f"  judge: {n}/{len(reqs)} calls")
    return done


def run_rounds(P: Paper, answer, model):
    """The three rounds, each planned from the answers before it. `answer(items)` returns
    {sha: (request, response, called_at)} for them: live calls, or pinned ones."""
    responses = {}
    items1 = plan_round1(P)
    responses.update(answer(items1))
    kinds = decide_kinds(P, items1, responses, model)
    items2, _ = plan_round2(P, kinds)
    responses.update(answer(items2))
    items3 = plan_round3(items2, responses, model)
    responses.update(answer(items3))
    return (items1, items2, items3), responses


# ─────────────────────────── build, replay, receipt ───────────────────────────

def _write(out, root, P, rounds, responses, model, log):
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
    term_rows, phrase_rows, sent_rows, alias_rows, measure_rows = decide(P, rounds, responses, model)
    out.mkdir(parents=True, exist_ok=True)
    db = duckdb.connect(str(out / CLAUSE_DB))
    try:
        db.execute(CLAUSE_SCHEMA)
        kinds = {_key(r, model): (k, t) for items in rounds for k, t, r, _ in items if r is not None}
        store._insert(db, "jev_calls", [
            {"sha": sha, "kind": kinds[sha][0], "target": kinds[sha][1],
             "request": json.dumps(req, ensure_ascii=False), "response": json.dumps(resp, ensure_ascii=False),
             "model": resp.get("model"), "called_at": at} for sha, (req, resp, at) in responses.items()])
        store._insert(db, "terms", term_rows)
        store._insert(db, "phrases", phrase_rows)
        store._insert(db, "sentences", sent_rows)
        store._insert(db, "aliases", alias_rows)
        store._insert(db, "measures", measure_rows)
        usage = [r[1].get("usage", {}) for r in responses.values()]
        meta = {"clause_version": CLAUSE_VERSION, "requested_model": model,
                "served_models": ",".join(sorted({r[1].get("model", "?") for r in responses.values()})),
                "substrate": str(Path(root).resolve()), "substrate_seals": json.dumps(seals, sort_keys=True),
                "built_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "calls": str(len(responses)),
                "questions": str(sum(len(r[0]["questions"]) for r in responses.values())),
                "input_tokens": str(sum(u.get("input_tokens", 0) for u in usage)),
                "output_tokens": str(sum(u.get("output_tokens", 0) for u in usage))}
        db.executemany("INSERT INTO clause_meta VALUES (?, ?)", list(meta.items()))
        db.execute("INSERT INTO seals VALUES (?, ?, ?)",
                   ["clauses", store.rows_sha(db, CLAUSE_COVERS), ",".join(CLAUSE_COVERS)])
    finally:
        db.close()
    log(f"clauses: {len(term_rows)} terms, {len(phrase_rows)} phrases, {len(sent_rows)} sentences, {len(measure_rows)} measures, "
        f"{len(alias_rows)} aliases -> {out / CLAUSE_DB}  ({meta['calls']} calls, {meta['questions']} questions, "
        f"{meta['input_tokens']} in / {meta['output_tokens']} out tokens)")
    return out / CLAUSE_DB


def _paper(root) -> Paper:
    from ugrc import store
    con = store.connect_readonly(root)
    try:
        return read_paper(sentences(con))
    finally:
        con.close()


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


class _NeverAsked(Exception):
    def __init__(self, targets):
        super().__init__(f"{len(targets)} planned question set(s) were never asked: {targets[:5]}")
        self.targets = targets


def _from_pinned(calls, model):
    def answer(items):
        asked = [(t, req) for _, t, req, _ in items if req is not None]
        missing = [t for t, req in asked if _key(req, model) not in calls]
        if missing:
            raise _NeverAsked(missing)
        return {_key(req, model): calls[_key(req, model)] for _, req in asked}
    return answer


def build(root, out, *, ask=None, model=None, workers=8, log=print):
    """Plan, ask the judge round by round, decide, and write <out>/clauses.duckdb (sealed). Never
    touches the substrate."""
    from ugrc import jev
    ask = ask or jev.ask
    model = model or jev.MODEL
    P = _paper(root)
    log(f"paper: {len(P.S)} sentences, {sum(len(v) for v in P.ms.values())} values")
    rounds, responses = run_rounds(P, lambda items: ask_all(items, ask=ask, model=model, workers=workers, log=log),
                                   model)
    return _write(out, root, P, rounds, responses, model, log)


def replay(root, source, out, *, log=print):
    """Rebuild a clause base from another one's pinned judgments: zero calls. Refuses if the plan asks
    anything the source never asked (the substrate or the questions moved)."""
    P = _paper(root)
    calls, model = pinned(source)
    try:
        rounds, responses = run_rounds(P, _from_pinned(calls, model), model)
    except _NeverAsked as e:
        raise SystemExit(f"{e} (in {source})")
    return _write(out, root, P, rounds, responses, model, log)


def recheck(root, clause_dir, *, rerun=False, ask=None, workers=8, log=print) -> list[tuple[bool, str]]:
    """The clause receipt. Zero model by default:
      - the clause base's seal covers its rows;
      - it was built on this substrate (same seals);
      - re-planning from the substrate and the pinned answers asks exactly the pinned questions;
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
        tables = ("terms", "phrases", "sentences", "aliases", "measures")
        stored = {t: db.execute(f'SELECT * FROM "{t}" ORDER BY ALL').fetchall() for t in tables}
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
    P = _paper(root)
    calls, model = pinned(clause_dir)
    try:
        rounds, responses = run_rounds(P, _from_pinned(calls, model), model)
    except _NeverAsked as e:
        out.append((False, f"the plan asks questions that were never pinned: {e}"))
        return out
    n = sum(len(items) for items in rounds)
    out.append((True, f"the plan asks exactly the pinned questions ({n} sets)"))
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, root, P, rounds, responses, model, lambda *_: None)
        db = duckdb.connect(str(Path(tmp) / CLAUSE_DB), read_only=True)
        again = {t: db.execute(f'SELECT * FROM "{t}" ORDER BY ALL').fetchall() for t in stored}
        db.close()
    for t in stored:
        out.append((again[t] == stored[t], f"re-deciding from the pinned answers reproduces {t} ({len(stored[t])} rows)"))
    if rerun:
        ask = ask or jev.ask
        items = [i for r in rounds for i in r]
        fresh = ask_all(items, ask=ask, model=model, workers=workers, log=log)
        same = differ = 0
        for sha, (_, resp, _) in responses.items():
            for q, a in resp["answers"].items():
                b = fresh[sha][1]["answers"].get(q, {})
                if "choice" not in a:
                    ok = (a.get("noul", 0) >= CONFIRM_MIN) == (b.get("noul", 0) >= CONFIRM_MIN)
                    shown_a, shown_b, margin = a.get("noul"), b.get("noul"), None
                else:
                    ok = a.get("choice") == b.get("choice")
                    shown_a, shown_b, margin = a.get("choice"), b.get("choice"), decision(a)["margin"]
                if ok:
                    same += 1
                else:
                    differ += 1
                    out.append((False, f"re-asked: {q} of {sha[:10]} answered {shown_b!r}, pinned {shown_a!r}"
                                       + (f" (pinned margin {margin})" if margin is not None else "")))
        out.append((differ == 0, f"re-asked every pinned question: {same} decisions identical, {differ} differ"))
    return out
