"""Blind grading of the routed test (PLAN.md): each question's 2 answers (prose, pdf; one run) under letters shuffled
by a fixed seed; which arm a letter is stays in code until `unseal`.

    python experiments/routed/grade.py sheet [--limit N]       questions whose answers are all in, not graded
    python experiments/routed/grade.py record < grades.txt     '## <key>' then '<letter> c|p|w <note>'
    python experiments/routed/grade.py progress
    python experiments/routed/grade.py unseal                  grades.json -> hand.json (hashed first)
    python experiments/routed/grade.py report                  the comparisons PLAN.md names

Rules: ../library/GRADING.md (1-29, L1-L5) and GRADING.md here (R1).
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
_spec = importlib.util.spec_from_file_location("library_grade", ROOT / "experiments" / "library" / "grade.py")
G = importlib.util.module_from_spec(_spec)
sys.modules["library_grade"] = G
_spec.loader.exec_module(G)               # blind, titles, questions, reference, the library test's hand.json
blind = G.blind

ARMS = ("prose", "pdf")
GRADES = HERE / "grades.json"
HAND = HERE / "hand.json"
SIGN = "(Claude, 2026-10-31, blind to arm)"
FULL = {"c": "correct", "p": "partial", "w": "wrong"}
TAGS = G.TAGS


def _arg(name, default=None, cast=str):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def _load(p):
    return json.loads(p.read_text()) if p.exists() else {}


def slots(key):
    arms = list(ARMS)
    random.Random(f"routed:{key}").shuffle(arms)
    return [(chr(ord("A") + i), a) for i, a in enumerate(arms)]


def path(arm, key):
    s, paper, pid = key.split("/")
    return HERE / "answers" / f"{arm}-r1" / f"{s}__{paper}-{pid}.json"


def record(arm, key):
    f = path(arm, key)
    return json.loads(f.read_text()) if f.exists() else None


def sheet():
    grades, limit, n, T, routes = _load(GRADES), _arg("--limit", 10_000, int), 0, G.titles(), \
        json.loads((HERE / "routes.json").read_text())["routes"]
    for key, q in G.questions().items():
        sl = slots(key)
        recs = {L: record(a, key) for L, a in sl}
        todo = [L for L, _ in sl if L not in grades.get(key, {})]
        if not todo or any(v is None for v in recs.values()):
            continue
        r = routes[key]
        sent = "its own paper" if r["routed_right"] else f"ANOTHER paper: {T[r['routed']]}"
        print(f"######## {key}  [{q['cat']}]  paper: {T[q['set'] + '/' + q['paper']]}\nrouted to: {sent}\n"
              f"Q: {q['q']}\nE: {q['expect']}\nT: {q.get('trap') or '-'}")
        for L in todo:
            print(f"--- {L}\n{blind.shown(recs[L]['rendered'] or '(empty)')}")
        print()
        n += 1
        if n >= limit:
            break
    print(f"{n} question(s) shown")


def record_grades():
    grades, key, n, keys = _load(GRADES), None, 0, G.questions()
    for line in sys.stdin.read().splitlines():
        if not line.strip():
            continue
        if line.startswith("## "):
            key = line[3:].strip()
            assert key in keys, key
            continue
        letter, v, *note = line.split(maxsplit=2)
        assert key and letter in {L for L, _ in slots(key)} and v in FULL, line
        grades.setdefault(key, {})[letter] = {"verdict": FULL[v], "note": note[0] if note else ""}
        n += 1
    GRADES.write_text(json.dumps(grades, indent=1, ensure_ascii=False) + "\n")
    print(f"{n} grades recorded")


def progress():
    grades, keys = _load(GRADES), G.questions()
    have = sum(all(record(a, k) for a in ARMS) for k in keys)
    done = sum(len(grades.get(k, {})) == len(ARMS) for k in keys)
    print(f"{len(keys)} questions, {have} with every answer in, {done} fully graded")


def unseal():
    (HERE / "graded.sha256").write_text(f"{hashlib.sha256(GRADES.read_bytes()).hexdigest()}  grades.json\n")
    hand = {}
    for key, g in _load(GRADES).items():
        for L, a in slots(key):
            if L in g:
                hand[f"{a}/{key}"] = {"verdict": g[L]["verdict"], "note": f"{g[L]['note']} {SIGN}".strip()}
    HAND.write_text(json.dumps(hand, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(hand)} grades unsealed to hand.json; grades.json hashed in graded.sha256")


def report():
    hand, lib, qs = _load(HAND), _load(G.HAND), G.questions()
    routes = json.loads((HERE / "routes.json").read_text())["routes"]
    keys = [k for k in qs if all(f"{a}/{k}" in hand for a in ARMS)]
    if not keys:
        raise SystemExit("nothing unsealed yet")
    right = {a: {k: int(hand[f"{a}/{k}"]["verdict"] == "correct") for k in keys} for a in ARMS}
    lright = {a: {k: int(lib[f"{a}/{k}"]["verdict"] == "correct") for k in keys} for a in G.ARMS}
    print(f"== {len(keys)} questions fully graded (one answer per arm)")
    for a in ARMS:
        c = collections.Counter(hand[f"{a}/{k}"]["verdict"] for k in keys)
        print(f"routed {a:5} right {c['correct']:3}  partial {c['partial']:3}  wrong {c['wrong']:3}  of {len(keys)}")
    print(G._pair(right["prose"], right["pdf"], keys, "routed prose", "routed pdf"))
    print("against the library test's arms (paired by question; graded in another session):")
    for a, b in (("prose", "prose"), ("prose", "pages"), ("pdf", "pages"), ("prose", "facts")):
        print("  " + G._pair(right[a], lright[b], keys, f"routed {a}", f"library {b}"))
    print("library test, same questions: " + ", ".join(f"{a} {sum(lright[a].values())}" for a in G.ARMS))
    ref = G.reference(keys, qs)
    print("one paper in view, same questions in their original wording (mean right per run): "
          + ", ".join(f"{a} {v:.1f}" for a, v in ref.items()))
    for gname, group in (("category", lambda k: qs[k]["cat"]), ("set", lambda k: qs[k]["set"]),
                         ("library", lambda k: qs[k]["library"])):
        rows = collections.defaultdict(list)
        for k in keys:
            rows[group(k)].append(k)
        print(f"by {gname} (right: routed prose / routed pdf / library prose / library pages):")
        for g, ks in sorted(rows.items()):
            line = " / ".join(f"{sum(d[k] for k in ks):3}" for d in (right["prose"], right["pdf"], lright["prose"],
                                                                       lright["pages"]))
            print(f"  {g:8} {line}  of {len(ks):3}")
    for k in keys:
        if not routes[k]["routed_right"]:
            print(f"misrouted {k} -> {routes[k]['routed']}: " + ", ".join(
                f"{a} {hand[f'{a}/{k}']['verdict']}" for a in ARMS))
    tags = collections.Counter((key.split("/")[0], t) for key, v in hand.items() for t in TAGS if t in v["note"])
    print("tags (all verdicts): " + ", ".join(f"{a} {t} {n}" for (a, t), n in sorted(tags.items())))
    toks = {a: [((record(a, k) or {}).get("usage") or {}).get("prompt_tokens") for k in keys] for a in ARMS}
    print("mean prompt tokens: " + ", ".join(f"{a} {sum(x for x in v if x) / max(1, len([x for x in v if x])):,.0f}"
                                             for a, v in toks.items()))


if __name__ == "__main__":
    {"sheet": sheet, "record": record_grades, "progress": progress, "unseal": unseal, "report": report}[sys.argv[1]]()
