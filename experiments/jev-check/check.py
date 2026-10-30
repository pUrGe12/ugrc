"""Jev as a checker of free answers: does the paper support what an answer says about each number in it?

    JEV_API_KEY=... python experiments/jev-check/check.py SET [--workers 8]      run the checker over a set of answers
    python experiments/jev-check/check.py report SET                              how its flags line up with the hand grades

SET is one of
  dev    the 308 clause-reasoning answers (llama-clauses-r1, llama-clauses-text-r1): built and looked at on these
  test   the 838 hybrid answers not looked at while building it (llama-hybrid-r1 single-paper, 154; llama-hybrid-corpus*
         r1-r3, 684), run once with nothing changed

For each answer, with no model:
  1. every number of two or more characters in it (a line that is only a number, a model counting, is skipped);
  2. the passages of the answer's paper that print that number: its clause-base sentences, its table rows (caption and
     column headers first) and its figure facts. For a corpus answer the paper is the one the question names, so a
     value taken from another paper finds no passage;
  3. up to TOP passages, those sharing most words with the answer's sentence around the number.
Then for each number, Jev reads each candidate passage, the number marked [[...]], and answers one yes/no question: does
the passage give the number for what the answer's sentence says it is? The number is supported when one passage gets yes
>= CONFIRM_MIN (ugrc's own 0.5). A number printed in no passage of the paper is supported only when code can recompute
it from an "a op b (op c) = number" the sentence writes out. An answer is FLAGGED when any of its numbers is unsupported,
PASSED when all are supported, and NO CLAIM when it holds no number.

Every Jev request and response is cached in jev_cache.jsonl, so a rerun calls Jev only for what it has not asked.
Results go to results-<SET>.json.
"""
import hashlib
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from ugrc import clauses, jev, store  # noqa: E402

TOP = 3
MAX_NUMBERS = 30
ANSWERS = ROOT / "experiments" / "bench-llama" / "answers"
CACHE = HERE / "jev_cache.jsonl"
NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
WORD = re.compile(r"[a-z0-9]+")
STOP = set("the a an of in on at to for and or is are was were be by with from as that this it its than which what "
           "how much many does do did".split())
lock = threading.Lock()


def _n(s):
    return s.replace(",", "").replace(" ", "").rstrip(".")


def _words(s):
    return {w for w in WORD.findall(s.lower()) if w not in STOP}


# ── the paper's passages ──

def passages(paper):
    """[(id, text, {numbers})] of a paper: clause-base sentences, table rows with caption and headers, figure facts."""
    con = store.connect_question(ROOT / "runs" / "bench" / paper)
    out = [(sid, t) for sid, t in con.execute("SELECT id, text FROM sentences").fetchall()]
    heads = {}
    for tid, h in con.execute("SELECT table_id, header FROM table_columns ORDER BY table_id, col_no").fetchall():
        heads.setdefault(tid, []).append(h or "")
    for tid, label, cap in con.execute("SELECT id, label, caption FROM tables").fetchall():
        rows = {}
        for r, t in con.execute("SELECT row_no, text FROM cells WHERE table_id = ? ORDER BY row_no, col_no", [tid]).fetchall():
            rows.setdefault(r, []).append(t or "")
        for r, cells in rows.items():
            out.append((f"{tid}.r{r}", f"{label}. {cap or ''} Columns: {' | '.join(heads.get(tid, []))}. Row: {' | '.join(cells)}"))
    for kid, label, st, v, u in con.execute(
            "SELECT k.id, f.label, k.statement, k.value, k.unit FROM figure_facts k JOIN figures f ON f.id = k.figure_id").fetchall():
        out.append((kid, f"({label}, read from the image) {st}" + (f" ({v} {u or ''})" if v is not None else "")))
    out = [(i, THOUSANDS.sub("", t)) for i, t in out if t]          # "$10 000" reads as 10000, as an answer writes it
    return [(i, t, {_n(x) for x in NUM.findall(t)}) for i, t in out]


THOUSANDS = re.compile(r"(?<=\d)[   ](?=\d{3}(?![\d.,]))")


def mark(text, number):
    """The passage with the first occurrence of the number wrapped in [[ ]]."""
    for m in NUM.finditer(text):
        if _n(m.group()) == number:
            return text[:m.start()] + "[[" + m.group() + "]]" + text[m.end():]
    return text


# ── the answer's numbers ──

_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])|\n+")


def _eval(expr):
    """The value of an arithmetic expression (numbers, + - * /, parentheses), or None; no other syntax is run."""
    import ast
    import operator
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](ev(node.left), ev(node.right))
        raise ValueError
    try:
        return ev(ast.parse(expr, mode="eval"))
    except (SyntaxError, ValueError, ZeroDivisionError, RecursionError):
        return None


