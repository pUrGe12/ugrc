"""Blind grading of the fresh-paper test (PLAN.md): each question's answers (top1, pdf, and oracle where top1's paper is
not the question's) under letters shuffled by a fixed seed; which arm a letter is stays in code until `unseal`.

    python experiments/fresh/grade.py sheet [--paper P] [--limit N]   questions whose answers are all in, not graded
    python experiments/fresh/grade.py record < grades.txt              '## <key>' then '<letter> c|p|w <note>'
    python experiments/fresh/grade.py progress
    python experiments/fresh/grade.py unseal                           grades.json -> hand.json (hashed first)
    python experiments/fresh/grade.py report                           the comparisons PLAN.md names

Rules: GRADING.md here (the big-library rules, Q3, N1).
"""
import collections
import hashlib
import importlib.util
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("big_grade", ROOT / "experiments" / "big-library" / "grade.py")
BG = importlib.util.module_from_spec(_spec)
sys.modules["big_grade"] = BG
_spec.loader.exec_module(BG)
G, blind = BG.G, BG.blind

ARMS = ("top1", "oracle", "pdf")
GRADES = HERE / "grades.json"
HAND = HERE / "hand.json"
SIGN = "(Claude, blind to arm)"
FULL = {"c": "correct", "p": "partial", "w": "wrong"}
TAGS = G.TAGS


def _arg(name, default=None, cast=str):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def _load(p):
    return json.loads(p.read_text()) if p.exists() else {}


def questions():
    return json.loads((HERE / "questions.json").read_text())["questions"]


def routes():
    return json.loads((HERE / "routes.json").read_text())["routes"]


def titles():
    t = BG.titles()
    t.update({f"fresh/{k}": v["title"] for k, v in json.loads((HERE / "papers.json").read_text()).items()})
    return t


def arms_of(key, rt):
    return [a for a in ARMS if a != "oracle" or not rt[key]["routed_right"]]


def slots(key, rt):
    arms = arms_of(key, rt)
    random.Random(f"fresh:{key}").shuffle(arms)
    return [(chr(ord("A") + i), a) for i, a in enumerate(arms)]


def record(arm, key):
    _, p, pid = key.split("/")
    f = HERE / "answers" / f"{arm}-r1" / f"{p}-{pid}.json"
    return json.loads(f.read_text()) if f.exists() else None


def sheet():
    grades, only, limit, n = _load(GRADES), _arg("--paper"), _arg("--limit", 10_000, int), 0
    T, rt = titles(), routes()
    for key, q in questions().items():
        if only and q["paper"] != only:
            continue
        sl = slots(key, rt)
        recs = {L: record(a, key) for L, a in sl}
        todo = [L for L, _ in sl if L not in grades.get(key, {})]
        if not todo or any(v is None for v in recs.values()):
            continue
        target = rt[key]["target"]
        held = sorted({rec["shown_paper"] for rec in recs.values()})
        papers = "; ".join(f"{T.get(d, d)[:70]}{' (its own)' if d == target else ''}" for d in held)
        print(f"######## {key}  [{q['cat']}]  paper: {T[target]}\nprompts held: {papers}\n"
              f"Q: {q['q']}\nE: {q['expect']}\nT: {q.get('trap') or '-'}")
        for L in todo:
            print(f"--- {L}\n{blind.shown(recs[L]['rendered'] or '(empty)')}")
        print()
        n += 1
        if n >= limit:
            break
    print(f"{n} question(s) shown")


def record_grades():
    grades, key, n, rt = _load(GRADES), None, 0, routes()
    for line in sys.stdin.read().splitlines():
        if not line.strip():
            continue
        if line.startswith("## "):
            key = line[3:].strip()
            assert key in rt, key
            continue
        letter, v, *note = line.split(maxsplit=2)
        assert key and letter in {L for L, _ in slots(key, rt)} and v in FULL, line
        grades.setdefault(key, {})[letter] = {"verdict": FULL[v], "note": note[0] if note else ""}
        n += 1
    GRADES.write_text(json.dumps(grades, indent=1, ensure_ascii=False) + "\n")
    print(f"{n} grades recorded")


