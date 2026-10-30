"""Blind grading of facts+prose against facts (PLAN.md): each question's 6 answers (3 runs each) under letters shuffled
by a fixed seed; which arm and run a letter is stays in code until `unseal`.

    python experiments/prose/grade.py sheet [--paper P] [--limit N]   questions whose answers are all in, not yet graded
    python experiments/prose/grade.py record < grades.txt             '## <paper>-<id>' then '<letter> c|p|w <note>'
    python experiments/prose/grade.py progress
    python experiments/prose/grade.py unseal                          grades.json -> hand.json under each answer's key
    python experiments/prose/grade.py report                          the comparisons PLAN.md names

Verdicts and rules: ../cheme/GRADING.md (1-23). Grades are hashed into graded.sha256 before unseal.
"""
import collections
import hashlib
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "bench-cross" / "jev-pick"))
sys.path.insert(0, str(HERE))
import blind  # noqa: E402  (shown, exact_p)
import run as P  # noqa: E402  (C = cheme run, answer_path)

ARMS = ("prose", "facts")
RUNS = (1, 2, 3)
GRADES = HERE / "grades.json"
HAND = HERE / "hand.json"
SIGN = "(Claude, 2026-10-30, blind to arm)"
FULL = {"c": "correct", "p": "partial", "w": "wrong"}


def _arg(name, default=None, cast=str):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def _load(p):
    return json.loads(p.read_text()) if p.exists() else {}


def probes():
    return {f"{paper}-{p['id']}": dict(p, paper=paper, set=s) for s, paper, p in P.C.probes()}


def slots(key):
    pairs = [(a, r) for a in ARMS for r in RUNS]
    random.Random(f"prose:{key}").shuffle(pairs)
    return [(chr(ord("A") + i), a, r) for i, (a, r) in enumerate(pairs)]


def path(arm, run, p):
    if arm == "prose":
        return P.answer_path(run, p["paper"], p["id"])
    return P.C.answer_path("facts", run, p["set"], p["paper"], p["id"])


def record(arm, run, p):
    f = path(arm, run, p)
    return json.loads(f.read_text()) if f.exists() else None


def sheet():
    grades, paper, limit, n = _load(GRADES), _arg("--paper"), _arg("--limit", 10_000, int), 0
    for key, p in probes().items():
        if paper and p["paper"] != paper:
            continue
        sl = slots(key)
        recs = {L: record(a, r, p) for L, a, r in sl}
        todo = [L for L, _, _ in sl if L not in grades.get(key, {})]
        if not todo or any(v is None for v in recs.values()):
            continue
        print(f"######## {key}  [{p['cat']}]\nQ: {p['q']}\nE: {p['expect']}\nT: {p.get('trap') or '-'}")
        for L in todo:
            print(f"--- {L}\n{blind.shown(recs[L]['rendered'] or '(empty)')}")
        print()
        n += 1
        if n >= limit:
            break
    print(f"{n} question(s) shown")


def record_grades():
    grades, key, n, keys = _load(GRADES), None, 0, probes()
    for line in sys.stdin.read().splitlines():
        if not line.strip():
            continue
        if line.startswith("## "):
            key = line[3:].strip()
            assert key in keys, key
            continue
        letter, v, *note = line.split(maxsplit=2)
        assert key and letter in {L for L, _, _ in slots(key)} and v in FULL, line
        grades.setdefault(key, {})[letter] = {"verdict": FULL[v], "note": note[0] if note else ""}
        n += 1
    GRADES.write_text(json.dumps(grades, indent=1, ensure_ascii=False) + "\n")
    print(f"{n} grades recorded")


def progress():
    grades, keys = _load(GRADES), probes()
    have = sum(all(record(a, r, p) for _, a, r in slots(k)) for k, p in keys.items())
    done = sum(len(grades.get(k, {})) == len(ARMS) * len(RUNS) for k in keys)
    print(f"{len(keys)} questions, {have} with every answer in, {done} fully graded")


