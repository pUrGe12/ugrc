"""Leads: the clause-base rows that bear on a question, found by code before the model's first turn.

The clause base (ugrc/clauses.py) holds every sentence of the prose and every value in it, with what a
judge read each value to be: what it is about, how it was measured, what it measures. A question names
some of those things. Code matches the question's words against each sentence and the readings of its
values (only the document's own words: what a value is of, by what method, what it measures, its unit; not
the judge's category label), widened by the document's own definitions ("vanadium pentoxide (V2O5)", the
clause base's aliases) and, for a word found nowhere, by its one-letter misspellings. It ranks the
sentences by how rare the matched words are in the document, and hands the best ones,
with their values, to the answering model together with the question, so that its first move is to read,
not to search. No model chooses the leads: the same question over the same clause base gives the same
leads, and the record keeps which ones were shown.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from ugrc import answer, store
from ugrc.refusal import Refusal

MAX_SENTENCES = 12          # sentences shown with a question
MAX_VALUES = 8              # values shown under one sentence
SENTENCE_CHARS = 400        # a shown sentence is cut here
MIN_SHARE = 0.3             # a sentence scoring below this share of the best one is not shown
READING_WEIGHT = 2.0        # a word found in a value's reading counts this many times one found only in the text
MIN_STEM = 4                # words at least this long also match a longer or shorter form of themselves
STEM_SLACK = 2              # ... when they agree on all but this many trailing letters of the shorter one
                            #     ("capacity" / "capacities", "strain" / "strains", "limit" / "limits")
MIN_TYPO = 5                # a word at least this long that occurs nowhere matches the words one edit away
                            #     ("copacity" -> "capacity", "battories" -> "batteries")
ALIAS_WEIGHT = 0.8          # a word added from a definition counts this share of a word the question has
MAX_PHRASE = 4              # question phrases up to this many words are looked up as defined long forms
_DEFINED = r"\s*\(([^()\s]{2,20})\)"     # "<long form> (<short form>)", as a paper defines a name

_TOKEN = re.compile(r"[^\W_]+")
# Words that carry no subject: function words, and the words questions are asked in.
STOP = frozenset("""
    a an the and or nor not no of in on at to from by for with without into onto over under than then as
    is are was were be been being am do does did done has have had having can could would should may might
    will shall must it its this that these those there their they them he she his her we our you your i me my
    what which who whom whose when where why how whether if so such any all each every both either neither
    some other another more most less least many much few very also only just about between among per via
    paper papers study studies work works article articles document documents author authors report reports
    reported reporting value values give gives given list lists listed mention mentions mentioned state
    states stated say says said show shows shown use uses used using find found tell describe described
    according compare compared comparison do does doing does provide provided
""".split())


@dataclass
class Leads:
    text: str = ""                                   # the block shown to the model; "" without a clause base
    sentences: list = field(default_factory=list)    # sentence ids shown, best first
    measures: list = field(default_factory=list)     # measure ids shown
    matched: int = 0                                 # sentences that matched the question at all

    def record(self) -> dict:
        return {"sentences": self.sentences, "measures": self.measures, "matched": self.matched}


def terms(question: str) -> list[str]:
    """The question's words that can name a subject, folded as a search compares them, in order."""
    out = []
    for w in _TOKEN.findall(answer.fold(question)):
        if len(w) < 2 or w in STOP or w in out:
            continue
        out.append(w)
    return out


def _matches(term: str, word: str) -> bool:
    if term == word:
        return True
    if len(term) < MIN_STEM or len(word) < MIN_STEM or any(c.isdigit() for c in term + word):
        return False
    n = 0
    for a, b in zip(term, word):
        if a != b:
            break
        n += 1
    return n >= max(MIN_STEM, min(len(term), len(word)) - STEM_SLACK)


def _words(*texts) -> set[str]:
    return {w for t in texts for w in _TOKEN.findall(answer.fold(t or ""))}


