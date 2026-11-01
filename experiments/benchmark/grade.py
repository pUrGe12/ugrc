"""Blind grading of the benchmark (PLAN.md). Which arm, mode and run a letter is stays in code until `unseal`.

    python experiments/benchmark/grade.py sheet bench [--from KEY] [--limit N]   part 1: a question's 4 answers
    python experiments/benchmark/grade.py sheet conv [--limit N]                 part 2: a question's 24 answers
    python experiments/benchmark/grade.py record bench|conv < grades.txt         '## <key or n>' then '<letter> c|p|w <note>'
    python experiments/benchmark/grade.py progress
    python experiments/benchmark/grade.py unseal                                 grades -> hand.json (hashed first)
    python experiments/benchmark/grade.py report

Rules: GRADING.md. An answer with no text (a part 2 turn the context window refused) gets no letter and is not right.
"""
import collections
import hashlib
import importlib.util
import json
import random
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

ARMS = ("ours", "rag", "chunks", "pdf")
MODES = ("chat", "solo")
RUNS = (1, 2, 3)
FULL = FG.FULL
SIGN = "(Claude, blind to arm)"
GRADES = {"bench": HERE / "grades-bench.json", "conv": HERE / "grades-conv.json"}
HAND = HERE / "hand.json"
CONV = json.loads((HERE / "conversation.json").read_text())
LETTERS = [chr(ord("A") + i) for i in range(26)]


def _load(p):
    return json.loads(p.read_text()) if p.exists() else {}


def questions():
    return json.loads((HERE / "questions.json").read_text())["questions"]


def answer_file(part, arm, key, run=1):
    return HERE / "answers" / part / f"{arm}-r{run}" / (key.replace("/", "__") + ".json")


# ---------------------------------------------------------------- what each letter is

def bench_record(arm, key):
    f = answer_file("bench", arm, key)
    return json.loads(f.read_text()) if f.exists() else None


def conv_text(arm, mode, run, n):
    """The answer's text, '' for a turn with no answer, None when not yet run."""
    if mode == "solo":
        f = answer_file("solo", arm, f"q{n:02d}", run)
        return json.loads(f.read_text())["rendered"] if f.exists() else None
    f = answer_file("chat", arm, "conversation", run)
    if not f.exists():
        return None
    turns = {t["n"]: t for t in json.loads(f.read_text())["turns"]}
    return turns[n]["rendered"] if n in turns else ""


def slots(part, key):
    """[(letter, label)] for the answers that have text; label 'arm' (part 1) or 'arm/mode/run' (part 2)."""
    if part == "bench":
        labels = [a for a in ARMS if (bench_record(a, key) or {}).get("rendered", "").strip()]
    else:
        labels = [f"{a}/{m}/r{r}" for a in ARMS for m in MODES for r in RUNS
                  if (conv_text(a, m, r, int(key)) or "").strip()]
    random.Random(f"benchmark-{part}:{key}").shuffle(labels)
    return list(zip(LETTERS, labels))


def text_of(part, key, label):
    if part == "bench":
        return bench_record(label, key)["rendered"]
    a, m, r = label.split("/")
    return conv_text(a, m, int(r[1:]), int(key))


def all_in(part, key):
    if part == "bench":
        return all(bench_record(a, key) is not None for a in ARMS)
    return all(conv_text(a, m, r, int(key)) is not None for a in ARMS for m in MODES for r in RUNS)


def keys(part):
    return list(questions()) if part == "bench" else [str(q["n"]) for q in CONV["questions"]]


# ---------------------------------------------------------------- sheets and grades

