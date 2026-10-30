"""Blind grading of the ChemE test (PLAN.md): each question's 9 answers (hybrid, facts and pdf, 3 runs each) under
letters in an order shuffled by a fixed seed; which arm and run a letter is stays in code until `unseal`.

    python experiments/cheme/grade.py sheet [--paper P] [--limit N]   questions whose answers are all in, not yet graded
    python experiments/cheme/grade.py record < grades.txt             '## <paper>-<id>' then '<letter> c|p|w <note>'
    python experiments/cheme/grade.py progress
    python experiments/cheme/grade.py unseal                          grades.json -> hand.json under each answer's key
    python experiments/cheme/grade.py report                          per arm, paired tests, by category/paper/set

Verdicts follow experiments/new6/GRADING.md: correct; partial (nothing false, an asked part missing); wrong (anything
false, including an accepted false premise and a false "not in the paper"). A computed value within 0.5% of the key
counts as right. Grades are hashed into graded.sha256 before unseal. On new6 the pdf answers are the ones graded
before (experiments/new6/hand.json), graded again here blind among the others: the two grades measure the grader.
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
import run as R  # noqa: E402  (probes, answer_path, ARMS)

ARMS = ("hybrid", "facts", "pdf")
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
    return {f"{paper}-{p['id']}": dict(p, paper=paper, set=s) for s, paper, p in R.probes()}


def slots(key):
    pairs = [(a, r) for a in ARMS for r in RUNS]
    random.Random(f"cheme:{key}").shuffle(pairs)
    return [(chr(ord("A") + i), a, r) for i, (a, r) in enumerate(pairs)]


def record(arm, run, key, p):
    f = R.answer_path(arm, run, p["set"], p["paper"], p["id"])
    return json.loads(f.read_text()) if f.exists() else None


def sheet():
    grades, paper, limit, n = _load(GRADES), _arg("--paper"), _arg("--limit", 10_000, int), 0
    for key, p in probes().items():
        if paper and p["paper"] != paper:
            continue
        sl = slots(key)
        recs = {L: record(a, r, key, p) for L, a, r in sl}
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
    have = sum(all(record(a, r, k, p) for _, a, r in slots(k)) for k, p in keys.items())
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


def _pair(right, qs, a, b):
    d = {k: right[a][k] - right[b][k] for k in qs}
    w, l = sum(x > 0 for x in d.values()), sum(x < 0 for x in d.values())
    return (f"{a} - {b}: sum of d = {sum(d.values()):+d} over {len(qs)} questions ({w} better, {l} worse, "
            f"{len(qs) - w - l} equal); exact paired sign-flip p = {blind.exact_p(list(d.values())):.4f}")


def report():
    hand, keys = _load(HAND), probes()
    for name, sel in (("all", lambda p: True), ("new6", lambda p: p["set"] == "new6"),
                      ("cheme", lambda p: p["set"] == "cheme")):
        qs = [k for k, p in keys.items() if sel(p) and all(f"{a}-r{r}/{k}" in hand for a in ARMS for r in RUNS)]
        if not qs:
            continue
        print(f"\n== {name}: {len(qs)} questions fully graded ({len(qs) * 3} answers per arm)")
        right = {}
        for arm in ARMS:
            c = collections.Counter(hand[f"{arm}-r{r}/{k}"]["verdict"] for k in qs for r in RUNS)
            per_run = [sum(hand[f"{arm}-r{r}/{k}"]["verdict"] == "correct" for k in qs) for r in RUNS]
            right[arm] = {k: sum(hand[f"{arm}-r{r}/{k}"]["verdict"] == "correct" for r in RUNS) for k in qs}
            print(f"{arm:7} right per run {per_run}  all runs: right {c['correct']} partial {c['partial']} "
                  f"wrong {c['wrong']} of {len(qs) * len(RUNS)}")
        for a, b in (("hybrid", "pdf"), ("facts", "pdf"), ("hybrid", "facts")):
            print(_pair(right, qs, a, b))
        for gname, group in (("category", lambda k: keys[k]["cat"]), ("paper", lambda k: keys[k]["paper"])):
            if name == "all" and gname == "paper":
                continue
            rows = collections.defaultdict(list)
            for k in qs:
                rows[group(k)].append(k)
            print(f"by {gname} (right of runs: hybrid / facts / pdf):")
            for g, ks in sorted(rows.items()):
                print(f"  {g:16} " + " / ".join(f"{sum(right[a][k] for k in ks):3}" for a in ARMS) + f"  of {3 * len(ks)}")
    old = _load(ROOT / "experiments" / "new6" / "hand.json")
    same = [(old[f"llama-direct-r{r}/{k}"]["verdict"], hand[f"pdf-r{r}/{k}"]["verdict"])
            for k, p in keys.items() if p["set"] == "new6" for r in RUNS
            if f"llama-direct-r{r}/{k}" in old and f"pdf-r{r}/{k}" in hand]
    if same:
        agree = sum(a == b for a, b in same)
        print(f"\ngrader consistency (new6 pdf answers, graded twice): {agree} of {len(same)} verdicts agree; "
              f"changes {collections.Counter(f'{a}->{b}' for a, b in same if a != b)}")


if __name__ == "__main__":
    {"sheet": sheet, "record": record_grades, "progress": progress, "unseal": unseal, "report": report}[sys.argv[1]]()