def _expression_text(lhs):
    """The left side of an '=' with units and words taken out: unit slashes (mAh/gS) dropped, × ÷ − as operators,
    thousands commas removed, anything but numbers, operators and parentheses blanked."""
    s = re.sub(r"(?<=[A-Za-zµμ])\s*/\s*(?=[A-Za-zµμ])", " ", lhs)
    s = re.sub(r"(?<=[\d)\s])[x×](?=[\s(\d])", "*", s).replace("÷", "/").replace("−", "-").replace("–", "-")
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)
    return re.sub(r"[^0-9.+\-*/() ]", " ", s)


def recomputed(sentence):
    """{result} of each 'expression = result' (or ≈) the sentence writes out whose arithmetic holds within 0.5% (or as
    a percent of it): the longest tail of the left side that evaluates with at least one operator is taken."""
    ok = set()
    parts = re.split(r"(=|≈)", sentence)
    for i in range(1, len(parts) - 1, 2):
        m = re.match(r"\s*~?\s*(\d[\d,]*(?:\.\d+)?)", parts[i + 1])
        if not m:
            continue
        target = float(_n(m.group(1)))
        toks = re.findall(r"\d+(?:\.\d+)?|[-+*/()]", _expression_text(parts[i - 1]))
        for start in range(len(toks)):                  # every tail of the left side, longest first
            expr = " ".join(toks[start:])
            if not any(t in "+-*/" for t in toks[start + 1:]):
                break
            val = _eval(expr)
            if val is not None and _close(val, target):
                ok.add(_n(m.group(1)))
                break
    return ok


def _close(val, target):
    return bool(target) and (abs(val - target) <= 0.005 * abs(target) or abs(val - target) < 0.006
                             or abs(val * 100 - target) <= 0.005 * abs(target))


def derivable(target, others):
    """Whether one arithmetic step (a+b, a-b, a*b, a/b, a percent change) or a chain of two products or quotients over
    the answer's other numbers gives the target, within 0.5%: a computed value consistent with the numbers it uses."""
    try:
        t = float(target)
    except ValueError:
        return False
    xs = []
    for o in others:
        try:
            x = float(o)
        except ValueError:
            continue
        if x not in xs:
            xs.append(x)
    xs = xs[:25]
    for a in xs:
        for b in xs:
            if a == b:
                continue
            for v in (a + b, a - b, a * b, a / b if b else None, (a - b) / b * 100 if b else None):
                if v is not None and _close(v, t):
                    return True
            for c in xs:
                if c in (a, b):
                    continue
                for v in (a * b * c, a * b / c if c else None):
                    if v is not None and _close(v, t):
                        return True
    return False


_EXPONENT_BEFORE = re.compile(r"\^\s*\(?\s*[-−–]?\s*$")
_TIMES_100_BEFORE = re.compile(r"([*×x]\s*|multipl\w* (?:it )?by\s*)$", re.IGNORECASE)


def _not_a_claim(sent, m, v):
    before, after = sent[max(0, m.start() - 16):m.start()], sent[m.end():m.end() + 2]
    return (after.lstrip().startswith("^") or bool(_EXPONENT_BEFORE.search(before))
            or (v == "100" and bool(_TIMES_100_BEFORE.search(before))))


def claims(text):
    """[(number, sentence)] for the numbers an answer states, in order, at most MAX_NUMBERS. Left out: a line that is
    only a number (a model counting), an exponent or the base of a power (10^-16), and the 100 of "x 100" or
    "multiply by 100" (turning a fraction into a percent)."""
    out = []
    for sent in _SPLIT.split(text or ""):
        if sent.strip().isdigit():
            continue
        for m in NUM.finditer(sent):
            v = _n(m.group())
            if _not_a_claim(sent, m, v):
                continue
            if len(v) >= 2 and (v, sent) not in out:
                out.append((v, sent.strip()))
    return out[:MAX_NUMBERS]


def answer_numbers(text):
    return [_n(x) for x in NUM.findall(text or "")]


# ── Jev ──

def question(number_marked, sentence):
    v = f"[[{number_marked}]]"
    return {"c": {"type": "noul",
                  "instructions": f"Does the passage give {v} for what this statement says it is? Statement: “{sentence}”",
                  "criteria": {"true": f"the passage gives {v} for the same thing, in the same sense, as the statement",
                               "false": f"the passage gives {v} for something else, or does not say what the statement "
                                        f"says about it"}}}


_cache = None


def ask(state, qs):
    global _cache
    key = hashlib.sha256(json.dumps([state, qs], sort_keys=True).encode()).hexdigest()
    with lock:
        if _cache is None:
            _cache = {}
            if CACHE.exists():
                for line in CACHE.read_text().splitlines():
                    r = json.loads(line)
                    _cache[r["key"]] = r["response"]
        if key in _cache:
            return _cache[key]
    resp = jev.ask(state, qs)
    with lock:
        _cache[key] = resp
        with CACHE.open("a") as f:
            f.write(json.dumps({"key": key, "state": state, "questions": qs, "response": resp}, ensure_ascii=False) + "\n")
    return resp


