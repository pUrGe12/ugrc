"""Blind grading and the frozen test for the jev-pick plan (PLAN.md).

    python experiments/bench-cross/jev-pick/blind.py sheet [--stage 1] [--paper P] [--limit N]
        every question of the stage whose answers are all in and not yet graded: the question, its key and trap, the
        notes earlier graders wrote on the same question, then its answers under letters A, B, ... in an order
        shuffled by a fixed seed. Which arm and run a letter is stays in code: the sheet never shows it.
    python experiments/bench-cross/jev-pick/blind.py progress [--stage 1]
    python experiments/bench-cross/jev-pick/blind.py unseal [--stage 1]
        copies the blind grades into bench-llama/hand.json under each answer's own key
    python experiments/bench-cross/jev-pick/blind.py report [--stage 1]
        the frozen test (PLAN.md): per question d = right runs (leads) - right runs (other arm), the exact paired
        sign-flip test on the sum, and what PLAN.md lists as also reported

Grades go in grades.json: {"<bench>/<paper>-<id>": {"A": {"verdict": "correct|partial|wrong", "note": "..."}, ...}}.
"""
import collections
import importlib.util
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ANSWERS = ROOT / "experiments" / "bench-llama" / "answers"
GRADES = HERE / "grades.json"
STAGES = {1: ("llama-hybrid-corpus", "llama-hybrid-corpus-bm25"), 2: ("llama-hybrid-corpus", "llama-hybrid-corpus-text")}
RUNS = (1, 2, 3)
VERDICTS = ("correct", "partial", "wrong")
SIGN = "(Claude, 2026-10-21, blind to arm)"


def _arg(name, default=None, cast=str):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def questions(stage):
    return json.loads((HERE / "questions.json").read_text())[f"stage{stage}"]


def _load(path):
    return json.loads(path.read_text()) if path.exists() else {}


def slots(key, stage):
    """[(letter, arm, run)] for a question: its answers in the stage, in the seeded order the sheet shows them."""
    pairs = [(a, r) for a in STAGES[stage] for r in RUNS]
    random.Random(f"jev-pick:stage{stage}:{key}").shuffle(pairs)
    return [(chr(ord("A") + i), a, r) for i, (a, r) in enumerate(pairs)]


def record(arm, run, key):
    b, name = key.split("/")
    f = ANSWERS / f"{arm}-r{run}" / b / f"{name}.json"
    return json.loads(f.read_text()) if f.exists() else None


def _probe(key):
    sys.path.insert(0, str(ROOT / "experiments" / "bench-llama"))
    import run as bench
    for b, paper, p in bench.probes():
        if f"{b}/{paper}-{p['id']}" == key:
            return p
    raise KeyError(key)


def _earlier_notes(key):
    hand = _load(ROOT / "experiments" / "bench-llama" / "hand.json")
    out = []
    for arm in ("llama-hybrid-r1", "llama-direct-r1", "llama-hybrid-r2", "llama-hybrid-r3"):
        h = hand.get(f"{arm}/{key}")
        if h:
            out.append(f"  [{h['verdict']}] {h.get('note', '')}")
    return out


def shown(text, head=2500, tail=1000):
    """An answer as the sheet shows it: a run of 6 or more lines that are each a bare number (a model counting) is
    folded into one line saying so, and a very long answer keeps its start and its end."""
    lines, out, i = text.strip().splitlines(), [], 0
    while i < len(lines):
        j = i
        while j < len(lines) and lines[j].strip().isdigit():
            j += 1
        if j - i >= 6:
            out.append(f"[... {j - i} lines that are each a bare number, {lines[i].strip()} to {lines[j - 1].strip()} ...]")
            i = j
        else:
            out.append(lines[i])
            i += 1
    t = "\n".join(out)
    return t if len(t) <= head + tail else f"{t[:head]}\n[... {len(t) - head - tail} characters cut ...]\n{t[-tail:]}"


def record_grades(stage):
    """Grades from stdin: a line '## <key>', then lines '<letter> c|p|w <note>'."""
    grades, key, n = _load(GRADES), None, 0
    full = {"c": "correct", "p": "partial", "w": "wrong"}
    for line in sys.stdin.read().splitlines():
        if not line.strip():
            continue
        if line.startswith("## "):
            key = line[3:].strip()
            assert key in questions(stage), key
            continue
        letter, v, *note = line.split(maxsplit=2)
        assert key and letter in {L for L, _, _ in slots(key, stage)} and v in full, line
        grades.setdefault(key, {})[letter] = {"verdict": full[v], "note": note[0] if note else ""}
        n += 1
    GRADES.write_text(json.dumps(grades, indent=1, ensure_ascii=False) + "\n")
    print(f"{n} grades recorded")


def sheet(stage):
    grades, paper, limit, n = _load(GRADES), _arg("--paper"), _arg("--limit", 10_000, int), 0
    for key in questions(stage):
        if paper and key.split("/")[1].rsplit("-", 1)[0] != paper:
            continue
        sl = slots(key, stage)
        g = grades.get(key, {})
        todo = [(L, a, r) for L, a, r in sl if L not in g]
        recs = {L: record(a, r, key) for L, a, r in sl}
        if not todo or any(v is None for v in recs.values()):
            continue
        p = recs[sl[0][0]]
        print(f"######## {key}  [{p['cat']}]\nQ: {p['question']}\nE: {p['expect']}\nT: {p.get('trap') or '-'}")
        notes = _earlier_notes(key)
        if notes:
            print("Earlier grades of this question (other setups):\n" + "\n".join(notes))
        for L, _, _ in todo:
            print(f"--- {L}\n{shown(recs[L]['rendered'] or '(empty)')}")
        print()
        n += 1
        if n >= limit:
            break
    print(f"{n} question(s) shown")


