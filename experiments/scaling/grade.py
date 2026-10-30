"""Blind grading and the frozen test for the scaling plan (PLAN.md), with bench-cross/jev-pick/blind.py's tools
pointed at this directory: seven arms, one run, each question's answers under letters A-G in a seeded order.

    python experiments/scaling/grade.py sheet [--paper P] [--limit N] | record | progress | unseal | report

Grade notes: start with [label] under GRADING.md rule 3; add [leak] when the answer gives away its form.
"""
import collections
import json
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parents[0] / "bench-cross" / "jev-pick"))
import blind  # noqa: E402

ARMS = ("llama-scale-text-L1", "llama-scale-text-L3", "llama-scale-text-L10", "llama-scale-facts-L1",
        "llama-scale-facts-L3", "llama-scale-facts-L10", "llama-scale-readings-L10")
blind.HERE = HERE
blind.GRADES = HERE / "grades.json"
blind.STAGES = {1: ARMS}
blind.RUNS = (1,)
blind.SIGN = "(Claude, 2026-10-22, blind to arm)"


def slots(key, stage):
    pairs = [(a, r) for a in ARMS for r in blind.RUNS]
    random.Random(f"scaling:{key}").shuffle(pairs)
    return [(chr(ord("A") + i), a, r) for i, (a, r) in enumerate(pairs)]


blind.slots = slots


def _hand():
    return json.loads((ROOT / "experiments" / "bench-llama" / "hand.json").read_text())


def _rec(arm, key):
    return blind.record(arm, 1, key)


def report(_stage=1, label_ok=False):
    v = blind.verdicts(1)
    qs = [k for k in blind.questions(1) if all((a, 1, k) in v for a in ARMS)]
    print(f"== scaling: {len(qs)} of {len(blind.questions(1))} questions fully graded"
          + ("  (SENSITIVITY: [label] verdicts counted as correct)" if label_ok else ""))

    def right(a, k):
        g = v[(a, 1, k)]
        return int(g["verdict"] == "correct" or (label_ok and g.get("note", "").startswith("[label]")))

    R = {a: {k: right(a, k) for k in qs} for a in ARMS}
    print(f"{'arm':26} {'right':>5} {'partial':>7} {'wrong':>5}   of {len(qs)}")
    for a in ARMS:
        c = collections.Counter(v[(a, 1, k)]["verdict"] for k in qs)
        print(f"{a:26} {sum(R[a].values()):5} {c['partial']:7} {c['wrong']:5}")

    def paired(name, x, y):
        d = [R[x][k] - R[y][k] for k in qs]
        w, l = sum(e > 0 for e in d), sum(e < 0 for e in d)
        print(f"{name}: sum d = {sum(d):+d} ({w} better, {l} worse); exact sign-flip p = {blind.exact_p(d):.4f}")

    print()
    paired("PRIMARY  facts-L10 vs text-L10", "llama-scale-facts-L10", "llama-scale-text-L10")
    for lo, hi in (("L1", "L10"), ("L1", "L3")):
        s = [(R[f"llama-scale-facts-{lo}"][k] - R[f"llama-scale-facts-{hi}"][k])
             - (R[f"llama-scale-text-{lo}"][k] - R[f"llama-scale-text-{hi}"][k]) for k in qs]
        print(f"loss {lo}->{hi}, facts minus text: sum s = {sum(s):+d} (negative: facts lose less); "
              f"exact sign-flip p = {blind.exact_p(s):.4f}")
    paired("facts-L1 vs text-L1 (cost of condensing)", "llama-scale-facts-L1", "llama-scale-text-L1")
    paired("facts-L3 vs text-L3", "llama-scale-facts-L3", "llama-scale-text-L3")
    paired("readings-L10 vs facts-L10", "llama-scale-readings-L10", "llama-scale-facts-L10")

    probes = {k: blind._probe(k) for k in qs}
    cats = sorted({probes[k]["cat"] for k in qs})
    print("\nright by category: " + "  ".join(f"{c}({sum(probes[k]['cat'] == c for k in qs)})" for c in cats))
    for a in ARMS:
        print(f"  {a:26} " + "  ".join(f"{c} {sum(R[a][k] for k in qs if probes[k]['cat'] == c):2}" for c in cats))

    print("\nper arm: median prompt tokens, papers held, answers with numbers printed nowhere in the paper, leaks")
    for a in ARMS:
        recs = [_rec(a, k) for k in qs]
        toks = statistics.median((r.get("usage") or {}).get("prompt_tokens", 0) for r in recs)
        held = collections.Counter(len(r["library"]["documents"]) for r in recs)
        inv = sum(bool(r.get("numbers_not_in_paper")) for r in recs)
        leaks = sum("[leak]" in v[(a, 1, k)].get("note", "") for k in qs)
        print(f"  {a:26} {toks:>8,.0f}  {dict(sorted(held.items()))}  {inv:3}  {leaks:3}")

    hand = _hand()
    print("\nreference only (graded earlier, not blind with these):")
    for arm in ("llama-direct-r1", "llama-clauses-text-r1"):
        print(f"  {arm:30} right {sum(hand.get(f'{arm}/{k}', {}).get('verdict') == 'correct' for k in qs)} of {len(qs)}")
    bm = [k for k in qs if all(f"llama-hybrid-corpus-bm25-r{r}/{k}" in hand for r in (1, 2, 3))]
    per = [sum(hand[f"llama-hybrid-corpus-bm25-r{r}/{k}"]["verdict"] == "correct" for k in bm) for r in (1, 2, 3)]
    print(f"  llama-hybrid-corpus-bm25 r1-r3 on {len(bm)} of these: right per run {per}; on the same {len(bm)}: "
          + ", ".join(f"{a.removeprefix('llama-scale-')} {sum(R[a][k] for k in bm)}" for a in ARMS))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "report":
        report(label_ok="--label-ok" in sys.argv)
    else:
        {"sheet": blind.sheet, "progress": blind.progress, "unseal": blind.unseal,
         "record": blind.record_grades}[cmd](1)
