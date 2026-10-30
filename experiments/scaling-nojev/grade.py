"""Blind grading and the frozen test for the scaling-nojev plan (PLAN.md): three arms at the 10-paper library, one run,
each question's answers under letters A-C in a seeded order (bench-cross/jev-pick/blind.py's tools).

    python experiments/scaling-nojev/grade.py sheet [--paper P] [--limit N] | record | progress | unseal | report

unseal writes the two new arms into bench-llama/hand.json; the regrades of llama-scale-facts-L10 stay here.
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

ARMS = ("llama-scale-facts-L10", "llama-scale-code-L10", "llama-scale-pdf-L10")
NEW = ARMS[1:]
blind.HERE = HERE
blind.GRADES = HERE / "grades.json"
blind.STAGES = {1: ARMS}
blind.RUNS = (1,)
blind.SIGN = "(Claude, 2026-10-22, blind to arm)"
blind.questions = lambda stage: json.loads((ROOT / "experiments" / "scaling" / "questions.json").read_text())["stage1"]


def slots(key, stage):
    pairs = [(a, r) for a in ARMS for r in blind.RUNS]
    random.Random(f"scaling-nojev:{key}").shuffle(pairs)
    return [(chr(ord("A") + i), a, r) for i, (a, r) in enumerate(pairs)]


blind.slots = slots


def unseal(_stage=1):
    path = ROOT / "experiments" / "bench-llama" / "hand.json"
    hand = json.loads(path.read_text())
    n = 0
    for (a, r, key), v in blind.verdicts(1).items():
        if a in NEW:
            hand[f"{a}-r{r}/{key}"] = {"verdict": v["verdict"], "note": f"{v.get('note', '').rstrip()} {blind.SIGN}".strip()}
            n += 1
    path.write_text(json.dumps(hand, indent=1, ensure_ascii=False) + "\n")
    print(f"{n} hand grades written to {path.relative_to(ROOT)} (regrades of {ARMS[0]} kept in grades.json only)")


def report(_stage=1):
    v = blind.verdicts(1)
    qs = [k for k in blind.questions(1) if all((a, 1, k) in v for a in ARMS)]
    print(f"== scaling-nojev: {len(qs)} of {len(blind.questions(1))} questions fully graded")
    R = {a: {k: int(v[(a, 1, k)]["verdict"] == "correct") for k in qs} for a in ARMS}
    for a in ARMS:
        c = collections.Counter(v[(a, 1, k)]["verdict"] for k in qs)
        print(f"  {a:24} right {c['correct']:3}  partial {c['partial']:3}  wrong {c['wrong']:3}")

    def paired(name, x, y):
        d = [R[x][k] - R[y][k] for k in qs]
        m = sum(d) / len(d)
        sd = math.sqrt(sum((e - m) ** 2 for e in d) / (len(d) - 1))
        half = 1.96 * sd / math.sqrt(len(d)) * len(d)
        print(f"{name}: sum d = {sum(d):+d} ({sum(e > 0 for e in d)} better, {sum(e < 0 for e in d)} worse); "
              f"95% interval {sum(d) - half:+.1f} to {sum(d) + half:+.1f} answers; exact sign-flip p = {blind.exact_p(d):.4f}")

    paired("PRIMARY  facts (Jev's filter) vs code (no Jev)", ARMS[0], ARMS[1])
    paired("code (ugrc, no Jev) vs pdf (no ugrc)", ARMS[1], ARMS[2])
    paired("facts vs pdf", ARMS[0], ARMS[2])
    probes = {k: blind._probe(k) for k in qs}
    cats = sorted({probes[k]["cat"] for k in qs})
    print("right by category: " + "  ".join(f"{c}({sum(probes[k]['cat'] == c for k in qs)})" for c in cats))
    for a in ARMS:
        print(f"  {a:24} " + "  ".join(f"{c} {sum(R[a][k] for k in qs if probes[k]['cat'] == c):2}" for c in cats))
    hand = json.loads((ROOT / "experiments" / "bench-llama" / "hand.json").read_text())
    old = {k: hand[f"{ARMS[0]}-r1/{k}"]["verdict"] for k in qs}
    agree = sum(old[k] == v[(ARMS[0], 1, k)]["verdict"] for k in qs)
    print(f"regrade of {ARMS[0]}: same verdict on {agree} of {len(qs)}; right then {sum(x == 'correct' for x in old.values())}, "
          f"now {sum(R[ARMS[0]].values())}")
    for a in NEW:
        toks = sorted((blind.record(a, 1, k).get("usage") or {}).get("prompt_tokens", 0) for k in qs)
        print(f"  {a:24} median prompt tokens {toks[len(toks) // 2]:,}")
    tl = sum(hand.get(f"llama-scale-text-L10-r1/{k}", {}).get("verdict") == "correct" for k in qs)
    print(f"reference: llama-scale-text-L10 (PDF text, 7-9 papers) right {tl}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    {"sheet": blind.sheet, "progress": blind.progress, "unseal": unseal, "report": report,
     "record": blind.record_grades}[cmd](1)