def sheet(part):
    grades = _load(GRADES[part])
    start, limit, n = FG._arg("--from"), FG._arg("--limit", 10_000, int), 0
    T, qs = FG.titles(), questions()
    started = start is None
    for key in keys(part):
        started = started or key == start
        if not started or not all_in(part, key):
            continue
        todo = [(L, lab) for L, lab in slots(part, key) if L not in grades.get(key, {})]
        if not todo:
            continue
        if part == "bench":
            q = qs[key]
            tg = f"{q['set']}/{q['paper']}"
            ttl = T.get(tg, tg)
            print(f"######## {key}  [{q['cat']}]  paper: {ttl}\nQ: {q['q']}\nE: {q['expect']}\nT: {q.get('trap') or '-'}")
        else:
            q = CONV["questions"][int(key) - 1]
            print(f"######## {key}  [{q['cat']}]\nQ (alone): {q['solo']}\nQ (in the conversation): {q['chat']}\n"
                  f"E: {q['expect']}\nT: {q['trap']}")
        for L, lab in todo:
            print(f"--- {L}\n{blind.shown(text_of(part, key, lab) or '(empty)')}")
        print()
        n += 1
        if n >= limit:
            break
    print(f"{n} question(s) shown")


def record(part):
    grades, key, n = _load(GRADES[part]), None, 0
    valid = set(keys(part))
    for line in sys.stdin.read().splitlines():
        if not line.strip():
            continue
        if line.startswith("## "):
            key = line[3:].strip()
            assert key in valid, key
            continue
        letter, v, *note = line.split(maxsplit=2)
        assert key and letter in {L for L, _ in slots(part, key)} and v in FULL, line
        grades.setdefault(key, {})[letter] = {"verdict": FULL[v], "note": note[0] if note else ""}
        n += 1
    GRADES[part].write_text(json.dumps(grades, indent=1, ensure_ascii=False) + "\n")
    print(f"{n} grades recorded")


def progress():
    for part in ("bench", "conv"):
        grades, ks = _load(GRADES[part]), keys(part)
        have = [k for k in ks if all_in(part, k)]
        done = sum(len(grades.get(k, {})) == len(slots(part, k)) for k in have)
        print(f"{part}: {len(ks)} questions, {len(have)} with every answer in, {done} fully graded")


