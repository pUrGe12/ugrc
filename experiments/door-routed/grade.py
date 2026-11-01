"""Blind grading of the door on the winning setup (PLAN.md): each question's answers (top1 graded again, and each door
arm's accepted answer) under letters shuffled by a fixed seed; which arm a letter is stays in code until `unseal`.

    python experiments/door-routed/grade.py sheet [--paper P] [--limit N]   questions whose answers are all in, not graded
    python experiments/door-routed/grade.py record < grades.txt              '## <key>' then '<letter> c|p|w <note>'
    python experiments/door-routed/grade.py progress
    python experiments/door-routed/grade.py unseal                           grades.json -> hand.json (hashed first)
    python experiments/door-routed/grade.py report                           the comparisons PLAN.md names

Rules: GRADING.md here. A door arm with no accepted answer has no letter: nothing reached the user, so not right.
"""
import collections
import hashlib
import importlib.util
import json
import random
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("fresh_grade", ROOT / "experiments" / "fresh" / "grade.py")
FG = importlib.util.module_from_spec(_spec)
sys.modules["fresh_grade"] = FG
_spec.loader.exec_module(FG)
G, blind = FG.G, FG.blind

ARMS = ("top1", "door", "door-facts")
DOORS = ("door", "door-facts")
GRADES = HERE / "grades.json"
HAND = HERE / "hand.json"
SIGN = "(Claude, blind to arm)"
FULL = FG.FULL
MARK = re.compile(r"\[\d+\]")          # the door's citation marks; removed from every answer alike


def _load(p):
    return json.loads(p.read_text()) if p.exists() else {}


def record(arm, key):
    if arm == "top1":
        return FG.record("top1", key)
    _, p, pid = key.split("/")
    f = HERE / "answers" / f"{arm}-r1" / f"{p}-{pid}.json"
    return json.loads(f.read_text()) if f.exists() else None


def all_in(key):
    return all(record(a, key) is not None for a in ARMS)


def delivered(arm, key):
    rec = record(arm, key)
    return bool(rec is not None and (arm == "top1" or (rec.get("accepted") and (rec.get("rendered") or "").strip())))


def slots(key):
    arms = [a for a in ARMS if delivered(a, key)]
    random.Random(f"door-routed:{key}").shuffle(arms)
    return [(chr(ord("A") + i), a) for i, a in enumerate(arms)]


def sheet():
    grades, only, limit, n = _load(GRADES), FG._arg("--paper"), FG._arg("--limit", 10_000, int), 0
    T, rt = FG.titles(), FG.routes()
    for key, q in FG.questions().items():
        if only and q["paper"] != only:
            continue
        if not all_in(key):
            continue
        sl = slots(key)
        todo = [(L, a) for L, a in sl if L not in grades.get(key, {})]
        if not todo:
            continue
        print(f"######## {key}  [{q['cat']}]  paper: {T[rt[key]['target']]}\n"
              f"Q: {q['q']}\nE: {q['expect']}\nT: {q.get('trap') or '-'}")
        for L, a in todo:
            text = MARK.sub("", record(a, key)["rendered"] or "").strip()
            print(f"--- {L}\n{blind.shown(text or '(empty)')}")
        print()
        n += 1
        if n >= limit:
            break
    print(f"{n} question(s) shown")


def record_grades():
    grades, key, n, rt = _load(GRADES), None, 0, FG.routes()
    for line in sys.stdin.read().splitlines():
        if not line.strip():
            continue
        if line.startswith("## "):
            key = line[3:].strip()
            assert key in rt, key
            continue
        letter, v, *note = line.split(maxsplit=2)
        assert key and letter in {L for L, _ in slots(key)} and v in FULL, line
        grades.setdefault(key, {})[letter] = {"verdict": FULL[v], "note": note[0] if note else ""}
        n += 1
    GRADES.write_text(json.dumps(grades, indent=1, ensure_ascii=False) + "\n")
    print(f"{n} grades recorded")


def progress():
    grades, qs = _load(GRADES), FG.questions()
    have = [k for k in qs if all_in(k)]
    done = sum(len(grades.get(k, {})) == len(slots(k)) for k in have)
    print(f"{len(qs)} questions, {len(have)} with every arm's record in, {done} fully graded; "
          + ", ".join(f"{a} delivered {sum(delivered(a, k) for k in have)}" for a in ARMS))


