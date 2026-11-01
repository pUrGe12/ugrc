"""Blind grading of the short-question answers (ANSWER.md): for each changed question, the long-form answer (big-library
top1), the short-form answer and, where search misroutes the short form, the short form on its own paper, under letters
shuffled by a fixed seed; which arm a letter is stays in code until `unseal`.

    python experiments/short-route/grade.py sheet [--set S] [--limit N]   questions whose answers are all in, not graded
    python experiments/short-route/grade.py record < grades.txt           '## <key>' then '<letter> c|p|w <note>'
    python experiments/short-route/grade.py progress
    python experiments/short-route/grade.py unseal                        grades.json -> hand.json (hashed first)
    python experiments/short-route/grade.py report                        the comparisons ANSWER.md names

Rules: ../big-library/GRADING.md, ../big-library/GRADING-settled.md and GRADING.md here (Q1-Q2).
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
BIG = ROOT / "experiments" / "big-library"
_spec = importlib.util.spec_from_file_location("big_grade", BIG / "grade.py")
BG = importlib.util.module_from_spec(_spec)
sys.modules["big_grade"] = BG
_spec.loader.exec_module(BG)
G, blind = BG.G, BG.blind

ARMS = ("long", "short", "short-oracle")
GRADES = HERE / "grades.json"
HAND = HERE / "hand.json"
SIGN = "(Claude, blind to arm)"
FULL = {"c": "correct", "p": "partial", "w": "wrong"}
TAGS = G.TAGS + ("[reading]",)


def _arg(name, default=None, cast=str):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def _load(p):
    return json.loads(p.read_text()) if p.exists() else {}


def rows():
    return json.loads((HERE / "routing.json").read_text())


def misrouted(r):
    return r["short"]["routed"] != r["target"]


def arms_of(key, rw):
    """Graded here: the changed questions only; short-oracle only where search sends the short form elsewhere."""
    r = rw[key]
    if r["unchanged"]:
        return []
    return [a for a in ARMS if a != "short-oracle" or misrouted(r)]


def slots(key, rw):
    arms = arms_of(key, rw)
    random.Random(f"short-route:{key}").shuffle(arms)
    return [(chr(ord("A") + i), a) for i, a in enumerate(arms)]


def record(arm, key):
    if arm == "long":
        return BG.record("top1", key)
    s, p, pid = key.split("/")
    f = HERE / "answers" / f"{arm}-r1" / f"{s}__{p}-{pid}.json"
    return json.loads(f.read_text()) if f.exists() else None


def sheet():
    grades, only, limit, n = _load(GRADES), _arg("--set"), _arg("--limit", 10_000, int), 0
    T, qs, rw = BG.titles(), BG.questions(), rows()
    short = json.loads((HERE / "short.json").read_text())["questions"]
    for key, q in qs.items():
        if only and q["set"] != only:
            continue
        sl = slots(key, rw)
        if not sl:
            continue
        recs = {L: record(a, key) for L, a in sl}
        todo = [L for L, _ in sl if L not in grades.get(key, {})]
        if not todo or any(v is None for v in recs.values()):
            continue
        target = rw[key]["target"]
        held = sorted({d for rec in recs.values() for d in rec["shown_papers"]})
        papers = "; ".join(f"{T[d][:70]}{' (its own)' if d == target else ''}" for d in held)
        print(f"######## {key}  [{q['cat']}]  paper: {T[target]}\nprompts held: {papers}\n"
              f"Q long:  {q['q']}\nQ short: {short[key]['short']}\nE: {q['expect']}\nT: {q.get('trap') or '-'}")
        for L in todo:
            print(f"--- {L}\n{blind.shown(recs[L]['rendered'] or '(empty)')}")
        print()
        n += 1
        if n >= limit:
            break
    print(f"{n} question(s) shown")


def record_grades():
    grades, key, n, rw = _load(GRADES), None, 0, rows()
    for line in sys.stdin.read().splitlines():
        if not line.strip():
            continue
        if line.startswith("## "):
            key = line[3:].strip()
            assert key in rw and arms_of(key, rw), key
            continue
        letter, v, *note = line.split(maxsplit=2)
        assert key and letter in {L for L, _ in slots(key, rw)} and v in FULL, line
        grades.setdefault(key, {})[letter] = {"verdict": FULL[v], "note": note[0] if note else ""}
        n += 1
    GRADES.write_text(json.dumps(grades, indent=1, ensure_ascii=False) + "\n")
    print(f"{n} grades recorded")


def progress():
    grades, rw = _load(GRADES), rows()
    keys = [k for k in rw if arms_of(k, rw)]
    have = sum(all(record(a, k) for a in arms_of(k, rw)) for k in keys)
    done = sum(len(grades.get(k, {})) == len(arms_of(k, rw)) for k in keys)
    print(f"{len(keys)} changed questions, {have} with every answer in, {done} fully graded")


def unseal():
    lines = [f"{hashlib.sha256(GRADES.read_bytes()).hexdigest()}  grades.json"]
    if (HERE / "GRADING-settled.md").exists():
        lines.append(f"{hashlib.sha256((HERE / 'GRADING-settled.md').read_bytes()).hexdigest()}  GRADING-settled.md")
    (HERE / "graded.sha256").write_text("\n".join(lines) + "\n")
    hand, rw = {}, rows()
    for key, g in _load(GRADES).items():
        for L, a in slots(key, rw):
            if L in g:
                hand[f"{a}/{key}"] = {"verdict": g[L]["verdict"], "note": f"{g[L]['note']} {SIGN}".strip()}
    HAND.write_text(json.dumps(hand, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(hand)} grades unsealed to hand.json; grades.json hashed in graded.sha256")


def report():
    hand, big, qs, rw = _load(HAND), _load(BG.HAND), BG.questions(), rows()
    bigrt = BG.routes()
    unsure = json.loads((HERE / "unsure.json").read_text())
    changed = [k for k in rw if arms_of(k, rw)]
    K = [k for k in changed if all(f"{a}/{k}" in hand for a in arms_of(k, rw))]
    if not K:
        raise SystemExit("nothing unsealed yet")

    def ok(v):
        return int(v["verdict"] == "correct")

    def right(arm, k):
        """Right (1/0) for any of the 388: graded here for changed questions, big-library grades for unchanged."""
        r = rw[k]
        if not r["unchanged"]:
            if arm == "short-oracle" and not misrouted(r):
                arm = "short"                                     # the same prompt
            return ok(hand[f"{arm}/{k}"])
        if arm == "short-oracle" and not bigrt[k]["routed_right"]:
            return ok(big[f"oracle/{k}"])
        return ok(big[f"top1/{k}"])

    R = {a: {k: right(a, k) for k in rw} for a in ARMS}
    print(f"== {len(K)} of {len(changed)} changed questions fully graded; {len(rw) - len(changed)} unchanged keep "
          "their big-library grades")
    for a in ARMS:
        ks = [k for k in K if f"{a}/{k}" in hand]
        c = collections.Counter(hand[f"{a}/{k}"]["verdict"] for k in ks)
        print(f"  {a:12} graded {len(ks):3}: right {c['correct']:3}  partial {c['partial']:3}  wrong {c['wrong']:3}")
    print("changed questions, right (short-oracle = short where search picks the right paper):")
    print("  " + "  ".join(f"{a} {sum(R[a][k] for k in K)}" for a in ARMS) + f"  of {len(K)}")
    print("  " + G._pair(R["short"], R["long"], K, "short", "long"))
    print("  " + G._pair(R["short-oracle"], R["long"], K, "short-oracle", "long") + "   (wording)")
    print("  " + G._pair(R["short"], R["short-oracle"], K, "short", "short-oracle") + "   (routing)")
    if len(K) == len(changed):
        print("all 388, right: " + "  ".join(f"{a} {sum(R[a].values())}" for a in ARMS)
              + f"   (big-library top1 304, oracle 304)")
    miss = [k for k in K if misrouted(rw[k])] + [k for k in rw if rw[k]["unchanged"] and misrouted(rw[k])]
    absent = [k for k in miss if qs[k]["cat"] == "A"]
    for name, ks in (("misrouted short questions", miss), ("  of them absence", absent),
                     ("  of them with an answer", [k for k in miss if k not in absent])):
        print(f"{name} ({len(ks)}): right " + "  ".join(f"{a} {sum(R[a][k] for k in ks)}" for a in ARMS))
    hit = [k for k in K if not misrouted(rw[k])]
    print(f"changed, routed right ({len(hit)}): right long {sum(R['long'][k] for k in hit)}, "
          f"short {sum(R['short'][k] for k in hit)}")
    lost = [k for k in K if R["long"][k] and not R["short"][k]]
    print(f"right long, not short ({len(lost)}): misrouted {sum(misrouted(rw[k]) for k in lost)}: "
          + " ".join(lost))
    won = [k for k in K if R["short"][k] and not R["long"][k]]
    print(f"right short, not long ({len(won)}): " + " ".join(won))
    same = sum(hand[f"long/{k}"]["verdict"] == big[f"top1/{k}"]["verdict"] for k in K)
    print(f"grader drift: the long answers' verdicts here equal the big-library ones for {same} of {len(K)}; right here "
          f"{sum(R['long'][k] for k in K)}, there {sum(ok(big[f'top1/{k}']) for k in K)}")
    for gname, group in (("set", lambda k: qs[k]["set"]), ("category", lambda k: qs[k]["cat"])):
        by = collections.defaultdict(list)
        for k in K:
            by[group(k)].append(k)
        print(f"by {gname}, changed questions (right: long / short / short-oracle; misrouted):")
        for g, ks in sorted(by.items()):
            print(f"  {g:10} " + " / ".join(f"{sum(R[a][k] for k in ks):3}" for a in ARMS)
                  + f"  of {len(ks):3}; misrouted {sum(misrouted(rw[k]) for k in ks)}")
    if len(K) == len(changed):
        print("post hoc, ask the user when search is unsure (flagged take short-oracle, the rest short), all 388:")
        for cut in (0.9, 0.85, 0.8):
            flag = {k for k in rw if unsure[k] >= cut}
            tot = sum(R["short-oracle"][k] if k in flag else R["short"][k] for k in rw)
            print(f"  cut-off {cut:4.2f}: asks {len(flag):3} times, right {tot}")
    tags = collections.Counter((key.split("/")[0], t) for key, v in hand.items() for t in TAGS if t in v["note"])
    print("tags (all verdicts): " + ", ".join(f"{a} {t} {n}" for (a, t), n in sorted(tags.items())))


if __name__ == "__main__":
    {"sheet": sheet, "record": record_grades, "progress": progress, "unseal": unseal, "report": report}[sys.argv[1]]()