def _reading_text(m: dict) -> list[str]:
    return [*(m["about"] or []), *(m["method"] or []), *(m["quantity"] or []), m["unit"] or ""]


def _one_edit(a: str, b: str) -> bool:
    """a and b differ by one substitution, insertion or deletion."""
    if abs(len(a) - len(b)) > 1 or a == b:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i + (len(a) == len(b)):] == b[i + 1:]


def defined(con, question: str, texts) -> list[str]:
    """Names the document defines for what the question says, or says in full for a name the question
    uses: a phrase of the question followed by "(SHORT)" in some sentence ("vanadium pentoxide (V2O5)"),
    and the clause base's aliases the judge accepted, both ways round. Folded, in order found."""
    words = [w for w in _TOKEN.findall(answer.fold(question))]
    asked = set(terms(question))
    out = []
    for n in range(MAX_PHRASE, 0, -1):
        for i in range(len(words) - n + 1):
            gram = words[i:i + n]
            if gram[0] in STOP or gram[-1] in STOP or (n == 1 and len(gram[0]) < MIN_STEM):
                continue
            pat = re.compile(r"(?<![\w])" + r"[\s-]+".join(map(re.escape, gram)) + _DEFINED)
            for t in texts:
                for m in pat.finditer(t):
                    short = answer.fold(m.group(1)).strip(".,;:")
                    if short and short[0].isalpha() and short not in asked and short not in out and short not in STOP:
                        out.append(short)
    for term, long_form in con.execute("SELECT term, long_form FROM c.main.aliases WHERE verdict = 'yes'").fetchall():
        t, lf = answer.fold(term or ""), _TOKEN.findall(answer.fold(long_form or ""))
        lf_terms = [w for w in lf if w not in STOP and len(w) > 1]
        if t in asked:
            out += [w for w in lf_terms if w not in asked and w not in out]
        elif lf_terms and all(any(_matches(q, w) for q in asked) for w in lf_terms) and t not in out:
            out += _TOKEN.findall(t)
    return out


def find(con, question: str) -> Leads:
    """The sentences (with their values) that match the question best; an empty Leads without a clause base."""
    if not store.has_clauses(con):
        return Leads()
    doc = "doc" in {r[0] for r in con.execute("DESCRIBE sentences").fetchall()}
    sents = con.execute(f"SELECT id, page, {'doc' if doc else 'NULL'}, text, modality, polarity, atoms FROM sentences "
                        "WHERE kind <> 'heading' ORDER BY id").fetchall()
    cols = ("id", "sentence", "text", "role", "property", "about", "method", "quantity", "unit")
    values = {}
    for row in con.execute(f"SELECT {', '.join(cols)} FROM measures ORDER BY id").fetchall():
        m = dict(zip(cols, row))
        values.setdefault(m["sentence"], []).append(m)
    asked = terms(question)
    if not asked or not sents:
        return Leads(_block([], 0), [], [], 0)
    folded = [answer.fold(s[3] or "") for s in sents]
    extra = defined(con, question, folded)
    weight = {**{t: ALIAS_WEIGHT for t in extra}, **{t: 1.0 for t in asked}}
    qs = list(weight)

    text_words = {s[0]: _words(s[3]) for s in sents}
    value_words = {mid: _words(*_reading_text(m)) for ms in values.values() for m in ms for mid in [m["id"]]}
    vocab = set().union(*text_words.values(), *value_words.values())
    hits = {t: {w for w in vocab if _matches(t, w)} for t in qs}       # the word forms each term matches
    for t in qs:                                                       # a word found nowhere: a misspelling?
        if not hits[t] and len(t) >= MIN_TYPO and not any(c.isdigit() for c in t):
            hits[t] = {w for w in vocab if _one_edit(t, w)}
    n = len(sents)

    def has(words, t):
        return not hits[t].isdisjoint(words)

    df = {t: sum(1 for s in sents if has(text_words[s[0]], t)
                 or any(has(value_words[m["id"]], t) for m in values.get(s[0], []))) for t in qs}
    idf = {t: weight[t] * math.log((n + 1) / (df[t] + 0.5)) for t in qs if df[t]}

    scored = []
    for s in sents:
        sid, ms = s[0], values.get(s[0], [])
        score, vscore = 0.0, {}
        for t, w in idf.items():
            in_reading = [m["id"] for m in ms if has(value_words[m["id"]], t)]
            for mid in in_reading:
                vscore[mid] = vscore.get(mid, 0.0) + w
            if in_reading:
                score += READING_WEIGHT * w
            elif has(text_words[sid], t):
                score += w
        if score > 0:
            scored.append((score, bool(ms), sid, s, ms, vscore))
    if not scored:
        return Leads(_block([], 0), [], [], 0)
    scored.sort(key=lambda x: (-x[0], not x[1], x[2]))
    best = scored[0][0]
    shown = [x for x in scored if x[0] >= MIN_SHARE * best][:MAX_SENTENCES]

    built = []

    def flows():
        if not built:
            built.append(answer.Flows(con))
        return built[0]

    groups, measure_ids = [], []
    for _, _, sid, s, ms, vscore in shown:
        keep = sorted(ms, key=lambda m: (-vscore.get(m["id"], 0.0), m["id"]))[:MAX_VALUES]
        keep.sort(key=lambda m: _offset(m["id"]))                    # in the order the sentence prints them
        rows = []
        for m in keep:
            try:
                answer.check_measure(con, m["id"], "leads", flows)
                ok = True
            except Refusal:
                ok = False
            rows.append((m, ok))
            measure_ids.append(m["id"])
        groups.append((s, rows, len(ms)))
    return Leads(_block(groups, len(scored)), [g[0][0] for g in groups], measure_ids, len(scored))