def unseal():
    lines = [f"{hashlib.sha256(GRADES.read_bytes()).hexdigest()}  grades.json"]
    if (HERE / "GRADING-settled.md").exists():
        lines.append(f"{hashlib.sha256((HERE / 'GRADING-settled.md').read_bytes()).hexdigest()}  GRADING-settled.md")
    (HERE / "graded.sha256").write_text("\n".join(lines) + "\n")
    hand = {}
    for key, g in _load(GRADES).items():
        for L, a in slots(key):
            if L in g:
                hand[f"{a}/{key}"] = {"verdict": g[L]["verdict"], "note": f"{g[L]['note']} {SIGN}".strip()}
    HAND.write_text(json.dumps(hand, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(hand)} grades unsealed to hand.json; grades.json hashed in graded.sha256")


def verdict(hand, arm, k):
    return hand.get(f"{arm}/{k}", {}).get("verdict") if delivered(arm, k) else "no answer"


def report():
    hand, qs = _load(HAND), FG.questions()
    K = [k for k in qs if all_in(k) and all(f"{a}/{k}" in hand for _, a in slots(k))]
    if not K:
        raise SystemExit("nothing unsealed yet")
    V = {a: {k: verdict(hand, a, k) for k in K} for a in ARMS}
    R = {a: {k: int(V[a][k] == "correct") for k in K} for a in ARMS}
    print(f"== {len(K)} of {len(qs)} questions graded")
    for a in ARMS:
        c = collections.Counter(V[a].values())
        d = len(K) - c["no answer"]
        print(f"  {a:10} delivered {d:3}: right {c['correct']:3}  partial {c['partial']:3}  wrong {c['wrong']:3}  "
              f"no answer {c['no answer']:3}   of delivered: right {c['correct'] / max(d, 1):.0%}, "
              f"wrong {c['wrong'] / max(d, 1):.0%}")
    print("  " + G._pair(R["door-facts"], R["top1"], K, "door-facts", "top1") + "   (primary)")
    print("  " + G._pair(R["door"], R["top1"], K, "door", "top1"))
    print("  " + G._pair(R["door-facts"], R["door"], K, "door-facts", "door"))
    old = _load(ROOT / "experiments" / "fresh" / "hand.json")
    was = {k: old[f"top1/{k}"]["verdict"] for k in K if f"top1/{k}" in old}
    moved = [(k, was[k], V["top1"][k]) for k in was if was[k] != V["top1"][k]]
    print(f"grader drift, top1 regraded against the fresh grading: right {sum(v == 'correct' for v in was.values())} "
          f"then, {sum(R['top1'].values())} now; {len(moved)} verdicts moved: "
          + ", ".join(f"{k.split('/', 1)[1]} {a}->{b}" for k, a, b in moved))
    by = collections.defaultdict(list)
    for k in K:
        by[qs[k]["cat"]].append(k)
    print("by category (right: " + " / ".join(ARMS) + "):")
    for c, ks in sorted(by.items()):
        print(f"  {c:16} " + " / ".join(f"{sum(R[a][k] for k in ks):2}" for a in ARMS) + f"  of {len(ks)}")
    for a in DOORS:
        recs = [record(a, k) for k in K]
        ok = [r for r in recs if r.get("accepted")]
        if not ok:
            continue
        med = lambda xs: statistics.median(xs) if xs else 0  # noqa: E731
        kinds = collections.Counter(c["kind"] for r in ok for c in r.get("citations") or [])
        rules = collections.Counter(x["rule"] for r in recs for sub in r.get("door_refusals") or [] for x in sub)
        gates = collections.Counter(p.get("verdict") for r in ok for p in r.get("pairings") or [])
        print(f"{a}: accepted {len(ok)}; per accepted answer, median turns {med([r['turns'] for r in ok])}, "
              f"refused submissions {med([len(r['door_refusals']) for r in ok])}, seconds {med([r['seconds'] for r in ok])}, "
              f"input tokens {med([r['usage']['input_tokens'] for r in ok]):,.0f}; numbers by pointer kind: {dict(kinds)}; "
              f"pairings: {dict(gates)}")
        print(f"  most refused rules (all {sum(rules.values())} refusals): "
              + ", ".join(f"{r} {n}" for r, n in rules.most_common(8)))
        fails = collections.Counter((r.get("error") or "")[:60] for r in recs if not r.get("accepted"))
        print(f"  no accepted answer: {sum(fails.values())}; " + "; ".join(f"{e!r} {n}" for e, n in fails.most_common(3)))
    tags = collections.Counter((key.split("/")[0], t) for key, v in hand.items() for t in G.TAGS if t in v["note"])
    print("tags: " + ", ".join(f"{a} {t} {n}" for (a, t), n in sorted(tags.items())))


if __name__ == "__main__":
    {"sheet": sheet, "record": record_grades, "progress": progress, "unseal": unseal, "report": report}[sys.argv[1]]()