def unseal():
    lines = [f"{hashlib.sha256(GRADES[p].read_bytes()).hexdigest()}  {GRADES[p].name}" for p in GRADES]
    if (HERE / "GRADING-settled.md").exists():
        lines.append(f"{hashlib.sha256((HERE / 'GRADING-settled.md').read_bytes()).hexdigest()}  GRADING-settled.md")
    (HERE / "graded.sha256").write_text("\n".join(lines) + "\n")
    hand = {}
    for part in GRADES:
        for key, g in _load(GRADES[part]).items():
            for L, lab in slots(part, key):
                if L in g:
                    hand[f"{part}/{lab}/{key}"] = {"verdict": g[L]["verdict"], "note": f"{g[L]['note']} {SIGN}".strip()}
    HAND.write_text(json.dumps(hand, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(hand)} grades unsealed to hand.json; grades hashed in graded.sha256")


# ---------------------------------------------------------------- report

def verdict(hand, part, label, key):
    v = hand.get(f"{part}/{label}/{key}")
    return v["verdict"] if v else "no answer"


def report():
    hand, qs = _load(HAND), questions()
    if not hand:
        raise SystemExit("nothing unsealed yet")
    K = [k for k in qs if all_in("bench", k)]
    V = {a: {k: verdict(hand, "bench", a, k) for k in K} for a in ARMS}
    R = {a: {k: int(V[a][k] == "correct") for k in K} for a in ARMS}
    print(f"== part 1: {len(K)} questions over the 130-paper library")
    for a in ARMS:
        c = collections.Counter(V[a].values())
        recs = [bench_record(a, k) for k in K]
        tok = statistics.mean((r.get("usage") or {}).get("prompt_tokens", 0) for r in recs)
        print(f"  {a:6} right {c['correct']:3}  partial {c['partial']:3}  wrong {c['wrong']:3}  no answer "
              f"{c['no answer']:2}   prompt tokens mean {tok:,.0f}   "
              + "  ".join(f"{s} {sum(R[a][k] for k in K if qs[k]['source'] == s)}/"
                          f"{sum(qs[k]['source'] == s for k in K)}" for s in ("fresh", "big-library")))
    for b in ("rag", "chunks", "pdf"):
        print("  " + G._pair(R["ours"], R[b], K, "ours", b))
    print("  " + G._pair(R["chunks"], R["rag"], K, "chunks", "rag"))
    by = collections.defaultdict(list)
    for k in K:
        by[qs[k]["cat"]].append(k)
    print("  by category (right: " + " / ".join(ARMS) + "):")
    for c, ks in sorted(by.items()):
        print(f"    {c}  " + " / ".join(f"{sum(R[a][k] for k in ks):2}" for a in ARMS) + f"  of {len(ks)}")
    rag = [bench_record("rag", k) for k in K]
    held = [r for r in rag if r["target_shown"]]
    print(f"  rag prompts holding a chunk of the question's paper: {len(held)} of {len(K)}; right where held "
          f"{sum(R['rag'][r['key']] for r in held)}, where not {sum(R['rag'][r['key']] for r in rag if r not in held)}")
    tags = collections.Counter((key.split("/")[1], t) for key, v in hand.items() if key.startswith("bench/")
                               for t in G.TAGS if t in v["note"])
    print("  tags: " + ", ".join(f"{a} {t} {n}" for (a, t), n in sorted(tags.items())))

    print("== part 2: 16 questions on one paper; chat = in one conversation, solo = each alone; 3 runs each")
    ns = [str(q["n"]) for q in CONV["questions"]]
    for a in ARMS:
        line = []
        for m in MODES:
            per = [sum(verdict(hand, "conv", f"{a}/{m}/r{r}", n) == "correct" for n in ns) for r in RUNS]
            first = [sum(verdict(hand, "conv", f"{a}/{m}/r{r}", n) == "correct" for n in ns[:8]) for r in RUNS]
            last = [sum(verdict(hand, "conv", f"{a}/{m}/r{r}", n) == "correct" for n in ns[8:]) for r in RUNS]
            line.append(f"{m} {per} mean {statistics.mean(per):4.1f} (turns 1-8 {statistics.mean(first):.1f}, "
                        f"9-16 {statistics.mean(last):.1f})")
        d = [int(verdict(hand, "conv", f"{a}/chat/r{r}", n) == "correct")
             - int(verdict(hand, "conv", f"{a}/solo/r{r}", n) == "correct") for r in RUNS for n in ns]
        print(f"  {a:6} " + " | ".join(line) + f" | chat - solo {sum(d):+d} over 48, p = {blind.exact_p(d):.4f}")
    for a in ARMS:
        convs = [json.loads(answer_file("chat", a, "conversation", r).read_text()) for r in RUNS]
        last = [max(((t.get("usage") or {}).get("prompt_tokens", 0) for t in c["turns"]), default=0) for c in convs]
        errs = sum(1 for c in convs for t in c["turns"] if t.get("error"))
        after = collections.Counter()
        for r in RUNS:
            for i, n in enumerate(ns[1:], start=1):
                prev = verdict(hand, "conv", f"{a}/chat/r{r}", ns[i - 1]) == "correct"
                now = verdict(hand, "conv", f"{a}/chat/r{r}", n) == "correct"
                after[(prev, now)] += 1
        print(f"  {a:6} chat context at its largest turn: {last} tokens; turns refused for length {errs}; "
              f"after a right turn right {after[(True, True)]}/{after[(True, True)] + after[(True, False)]}, "
              f"after a wrong turn right {after[(False, True)]}/{after[(False, True)] + after[(False, False)]}")
    for n in ns:
        print(f"  q{int(n):2} [{CONV['questions'][int(n) - 1]['cat']}] " + "  ".join(
            f"{a} " + "/".join(str(sum(verdict(hand, 'conv', f'{a}/{m}/r{r}', n) == 'correct' for r in RUNS))
                               for m in MODES) for a in ARMS) + "   (chat/solo, of 3)")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd in ("sheet", "record"):
        {"sheet": sheet, "record": record}[cmd](sys.argv[2])
    else:
        {"progress": progress, "unseal": unseal, "report": report}[cmd]()
