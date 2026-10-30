"""Blind grading of the new6 answers: each question's 6 answers (hybrid and pasted PDF, 3 runs each) under letters in
an order shuffled by a fixed seed; which arm and run a letter is stays in code until `unseal`.

    python experiments/new6/grade.py sheet [--paper P] [--limit N]   questions whose answers are all in, not yet graded
    python experiments/new6/grade.py record < grades.txt             '## <paper>-<id>' then '<letter> c|p|w <note>'
    python experiments/new6/grade.py progress
    python experiments/new6/grade.py unseal                          grades.json -> hand.json under each answer's key
    python experiments/new6/grade.py report                          per arm, per category, and the paired test

Verdicts follow bench-cross/jev-pick/GRADING.md: correct; partial (nothing false, an asked part missing); wrong
(anything false, including an accepted false premise and a false "not in the paper"). A computed value within 0.5% of
the key counts as right. Grades are hashed into graded.sha256 before unseal.
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
import blind  # noqa: E402  (shown, exact_p)

ARMS = ("llama-hybrid", "llama-direct")
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
    frozen = (HERE / "frozen.sha256").read_text().split()[0]
    assert hashlib.sha256((HERE / "probes.json").read_bytes()).hexdigest() == frozen, "probes.json changed"
    return {f"{paper}-{p['id']}": dict(p, paper=paper)
            for paper, ps in json.loads((HERE / "probes.json").read_text())["papers"].items() for p in ps}


def slots(key):
    pairs = [(a, r) for a in ARMS for r in RUNS]
    random.Random(f"new6:{key}").shuffle(pairs)
    return [(chr(ord("A") + i), a, r) for i, (a, r) in enumerate(pairs)]


def record(arm, run, key):
    f = HERE / "answers" / f"{arm}-r{run}" / f"{key}.json"
    return json.loads(f.read_text()) if f.exists() else None


def sheet():
    grades, paper, limit, n = _load(GRADES), _arg("--paper"), _arg("--limit", 10_000, int), 0
    for key, p in probes().items():
        if paper and p["paper"] != paper:
            continue
        sl = slots(key)
        recs = {L: record(a, r, key) for L, a, r in sl}
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
    have = sum(all(record(a, r, k) for _, a, r in slots(k)) for k in keys)
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


def report():
    hand, keys = _load(HAND), probes()
    qs = [k for k in keys if all(f"{a}-r{r}/{k}" in hand for a in ARMS for r in RUNS)]
    print(f"== new6: {len(qs)} of {len(keys)} questions fully graded")
    right = {}
    for arm in ARMS:
        c = collections.Counter(hand[f"{arm}-r{r}/{k}"]["verdict"] for k in qs for r in RUNS)
        per_run = [sum(hand[f"{arm}-r{r}/{k}"]["verdict"] == "correct" for k in qs) for r in RUNS]
        right[arm] = {k: sum(hand[f"{arm}-r{r}/{k}"]["verdict"] == "correct" for r in RUNS) for k in qs}
        print(f"{arm:14} right per run {per_run}  all runs: right {c['correct']} partial {c['partial']} wrong {c['wrong']} "
              f"of {len(qs) * len(RUNS)}")
    d = {k: right["llama-hybrid"][k] - right["llama-direct"][k] for k in qs}
    w, l = sum(x > 0 for x in d.values()), sum(x < 0 for x in d.values())
    print(f"hybrid - direct: sum of d = {sum(d.values())} over {len(qs)} questions ({w} better, {l} worse, "
          f"{len(qs) - w - l} equal); exact paired sign-flip p = {blind.exact_p(list(d.values())):.4f}")
    for name, group in (("category", lambda k: keys[k]["cat"]), ("paper", lambda k: keys[k]["paper"])):
        rows = collections.defaultdict(list)
        for k in qs:
            rows[group(k)].append(k)
        print(f"by {name} (right of runs, hybrid / direct):")
        for g, ks in sorted(rows.items()):
            h, dd = sum(right["llama-hybrid"][k] for k in ks), sum(right["llama-direct"][k] for k in ks)
            print(f"  {g:16} {h:3} / {dd:3}  of {3 * len(ks)}")
    print("questions that differ: " + ", ".join(f"{k} {right['llama-hybrid'][k]}-{right['llama-direct'][k]}" for k in qs if d[k]))


if __name__ == "__main__":
    {"sheet": sheet, "record": record_grades, "progress": progress, "unseal": unseal, "report": report}[sys.argv[1]]()