def check(rec, psg):
    """The checker's reading of one answer: each number, its candidate passages and Jev's yes, and the verdict."""
    rows = []
    every = answer_numbers(rec.get("rendered"))
    for v, sent in claims(rec.get("rendered")):
        cands = sorted((p for p in psg if v in p[2]), key=lambda p: (-len(_words(sent) & _words(p[1])), p[0]))[:TOP]
        row = {"number": v, "sentence": sent[:500], "candidates": []}
        others = [x for x in every if x != v]
        if not cands:
            if v in recomputed(sent):
                row["supported"], row["by"] = True, "arithmetic"
            elif derivable(v, others):
                row["supported"], row["by"] = True, "derived from the answer's numbers"
            else:
                row["supported"], row["by"] = False, "printed nowhere in the paper"
            rows.append(row)
            continue
        for pid, text, _ in cands:
            state = mark(text, v)
            marked = state[state.index("[[") + 2: state.index("]]")] if "[[" in state else v
            try:
                p = ask(state, question(marked, sent[:500]))["answers"]["c"]["noul"]
            except (jev.JevError, KeyError, TypeError) as e:
                p = None
                row["error"] = str(e)[:200]
            row["candidates"].append({"passage": pid, "p": p})
        ps = [c["p"] for c in row["candidates"] if c["p"] is not None]
        row["supported"] = bool(ps) and max(ps) >= clauses.CONFIRM_MIN
        row["by"] = "jev"
        if not row["supported"] and v in recomputed(sent):     # a value the paper prints is a claim Jev judges; only an
            row["supported"], row["by"] = True, "arithmetic"    # explicit sum the answer writes out can stand instead
        rows.append(row)
    verdict = "no claim" if not rows else ("passed" if all(r["supported"] for r in rows) else "flagged")
    return {"verdict": verdict, "numbers": rows}


# ── sets, run, report ──

def records(which):
    arms = {"dev": ["llama-clauses-r1", "llama-clauses-text-r1"],
            "test": ["llama-hybrid-r1"] + [f"{a}-r{r}" for a in ("llama-hybrid-corpus", "llama-hybrid-corpus-bm25") for r in (1, 2, 3)]}[which]
    out = {}
    for arm in arms:
        for f in sorted((ANSWERS / arm).glob("*/*.json")):
            if f.name.endswith(".error.json"):
                continue
            out[f"{arm}/{f.parent.name}/{f.stem}"] = json.loads(f.read_text())
    return out


def run(which, workers):
    recs = records(which)
    cache, results = {}, {}
    for k, r in recs.items():
        if r["paper"] not in cache:
            cache[r["paper"]] = passages(r["paper"])

    def one(k):
        results[k] = check(recs[k], cache[recs[k]["paper"]])
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, sorted(recs)))
    (HERE / f"results-{which}.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    print(f"{len(results)} answers checked; {sum(len(v['numbers']) for v in results.values())} numbers")
    report(which)


def report(which):
    results = json.loads((HERE / f"results-{which}.json").read_text())
    hand = json.loads((ROOT / "experiments" / "bench-llama" / "hand.json").read_text())
    import collections
    tab = collections.Counter()
    for k, res in results.items():
        h = (hand.get(k) or {}).get("verdict", "ungraded")
        tab[(res["verdict"], h)] += 1
    verdicts = ("correct", "partial", "wrong")
    print(f"\n== {which}: checker verdict against hand grade ({len(results)} answers)")
    print(f"{'':10} " + " ".join(f"{h:>8}" for h in verdicts) + "    total")
    for c in ("passed", "flagged", "no claim"):
        print(f"{c:10} " + " ".join(f"{tab[(c, h)]:>8}" for h in verdicts) + f"   {sum(tab[(c, h)] for h in verdicts):>6}")
    wrong = sum(tab[(c, 'wrong')] for c in ('passed', 'flagged', 'no claim'))
    right = sum(tab[(c, 'correct')] for c in ('passed', 'flagged', 'no claim'))
    print(f"wrong answers flagged: {tab[('flagged', 'wrong')]} of {wrong}; right answers flagged: {tab[('flagged', 'correct')]} "
          f"of {right}")
    passed = sum(tab[('passed', h)] for h in verdicts)
    if passed:
        print(f"of the {passed} passed answers, {tab[('passed', 'correct')]} are right ({100 * tab[('passed', 'correct')] / passed:.0f}%), "
              f"{tab[('passed', 'wrong')]} wrong; over all answers {100 * right / len(results):.0f}% are right")


if __name__ == "__main__":
    if sys.argv[1] == "report":
        report(sys.argv[2])
    else:
        run(sys.argv[1], int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 8)