def unseal():
    (HERE / "graded.sha256").write_text(f"{hashlib.sha256(GRADES.read_bytes()).hexdigest()}  grades.json\n")
    hand = {}
    for key, g in _load(GRADES).items():
        for L, a, r in slots(key):
            if L in g:
                hand[f"{a}-r{r}/{key}"] = {"verdict": g[L]["verdict"], "note": f"{g[L]['note']} {SIGN}".strip()}
    HAND.write_text(json.dumps(hand, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(hand)} grades unsealed to hand.json; grades.json hashed in graded.sha256")


def _right(hand, prefix, k):
    return sum(hand[f"{prefix}{r}/{k}"]["verdict"] == "correct" for r in RUNS)


def _pair(da, db, qs, a, b):
    d = {k: da[k] - db[k] for k in qs}
    w, l = sum(x > 0 for x in d.values()), sum(x < 0 for x in d.values())
    return (f"{a} - {b}: sum of d = {sum(d.values()):+d} over {len(qs)} questions ({w} better, {l} worse, "
            f"{len(qs) - w - l} equal); exact paired sign-flip p = {blind.exact_p(list(d.values())):.4f}")


def report():
    hand, keys = _load(HAND), probes()
    old = _load(ROOT / "experiments" / "cheme" / "hand.json")       # hybrid, facts, pdf as graded in the ChemE test
    for name, sel in (("all", lambda p: True), ("new6", lambda p: p["set"] == "new6"),
                      ("cheme", lambda p: p["set"] == "cheme")):
        qs = [k for k, p in keys.items() if sel(p) and all(f"{a}-r{r}/{k}" in hand for a in ARMS for r in RUNS)]
        if not qs:
            continue
        print(f"\n== {name}: {len(qs)} questions fully graded ({len(qs) * 3} answers per arm)")
        right = {"prose": {k: _right(hand, "prose-r", k) for k in qs}, "facts": {k: _right(hand, "facts-r", k) for k in qs}}
        for arm in ("hybrid", "facts", "pdf"):
            right[f"{arm} (ChemE grades)"] = {k: _right(old, f"{arm}-r", k) for k in qs}
        for arm in ARMS:
            c = collections.Counter(hand[f"{arm}-r{r}/{k}"]["verdict"] for k in qs for r in RUNS)
            per_run = [sum(hand[f"{arm}-r{r}/{k}"]["verdict"] == "correct" for k in qs) for r in RUNS]
            print(f"{arm:6} right per run {per_run}  all runs: right {c['correct']} partial {c['partial']} "
                  f"wrong {c['wrong']} of {len(qs) * len(RUNS)}")
        for arm in ("hybrid", "facts", "pdf"):
            print(f"{arm + ' (ChemE grades)':22} right {sum(right[arm + ' (ChemE grades)'].values())}")
        print(_pair(right["prose"], right["facts"], qs, "prose", "facts"))
        for arm in ("pdf", "hybrid"):
            print(_pair(right["prose"], right[f"{arm} (ChemE grades)"], qs, "prose", f"{arm} (ChemE grades)"))
        for gname, group in (("category", lambda k: keys[k]["cat"]), ("paper", lambda k: keys[k]["paper"])):
            if name == "all" and gname == "paper":
                continue
            rows = collections.defaultdict(list)
            for k in qs:
                rows[group(k)].append(k)
            print(f"by {gname} (right of runs: prose / facts / facts (ChemE grades) / pdf (ChemE grades)):")
            for g, ks in sorted(rows.items()):
                print(f"  {g:16} " + " / ".join(f"{sum(right[a][k] for k in ks):3}" for a in
                                                ("prose", "facts", "facts (ChemE grades)", "pdf (ChemE grades)"))
                      + f"  of {3 * len(ks)}")
    same = [(old[f"facts-r{r}/{k}"]["verdict"], hand[f"facts-r{r}/{k}"]["verdict"])
            for k in keys for r in RUNS if f"facts-r{r}/{k}" in old and f"facts-r{r}/{k}" in hand]
    if same:
        agree = sum(a == b for a, b in same)
        print(f"\ngrader drift (facts answers, graded in the ChemE test and again here): {agree} of {len(same)} verdicts "
              f"agree; changes {collections.Counter(f'{a}->{b}' for a, b in same if a != b)}")


if __name__ == "__main__":
    {"sheet": sheet, "record": record_grades, "progress": progress, "unseal": unseal, "report": report}[sys.argv[1]]()
