"""Blind grading of cheme2 (PLAN.md): each question's 9 answers (prose, facts, pdf x 3 runs) under letters shuffled
by a fixed seed; which arm and run a letter is stays in code until `unseal`.

    python experiments/cheme2/grade.py sheet [--paper P] [--limit N]   questions whose answers are all in, not yet graded
    python experiments/cheme2/grade.py record < grades.txt             '## <paper>-<id>' then '<letter> c|p|w <note>'
    python experiments/cheme2/grade.py progress
    python experiments/cheme2/grade.py unseal                          grades.json -> hand.json under each answer's key
    python experiments/cheme2/grade.py report                          the comparisons PLAN.md names

Verdicts and rules: ../cheme/GRADING.md (1-23), ../prose/GRADING.md (24-25), GRADING.md here. Grades are hashed into graded.sha256 before unseal.
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
import run as R  # noqa: E402  (probes, answer_path)

ARMS = ("prose", "facts", "pdf")
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
    return {f"{paper}-{p['id']}": dict(p, paper=paper) for paper, p in R.probes()}


def slots(key):
    pairs = [(a, r) for a in ARMS for r in RUNS]
    random.Random(f"cheme2:{key}").shuffle(pairs)
    return [(chr(ord("A") + i), a, r) for i, (a, r) in enumerate(pairs)]


def path(arm, run, p):
    return R.answer_path(arm, run, p["paper"], p["id"])


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


OLD = set(json.loads((ROOT / "experiments" / "cheme" / "papers.json").read_text()))     # the ChemE test's 10 topics


def report():
    hand, keys = _load(HAND), probes()
    qs_all = [k for k in keys if all(f"{a}-r{r}/{k}" in hand for a in ARMS for r in RUNS)]
    for name, sel in (("all", lambda k: True), ("old topics", lambda k: keys[k]["paper"] in OLD),
                      ("new topics", lambda k: keys[k]["paper"] not in OLD)):
        qs = [k for k in qs_all if sel(k)]
        if not qs:
            continue
        print(f"\n== {name}: {len(qs)} questions fully graded ({len(qs) * 3} answers per arm)")
        right = {a: {k: _right(hand, f"{a}-r", k) for k in qs} for a in ARMS}
        for arm in ARMS:
            c = collections.Counter(hand[f"{arm}-r{r}/{k}"]["verdict"] for k in qs for r in RUNS)
            per_run = [sum(hand[f"{arm}-r{r}/{k}"]["verdict"] == "correct" for k in qs) for r in RUNS]
            print(f"{arm:6} right per run {per_run}  all runs: right {c['correct']} partial {c['partial']} "
                  f"wrong {c['wrong']} of {len(qs) * len(RUNS)}")
        for a, b in (("prose", "pdf"), ("prose", "facts"), ("facts", "pdf")):
            print(_pair(right[a], right[b], qs, a, b))
        for gname, group in (("category", lambda k: keys[k]["cat"]), ("paper", lambda k: keys[k]["paper"])):
            if name != "all" and gname == "category":
                continue
            rows = collections.defaultdict(list)
            for k in qs:
                rows[group(k)].append(k)
            print(f"by {gname} (right of runs: prose / facts / pdf):")
            for g, ks in sorted(rows.items()):
                print(f"  {g:22} " + " / ".join(f"{sum(right[a][k] for k in ks):3}" for a in ARMS) + f"  of {3 * len(ks)}")
    tags = collections.Counter((key.split("-r")[0], t) for key, v in hand.items() if v["verdict"] == "wrong"
                               for t in ("[label]", "[hedge]", "[render]") if t in v["note"])
    print(f"\ntagged wrongs: {dict(sorted(tags.items()))}")


if __name__ == "__main__":
    {"sheet": sheet, "record": record_grades, "progress": progress, "unseal": unseal, "report": report}[sys.argv[1]]()
