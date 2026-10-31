"""Blind grading of the library test (PLAN.md): each question's 3 answers (facts, prose, pages; one run) under letters
shuffled by a fixed seed; which arm a letter is stays in code until `unseal`.

    python experiments/library/grade.py sheet [--library L1] [--limit N]   questions whose answers are all in, not graded
    python experiments/library/grade.py record < grades.txt                '## <key>' then '<letter> c|p|w <note>'
    python experiments/library/grade.py progress
    python experiments/library/grade.py unseal                             grades.json -> hand.json (hashed first)
    python experiments/library/grade.py report                             the comparisons PLAN.md names

Rules: ../cheme/GRADING.md (1-23), ../prose/GRADING.md (24-25), ../cheme2/GRADING.md (26-29), GRADING.md here (L1-L5).
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

ARMS = ("facts", "prose", "pages")
GRADES = HERE / "grades.json"
HAND = HERE / "hand.json"
SIGN = "(Claude, 2026-10-31, blind to arm)"
FULL = {"c": "correct", "p": "partial", "w": "wrong"}
TAGS = ("[paper]", "[name]", "[miss]", "[label]", "[hedge]", "[render]")


def _arg(name, default=None, cast=str):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def _load(p):
    return json.loads(p.read_text()) if p.exists() else {}


def questions():
    return json.loads((HERE / "questions.json").read_text())["questions"]


def titles():
    import html
    import re
    out = {}
    for s in ("cheme", "cheme2"):
        for k, v in json.loads((ROOT / "experiments" / s / "papers.json").read_text()).items():
            out[f"{s}/{k}"] = re.sub(r"<[^>]+>", "", html.unescape(v["title"])).rstrip(".")
    return out


def slots(key):
    arms = list(ARMS)
    random.Random(f"library:{key}").shuffle(arms)
    return [(chr(ord("A") + i), a) for i, a in enumerate(arms)]


def path(arm, key):
    s, paper, pid = key.split("/")
    return HERE / "answers" / f"{arm}-r1" / f"{s}__{paper}-{pid}.json"


def record(arm, key):
    f = path(arm, key)
    return json.loads(f.read_text()) if f.exists() else None


def sheet():
    grades, lib, limit, n, T = _load(GRADES), _arg("--library"), _arg("--limit", 10_000, int), 0, titles()
    for key, q in questions().items():
        if lib and q["library"] != lib:
            continue
        sl = slots(key)
        recs = {L: record(a, key) for L, a in sl}
        todo = [L for L, _ in sl if L not in grades.get(key, {})]
        if not todo or any(v is None for v in recs.values()):
            continue
        print(f"######## {key}  [{q['cat']}]  paper: {T[q['set'] + '/' + q['paper']]}\nQ: {q['q']}\n"
              f"E: {q['expect']}\nT: {q.get('trap') or '-'}")
        for L in todo:
            print(f"--- {L}\n{blind.shown(recs[L]['rendered'] or '(empty)')}")
        print()
        n += 1
        if n >= limit:
            break
    print(f"{n} question(s) shown")


def record_grades():
    grades, key, n, keys = _load(GRADES), None, 0, questions()
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
    grades, keys = _load(GRADES), questions()
    by = collections.Counter()
    for k, q in keys.items():
        have = all(record(a, k) for a in ARMS)
        done = len(grades.get(k, {})) == len(ARMS)
        by[(q["library"], "in")] += have
        by[(q["library"], "graded")] += done
        by[(q["library"], "all")] += 1
    for lib in sorted({q["library"] for q in keys.values()}):
        print(f"{lib}: {by[(lib, 'all')]} questions, {by[(lib, 'in')]} with every answer in, "
              f"{by[(lib, 'graded')]} fully graded")


def unseal():
    (HERE / "graded.sha256").write_text(f"{hashlib.sha256(GRADES.read_bytes()).hexdigest()}  grades.json\n")
    hand = {}
    for key, g in _load(GRADES).items():
        for L, a in slots(key):
            if L in g:
                hand[f"{a}/{key}"] = {"verdict": g[L]["verdict"], "note": f"{g[L]['note']} {SIGN}".strip()}
    HAND.write_text(json.dumps(hand, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(hand)} grades unsealed to hand.json; grades.json hashed in graded.sha256")


def _pair(da, db, qs, a, b):
    d = {k: da[k] - db[k] for k in qs}
    w, l = sum(x > 0 for x in d.values()), sum(x < 0 for x in d.values())
    return (f"{a} - {b}: {sum(d.values()):+d} over {len(qs)} questions ({w} better, {l} worse, {len(qs) - w - l} equal); "
            f"exact paired sign-flip p = {blind.exact_p(list(d.values())):.4f}")


def reference(keys, qs):
    """The same questions with one paper in view (original wording): mean right per run, from earlier grades."""
    src = {"cheme": {"prose": ("prose", "prose"), "facts": ("prose", "facts"), "pdf": ("cheme", "pdf")},
           "cheme2": {"prose": ("cheme2", "prose"), "facts": ("cheme2", "facts"), "pdf": ("cheme2", "pdf")}}
    hands = {d: _load(ROOT / "experiments" / d / "hand.json") for d in ("cheme", "prose", "cheme2")}
    out = {}
    for arm in ("prose", "facts", "pdf"):
        tot = 0
        for k in keys:
            q = qs[k]
            d, a = src[q["set"]][arm]
            tot += sum(hands[d].get(f"{a}-r{r}/{q['paper']}-{q['id']}", {}).get("verdict") == "correct" for r in (1, 2, 3))
        out[arm] = tot / 3
    return out


def report():
    hand, qs = _load(HAND), questions()
    keys = [k for k in qs if all(f"{a}/{k}" in hand for a in ARMS)]
    if not keys:
        raise SystemExit("nothing unsealed yet")
    right = {a: {k: int(hand[f"{a}/{k}"]["verdict"] == "correct") for k in keys} for a in ARMS}
    print(f"== {len(keys)} questions fully graded (one answer per arm)")
    for a in ARMS:
        c = collections.Counter(hand[f"{a}/{k}"]["verdict"] for k in keys)
        print(f"{a:6} right {c['correct']:3}  partial {c['partial']:3}  wrong {c['wrong']:3}  of {len(keys)}")
    for a, b in (("prose", "pages"), ("facts", "pages"), ("prose", "facts")):
        print(_pair(right[a], right[b], keys, a, b))
    ref = reference(keys, qs)
    print("one paper in view, same questions in their original wording (mean right per run): "
          + ", ".join(f"{a} {v:.1f}" for a, v in ref.items()))
    for gname, group in (("library", lambda k: qs[k]["library"]), ("category", lambda k: qs[k]["cat"]),
                         ("set", lambda k: qs[k]["set"])):
        rows = collections.defaultdict(list)
        for k in keys:
            rows[group(k)].append(k)
        print(f"by {gname} (right: facts / prose / pages):")
        for g, ks in sorted(rows.items()):
            line = " / ".join(f"{sum(right[a][k] for k in ks):3}" for a in ARMS)
            pp = _pair(right["prose"], right["pages"], ks, "prose", "pages").split(": ", 1)[1]
            print(f"  {g:8} {line}  of {len(ks):3}   prose - pages {pp}")
    tags = collections.Counter((key.split("/")[0], t) for key, v in hand.items() for t in TAGS if t in v["note"])
    print("tags (all verdicts): " + ", ".join(f"{a} {t} {n}" for (a, t), n in sorted(tags.items())))
    miss = collections.Counter()
    for a in ARMS:
        for k in keys:
            r = record(a, k)
            if r and not r["target_shown"]:
                miss[(a, hand[f"{a}/{k}"]["verdict"])] += 1
    print(f"answers whose prompt lacked the question's paper: {dict(miss) or 'none'}")
    toks = {a: [((record(a, k) or {}).get("usage") or {}).get("prompt_tokens") for k in keys] for a in ARMS}
    print("mean prompt tokens: " + ", ".join(f"{a} {sum(x for x in v if x) / max(1, len([x for x in v if x])):,.0f}"
                                             for a, v in toks.items()))


if __name__ == "__main__":
    {"sheet": sheet, "record": record_grades, "progress": progress, "unseal": unseal, "report": report}[sys.argv[1]]()
