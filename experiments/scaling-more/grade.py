"""Blind grading and the frozen test for the scaling-more plan (PLAN.md): four arms, one run, each question's answers
under letters A-D in a seeded order (bench-cross/jev-pick/blind.py's tools).

    python experiments/scaling-more/grade.py sheet [--paper P] [--limit N] | record | progress | unseal | report
"""
import collections
import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parents[0] / "bench-cross" / "jev-pick"))
import blind  # noqa: E402

ARMS = ("llama-more-facts-L20", "llama-more-facts-L40", "llama-more-pages-L40", "llama-more-factpages-L40")
blind.HERE = HERE
blind.GRADES = HERE / "grades.json"
blind.STAGES = {1: ARMS}
blind.RUNS = (1,)
blind.SIGN = "(Claude, 2026-10-22, blind to arm)"
blind.questions = lambda stage: json.loads((ROOT / "experiments" / "scaling" / "questions.json").read_text())["stage1"]


def slots(key, stage):
    pairs = [(a, r) for a in ARMS for r in blind.RUNS]
    random.Random(f"scaling-more:{key}").shuffle(pairs)
    return [(chr(ord("A") + i), a, r) for i, (a, r) in enumerate(pairs)]


blind.slots = slots


def report(_stage=1):
    v = blind.verdicts(1)
    qs = [k for k in blind.questions(1) if all((a, 1, k) in v for a in ARMS)]
    hand = json.loads((ROOT / "experiments" / "bench-llama" / "hand.json").read_text())
    print(f"== scaling-more: {len(qs)} of {len(blind.questions(1))} questions fully graded")
    R = {a: {k: int(v[(a, 1, k)]["verdict"] == "correct") for k in qs} for a in ARMS}
    R["llama-scale-facts-L10"] = {k: int(hand[f"llama-scale-facts-L10-r1/{k}"]["verdict"] == "correct") for k in qs}
    for a in ("llama-scale-facts-L10",) + ARMS:
        if a in ARMS:
            c = collections.Counter(v[(a, 1, k)]["verdict"] for k in qs)
            extra = f"partial {c['partial']:3}  wrong {c['wrong']:3}"
        else:
            extra = "(graded earlier, experiments/scaling)"
        print(f"  {a:26} right {sum(R[a].values()):3}  {extra}")

    def paired(name, x, y):
        d = [R[x][k] - R[y][k] for k in qs]
        m = sum(d) / len(d)
        sd = math.sqrt(sum((e - m) ** 2 for e in d) / (len(d) - 1))
        half = 1.96 * sd / math.sqrt(len(d)) * len(d)
        print(f"{name}: sum d = {sum(d):+d} ({sum(e > 0 for e in d)} better, {sum(e < 0 for e in d)} worse); "
              f"95% interval {sum(d) - half:+.1f} to {sum(d) + half:+.1f}; exact sign-flip p = {blind.exact_p(d):.4f}")

    paired("PRIMARY  factpages-L40 vs pages-L40", "llama-more-factpages-L40", "llama-more-pages-L40")
    paired("facts-L40 (all) vs factpages-L40", "llama-more-facts-L40", "llama-more-factpages-L40")
    paired("facts-L40 (all) vs pages-L40", "llama-more-facts-L40", "llama-more-pages-L40")
    paired("facts-L10 vs facts-L40 (L10 graded earlier)", "llama-scale-facts-L10", "llama-more-facts-L40")
    paired("facts-L10 vs facts-L20 (L10 graded earlier)", "llama-scale-facts-L10", "llama-more-facts-L20")
    probes = {k: blind._probe(k) for k in qs}
    cats = sorted({probes[k]["cat"] for k in qs})
    print("right by category: " + "  ".join(f"{c}({sum(probes[k]['cat'] == c for k in qs)})" for c in cats))
    for a in ("llama-scale-facts-L10",) + ARMS:
        print(f"  {a:26} " + "  ".join(f"{c} {sum(R[a][k] for k in qs if probes[k]['cat'] == c):2}" for c in cats))
    print("per arm: median prompt tokens; papers in library; questions whose own paper got at least one picked page "
          "(right when it did / when it did not)")
    for a in ARMS:
        recs = {k: blind.record(a, 1, k) for k in qs}
        toks = sorted((r.get("usage") or {}).get("prompt_tokens", 0) for r in recs.values())
        n = collections.Counter(len(r["library"]["documents"]) for r in recs.values())
        hit = [k for k, r in recs.items() if r["library"]["target_shown"]]
        miss = [k for k in qs if k not in hit]
        print(f"  {a:26} {toks[len(toks) // 2]:>8,}  {dict(n)}  own paper shown {len(hit)}/{len(qs)} "
              f"(right {sum(R[a][k] for k in hit)} / {sum(R[a][k] for k in miss)})")


if __name__ == "__main__":
    cmd = sys.argv[1]
    {"sheet": blind.sheet, "progress": blind.progress, "unseal": blind.unseal, "report": report,
     "record": blind.record_grades}[cmd](1)