def progress(stage):
    grades = _load(GRADES)
    qs = questions(stage)
    have = sum(all(record(a, r, k) for _, a, r in slots(k, stage)) for k in qs)
    done = sum(len([L for L, _, _ in slots(k, stage) if L in grades.get(k, {})]) == len(STAGES[stage]) * len(RUNS) for k in qs)
    print(f"stage {stage}: {len(qs)} questions, {have} with every answer in, {done} fully graded")


def verdicts(stage):
    """{(arm, run, key): verdict} from the blind grades."""
    grades, out = _load(GRADES), {}
    for key in questions(stage):
        for L, a, r in slots(key, stage):
            v = grades.get(key, {}).get(L)
            if v:
                assert v["verdict"] in VERDICTS, (key, L, v)
                out[(a, r, key)] = v
    return out


def unseal(stage):
    path = ROOT / "experiments" / "bench-llama" / "hand.json"
    hand = _load(path)
    n = 0
    for (a, r, key), v in verdicts(stage).items():
        k = f"{a}-r{r}/{key}"
        new = {"verdict": v["verdict"], "note": f"{v.get('note', '').rstrip()} {SIGN}".strip()}
        if hand.get(k) != new:
            hand[k] = new
            n += 1
    path.write_text(json.dumps(hand, indent=1, ensure_ascii=False) + "\n")
    print(f"{n} hand grades written to {path.relative_to(ROOT)}")


def exact_p(d):
    """Two-sided exact paired sign-flip test on sum(d): every assignment of signs to the nonzero |d|."""
    a = [abs(x) for x in d if x]
    dist = {0: 1}
    for x in a:
        nd = collections.Counter()
        for s, c in dist.items():
            nd[s + x] += c
            nd[s - x] += c
        dist = nd
    obs = abs(sum(d))
    return sum(c for s, c in dist.items() if abs(s) >= obs) / 2 ** len(a)


def _sign_test(w, l):
    spec = importlib.util.spec_from_file_location("leads_grade", ROOT / "experiments" / "bench-leads" / "grade.py")
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    return g.sign_test(w, l)


def report(stage):
    lead, other = STAGES[stage]
    v = verdicts(stage)
    qs = [k for k in questions(stage) if all((a, r, k) in v for a in STAGES[stage] for r in RUNS)]
    print(f"== stage {stage}: {lead} against {other}; {len(qs)} of {len(questions(stage))} questions fully graded")
    for arm in (lead, other):
        c = collections.Counter(v[(arm, r, k)]["verdict"] for k in qs for r in RUNS)
        per_run = [sum(v[(arm, r, k)]["verdict"] == "correct" for k in qs) for r in RUNS]
        print(f"{arm:28} right per run {per_run}  all runs: right {c['correct']} partial {c['partial']} wrong {c['wrong']} "
              f"of {len(qs) * len(RUNS)}")
    right = {arm: {k: sum(v[(arm, r, k)]["verdict"] == "correct" for r in RUNS) for k in qs} for arm in (lead, other)}
    d = {k: right[lead][k] - right[other][k] for k in qs}
    w, l = sum(x > 0 for x in d.values()), sum(x < 0 for x in d.values())
    print(f"PRIMARY: sum of d = {sum(d.values())} over {len(qs)} questions ({w} better with {lead}, {l} worse, "
          f"{len(qs) - w - l} equal); exact paired sign-flip test p = {exact_p(list(d.values())):.4f}")
    print(f"also: sign test on the {w + l} questions that differ, p = {_sign_test(w, l):.4f}")
    probes = {k: _probe(k) for k in qs}
    bycat = collections.defaultdict(list)
    for k in qs:
        bycat[probes[k]["cat"]].append(d[k])
    print("by category (sum of d, questions): " + ", ".join(f"{c} {sum(x)}/{len(x)}" for c, x in sorted(bycat.items())))
    bypaper = collections.defaultdict(list)
    for k in qs:
        bypaper[k.split("/")[1].rsplit("-", 1)[0]].append(d[k])
    print("by paper: " + ", ".join(f"{p} {sum(x)}/{len(x)}" for p, x in sorted(bypaper.items())))
    print("questions that differ: " + ", ".join(f"{k} {right[lead][k]}-{right[other][k]}" for k in qs if d[k]))
    if stage == 1 and HERE.name == "jev-pick":         # the pooled line belongs to the jev-pick plan only
        earlier = _earlier_differing()
        pooled = list(d.values()) + earlier
        print(f"also: pooled with the earlier test's {len(earlier)} questions whose pages differed (not fresh): sum "
              f"{sum(pooled)} over {len(pooled)}, p = {exact_p(pooled):.4f}")


def _earlier_differing():
    """d per question of the earlier leads-vs-BM25 test (llama-hybrid vs llama-hybrid-bm25, 61 questions), for the
    questions whose two arms were given different pages."""
    spec = importlib.util.spec_from_file_location("cross_grade", ROOT / "experiments" / "bench-cross" / "grade.py")
    g = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "experiments" / "bench-leads"))
    spec.loader.exec_module(g)
    out = []
    for _, _, _, got, _, _ in g._pick_items():
        a, b = got["llama-hybrid"], got["llama-hybrid-bm25"]
        if json.dumps(a[1][1]["pages"]) == json.dumps(b[1][1]["pages"]):
            continue
        out.append(sum(a[r][0] == "correct" for r in RUNS) - sum(b[r][0] == "correct" for r in RUNS))
    return out


if __name__ == "__main__":
    cmd, stage = sys.argv[1], _arg("--stage", 1, int)
    {"sheet": sheet, "progress": progress, "unseal": unseal, "report": report, "record": record_grades}[cmd](stage)