def progress():
    grades, rt = _load(GRADES), routes()
    have = sum(all(record(a, k) for a in arms_of(k, rt)) for k in rt)
    done = sum(len(grades.get(k, {})) == len(arms_of(k, rt)) for k in rt)
    print(f"{len(rt)} questions, {have} with every answer in, {done} fully graded")


def unseal():
    lines = [f"{hashlib.sha256(GRADES.read_bytes()).hexdigest()}  grades.json"]
    if (HERE / "GRADING-settled.md").exists():
        lines.append(f"{hashlib.sha256((HERE / 'GRADING-settled.md').read_bytes()).hexdigest()}  GRADING-settled.md")
    (HERE / "graded.sha256").write_text("\n".join(lines) + "\n")
    hand, rt = {}, routes()
    for key, g in _load(GRADES).items():
        for L, a in slots(key, rt):
            if L in g:
                hand[f"{a}/{key}"] = {"verdict": g[L]["verdict"], "note": f"{g[L]['note']} {SIGN}".strip()}
    HAND.write_text(json.dumps(hand, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(hand)} grades unsealed to hand.json; grades.json hashed in graded.sha256")


def report():
    hand, qs, rt = _load(HAND), questions(), routes()
    K = [k for k in qs if all(f"{a}/{k}" in hand for a in arms_of(k, rt))]
    if not K:
        raise SystemExit("nothing unsealed yet")

    def right(arm, k):
        if arm == "oracle" and rt[k]["routed_right"]:
            arm = "top1"                                   # the same prompt
        return int(hand[f"{arm}/{k}"]["verdict"] == "correct")

    R = {a: {k: right(a, k) for k in K} for a in ARMS}
    print(f"== {len(K)} of {len(qs)} questions graded")
    for a in ARMS:
        c = collections.Counter(hand[f"{a}/{k}"]["verdict"] for k in K if f"{a}/{k}" in hand)
        print(f"  {a:6} graded {sum(c.values()):3}: right {c['correct']:3}  partial {c['partial']:3}  wrong {c['wrong']:3}")
    print("right of " + str(len(K)) + " (oracle = top1 where search picks the right paper): "
          + "  ".join(f"{a} {sum(R[a].values())}" for a in ARMS))
    print("  " + G._pair(R["top1"], R["pdf"], K, "top1", "pdf") + "   (primary)")
    print("  " + G._pair(R["top1"], R["oracle"], K, "top1", "oracle") + "   (routing)")
    print("  " + G._pair(R["oracle"], R["pdf"], K, "oracle", "pdf"))
    miss = [k for k in K if not rt[k]["routed_right"]]
    print(f"misrouted ({len(miss)}): right " + "  ".join(f"{a} {sum(R[a][k] for k in miss)}" for a in ARMS)
          + "; " + " ".join(f"{k}({qs[k]['cat']})" for k in miss))
    for gname, group in (("category", lambda k: qs[k]["cat"]), ("paper", lambda k: qs[k]["paper"])):
        by = collections.defaultdict(list)
        for k in K:
            by[group(k)].append(k)
        print(f"by {gname} (right: top1 / oracle / pdf):")
        for g, ks in sorted(by.items()):
            print(f"  {g:22} " + " / ".join(f"{sum(R[a][k] for k in ks):2}" for a in ARMS) + f"  of {len(ks)}")
    for cut in (0.9, 0.85, 0.8):
        flag = {k for k in K if rt[k]["unsure"] >= cut}
        tot = sum(R["oracle"][k] if k in flag else R["top1"][k] for k in K)
        print(f"post hoc, ask when unsure >= {cut}: asks {len(flag)} times ({len(flag & set(miss))} misrouted), right {tot}")
    tags = collections.Counter((key.split("/")[0], t) for key, v in hand.items() for t in TAGS if t in v["note"])
    print("tags: " + ", ".join(f"{a} {t} {n}" for (a, t), n in sorted(tags.items())))


if __name__ == "__main__":
    {"sheet": sheet, "record": record_grades, "progress": progress, "unseal": unseal, "report": report}[sys.argv[1]]()
