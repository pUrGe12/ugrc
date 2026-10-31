"""Blind grading of the big-library test (PLAN.md): each question's answers (top1, top2, and oracle where top1's paper is
not the question's; one run) under letters shuffled by a fixed seed; which arm a letter is stays in code until `unseal`.

    python experiments/big-library/grade.py sheet [--set S] [--limit N]   questions whose answers are all in, not graded
    python experiments/big-library/grade.py record < grades.txt           '## <key>' then '<letter> c|p|w <note>'
    python experiments/big-library/grade.py progress
    python experiments/big-library/grade.py unseal                        grades.json -> hand.json (hashed first)
    python experiments/big-library/grade.py report                        the comparisons PLAN.md names

Rules: ../library/GRADING.md (1-29, L1-L5), ../routed/GRADING.md (R1) and GRADING.md here (B1-B3).
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
_spec.loader.exec_module(G)               # blind, _pair, TAGS
blind = G.blind

ARMS = ("top1", "top2", "oracle")
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
    return {k: v["title"] for k, v in json.loads((HERE / "papers.json").read_text())["papers"].items()}


def arms_of(key, rt):
    """oracle has its own answer only where top1's paper is not the question's (elsewhere it is top1's prompt)."""
    return [a for a in ARMS if a != "oracle" or not rt[key]["routed_right"]]


def slots(key, rt):
    arms = arms_of(key, rt)
    random.Random(f"big-library:{key}").shuffle(arms)
    return [(chr(ord("A") + i), a) for i, a in enumerate(arms)]


def path(arm, key):
    s, paper, pid = key.split("/")
    return HERE / "answers" / f"{arm}-r1" / f"{s}__{paper}-{pid}.json"


def record(arm, key):
    f = path(arm, key)
    return json.loads(f.read_text()) if f.exists() else None


def sheet():
    grades, only, limit, n, T, rt = _load(GRADES), _arg("--set"), _arg("--limit", 10_000, int), 0, titles(), routes()
    for key, q in questions().items():
        if only and q["set"] != only:
            continue
        sl = slots(key, rt)
        recs = {L: record(a, key) for L, a in sl}
        todo = [L for L, _ in sl if L not in grades.get(key, {})]
        if not todo or any(v is None for v in recs.values()):
            continue
        r = rt[key]
        ranked = "; ".join(f"{i + 1}. {T[d][:70]}{' (its own)' if d == r['target'] else ''}"
                           for i, d in enumerate(r["paper_order"][:2]))
        print(f"######## {key}  [{q['cat']}]  paper: {T[r['target']]}\nsearch ranked: {ranked}\n"
              f"Q: {q['q']}\nE: {q['expect']}\nT: {q.get('trap') or '-'}")
        for L in todo:
            print(f"--- {L}\n{blind.shown(recs[L]['rendered'] or '(empty)')}")
        print()
        n += 1
        if n >= limit:
            break
    print(f"{n} question(s) shown")


def record_grades():
    grades, key, n, keys, rt = _load(GRADES), None, 0, questions(), routes()
    for line in sys.stdin.read().splitlines():
        if not line.strip():
            continue
        if line.startswith("## "):
            key = line[3:].strip()
            assert key in keys, key
            continue
        letter, v, *note = line.split(maxsplit=2)
        assert key and letter in {L for L, _ in slots(key, rt)} and v in FULL, line
        grades.setdefault(key, {})[letter] = {"verdict": FULL[v], "note": note[0] if note else ""}
        n += 1
    GRADES.write_text(json.dumps(grades, indent=1, ensure_ascii=False) + "\n")
    print(f"{n} grades recorded")


def progress():
    grades, keys, rt = _load(GRADES), questions(), routes()
    have = sum(all(record(a, k) for a in arms_of(k, rt)) for k in keys)
    done = sum(len(grades.get(k, {})) == len(arms_of(k, rt)) for k in keys)
    print(f"{len(keys)} questions, {have} with every answer in, {done} fully graded")


def unseal():
    (HERE / "graded.sha256").write_text(f"{hashlib.sha256(GRADES.read_bytes()).hexdigest()}  grades.json\n")
    hand, rt = {}, routes()
    for key, g in _load(GRADES).items():
        for L, a in slots(key, rt):
            if L in g:
                hand[f"{a}/{key}"] = {"verdict": g[L]["verdict"], "note": f"{g[L]['note']} {SIGN}".strip()}
    HAND.write_text(json.dumps(hand, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(hand)} grades unsealed to hand.json; grades.json hashed in graded.sha256")


def report():
    hand, qs, rt = _load(HAND), questions(), routes()
    keys = [k for k in qs if all(f"{a}/{k}" in hand for a in arms_of(k, rt))]
    if not keys:
        raise SystemExit("nothing unsealed yet")

    def right(arm, k):
        if arm == "oracle" and rt[k]["routed_right"]:
            arm = "top1"                     # the same prompt, byte for byte
        return int(hand[f"{arm}/{k}"]["verdict"] == "correct")

    R = {a: {k: right(a, k) for k in keys} for a in ARMS}
    print(f"== {len(keys)} questions fully graded (one answer per arm; oracle = top1 where top1's paper is right)")
    for a in ("top1", "top2"):
        c = collections.Counter(hand[f"{a}/{k}"]["verdict"] for k in keys)
        print(f"{a:6} right {c['correct']:3}  partial {c['partial']:3}  wrong {c['wrong']:3}  of {len(keys)}")
    print(f"oracle right {sum(R['oracle'].values()):3} of {len(keys)}")
    print(G._pair(R["top1"], R["top2"], keys, "top1", "top2"))
    print(G._pair(R["top1"], R["oracle"], keys, "top1", "oracle"))
    print(G._pair(R["top2"], R["oracle"], keys, "top2", "oracle"))
    miss = [k for k in keys if not rt[k]["routed_right"]]
    print(f"misrouted ({len(miss)}): right top1 {sum(R['top1'][k] for k in miss)}, top2 {sum(R['top2'][k] for k in miss)}, "
          f"oracle {sum(R['oracle'][k] for k in miss)}; own paper among top 2 for {sum(rt[k]['target_rank'] <= 2 for k in miss)}")
    hit = [k for k in keys if rt[k]["routed_right"]]
    print(f"routed right ({len(hit)}): right top1 {sum(R['top1'][k] for k in hit)}, top2 {sum(R['top2'][k] for k in hit)}")
    for gname, group in (("set", lambda k: qs[k]["set"]), ("category", lambda k: qs[k]["cat"])):
        rows = collections.defaultdict(list)
        for k in keys:
            rows[group(k)].append(k)
        print(f"by {gname} (right: top1 / top2 / oracle; misrouted):")
        for g, ks in sorted(rows.items()):
            print(f"  {g:8} " + " / ".join(f"{sum(R[a][k] for k in ks):3}" for a in ARMS)
                  + f"  of {len(ks):3}; misrouted {sum(not rt[k]['routed_right'] for k in ks)}")
    routed = _load(ROOT / "experiments" / "routed" / "hand.json")
    ks = [k for k in keys if f"prose/{k}" in routed]
    if ks:
        old = {k: int(routed[f"prose/{k}"]["verdict"] == "correct") for k in ks}
        print("against the routed test's prose arm (10-paper libraries; graded in another session):")
        print("  " + G._pair(R["top1"], old, ks, "top1", "routed prose"))
    tags = collections.Counter((key.split("/")[0], t) for key, v in hand.items() for t in TAGS if t in v["note"])
    print("tags (all verdicts): " + ", ".join(f"{a} {t} {n}" for (a, t), n in sorted(tags.items())))
    for a in ("top1", "top2"):
        v = [((record(a, k) or {}).get("usage") or {}).get("prompt_tokens") for k in keys]
        v = [x for x in v if x]
        print(f"mean prompt tokens {a}: {sum(v) / max(1, len(v)):,.0f}")


if __name__ == "__main__":
    {"sheet": sheet, "record": record_grades, "progress": progress, "unseal": unseal, "report": report}[sys.argv[1]]()