def _offset(mid: str) -> int:
    try:
        return int(mid.rsplit("#", 1)[1])
    except (IndexError, ValueError):
        return 0


def _block(groups, matched) -> str:
    head = "## Leads from the clause base\n"
    if not groups:
        return head + ("No sentence of the prose matched the words of this question. Search lines, cells and "
                       "figure_facts as usual (table cells and figure facts are not in the clause base).")
    out = [head + f"Code matched the words of this question against every sentence of the prose and what the judge "
           f"read each value in it to be. These {len(groups)} sentences matched best ({matched} matched at all). They "
           "are leads, not answers: check from its sentence that a value is what you need, and search lines, cells "
           "and figure_facts when they do not hold it (table cells and figure facts are not in the clause base). "
           "Show a value listed here with {\"measure\": \"<its id>\"}."]
    for (sid, page, doc, text, modality, polarity, atoms), rows, n_values in groups:
        lines = atoms[0] if len(atoms) == 1 else f"{atoms[0]}–{atoms[-1]}"
        where = f"{doc}, page {page}" if doc else f"page {page}"
        mood = modality + (", negated" if polarity == "negated" else "")
        cut = text if len(text) <= SENTENCE_CHARS else text[:SENTENCE_CHARS] + " …"
        out.append(f"- sentence {sid} ({where}, lines {lines}; {mood}): {cut!r}")
        for m, ok in rows:
            parts = [m["role"] or "?"]
            if m["property"] and m["property"] != "other":
                parts.append(m["property"])
            for label, key in (("of", "about"), ("by", "method"), ("measures", "quantity")):
                if m[key]:
                    parts.append(f"{label} " + " / ".join(m[key]))
            note = "" if ok else " (cannot be shown as it is: quote it yourself from its line)"
            out.append(f"    - {m['id']} {m['text']!r}: " + "; ".join(parts) + note)
        if n_values > len(rows):
            more = n_values - len(rows)
            out.append(f"    - … {more} more value{'s' if more > 1 else ''} in this sentence (measures WHERE sentence = '{sid}')")
    return "\n".join(out)
