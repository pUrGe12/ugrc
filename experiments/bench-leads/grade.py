"""Grade the bench answers: an automatic check against each probe's key, hand grades for the rest, format gaps.

    python experiments/bench-leads/grade.py sheet     the hand-review sheet: every answer the check does not pass,
                                                      and a seeded 15% sample of the ones it does
    python experiments/bench-leads/grade.py report    the tables, from the check and hand.json

The check passes an answer when every `must` group of its probe occurs in the rendered answer (numbers whole:
"14" does not match "0.14" or "145") and no `must_not` string does. A hand grade in hand.json
({"<arm>-r<k>/<paper>-<id>": {"verdict": "correct|partial|wrong", "note": ...}}) overrides the check.
Format gaps are counted by gaps.py and reported apart from correctness.
"""
import collections
import json
import math
import random
import re
import statistics as st
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from gaps import gaps  # noqa: E402

PRICE = (0.10, 0.125, 0.01, 0.50)      # Haiku 5.5 $/M under 100K: input, cache write, cache read, output
KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
NEG = ("not report", "not given", "not give", "does not", "do not", "did not", "doesn't", "no ", "not state",
       "not specif", "not mention", "not provide", "not include", "not found", "not appear", "absent", "never",
       "none", "nowhere", "not list", "not tested", "not measured", "not perform", "not discuss", "not contain")
SAMPLE = 0.15


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).casefold()
    s = re.sub(r"[−–—‐‑]", "-", s)
    s = re.sub(r"\s*\^\s*", "^", s)
    return " ".join(s.split())


def has(text: str, needle: str) -> bool:
    n = norm(needle)
    if needle == "NEG":
        return any(norm(x) in text for x in NEG)
    pat = re.escape(n)
    if n[:1].isdigit():
        pat = r"(?<![\d.])" + pat
    if n[-1:].isdigit():
        pat += r"(?!\.?\d)"
    return re.search(pat, text) is not None


def check(rec: dict, probe: dict) -> tuple[bool, list]:
    text = norm(rec.get("rendered") or "")
    missing = [g for g in probe["must"] if not any(has(text, alt) for alt in g)]
    present = [x for x in probe.get("must_not") or [] if has(text, x)]
    return (not missing and not present), missing + present


def load():
    probes = {(paper, p["id"]): p for paper, ps in json.loads((HERE / "probes.json").read_text())["papers"].items()
              for p in ps}
    recs = {}
    for f in sorted((HERE / "answers").glob("*/*.json")):
        r = json.loads(f.read_text())
        recs[f"{f.parent.name}/{f.stem}"] = r
    hand = json.loads((HERE / "hand.json").read_text()) if (HERE / "hand.json").exists() else {}
    return probes, recs, hand


def verdicts(probes, recs, hand):
    out = {}
    for key, r in recs.items():
        ok, why = check(r, probes[(r["paper"], r["probe"])])
        if key in hand:
            out[key] = (hand[key]["verdict"], "hand", hand[key].get("note"))
        else:
            out[key] = ("correct" if ok else "unreviewed", "check", None if ok else f"check: missing/present {why}")
    return out


def sheet():
    probes, recs, hand = load()
    rng = random.Random(20261018)
    rows = []
    for key, r in sorted(recs.items()):
        if key in hand:
            continue
        ok, why = check(r, probes[(r["paper"], r["probe"])])
        if ok and rng.random() >= SAMPLE:
            continue
        p = probes[(r["paper"], r["probe"])]
        rows.append(f"### {key}  [{'check passes (sample)' if ok else 'check: ' + str(why)}] tools={r['tool_calls']} "
                    f"refused={len(r['door_refusals'])} gaps={len(gaps(r))}\nQ: {p['q']}\nEXPECT: {p['expect']}\n"
                    f"TRAP: {p.get('trap')}\nANSWER: {r['rendered']}\n")
    print(f"{len(rows)} to review\n")
    print("\n".join(rows))


def sign_test(wins, losses):
    n = wins + losses
    if not n:
        return 1.0
    k = min(wins, losses)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def report():
    probes, recs, hand = load()
    v = verdicts(probes, recs, hand)
    arms = sorted({k.split("/")[0].rsplit("-r", 1)[0] for k in recs}, key=lambda a: (a != "plain", a))
    runs = sorted({int(k.split("/")[0].rsplit("-r", 1)[1]) for k in recs})
    print(f"{len(recs)} answers; {sum(1 for x in v.values() if x[1] == 'hand')} hand-graded; "
          f"{sum(1 for x in v.values() if x[0] == 'unreviewed')} not yet reviewed\n")
    print(f"{'arm':6} {'run':>3} {'n':>3} {'right':>5} {'part':>4} {'wrong':>5} {'open':>4} | {'gap answers':>11} "
          f"{'refused':>7} {'tools':>5} {'turns':>5} | {'cost':>6} | {'measure runs':>12}")
    for arm in arms:
        for k in runs:
            keys = [x for x in recs if x.startswith(f"{arm}-r{k}/")]
            c = collections.Counter(v[x][0] for x in keys)
            rs = [recs[x] for x in keys]
            g = sum(1 for r in rs if gaps(r))
            cost = sum(sum(r["usage"].get(kk, 0) * p for kk, p in zip(KEYS, PRICE)) / 1e6 for r in rs)
            m = sum(1 for r in rs for x in r.get("runs") or [] if isinstance(x, dict) and "measure" in x)
            print(f"{arm:6} {k:>3} {len(keys):>3} {c['correct']:>5} {c['partial']:>4} {c['wrong']:>5} "
                  f"{c['unreviewed']:>4} | {g:>11} {sum(len(r['door_refusals']) for r in rs):>7} "
                  f"{st.median(r['tool_calls'] for r in rs):>5} {st.median(r['turns'] for r in rs):>5} | "
                  f"${cost:>5.2f} | {m:>12}")
    # per probe: correct runs out of len(runs), arm against arm
    if len(arms) == 2:
        a, b = arms
        wins = losses = ties = 0
        per_cat = collections.defaultdict(lambda: [0, 0, 0])
        for (paper, pid), p in probes.items():
            ca = sum(v.get(f"{a}-r{k}/{paper}-{pid}", ("",))[0] == "correct" for k in runs)
            cb = sum(v.get(f"{b}-r{k}/{paper}-{pid}", ("",))[0] == "correct" for k in runs)
            d = (cb > ca) - (cb < ca)
            wins += d > 0
            losses += d < 0
            ties += d == 0
            per_cat[p["cat"]][0 if d > 0 else 1 if d < 0 else 2] += 1
        print(f"\nper probe, correct runs of {b} vs {a}: {b} better on {wins}, worse on {losses}, equal on {ties} "
              f"(sign test p = {sign_test(wins, losses):.2f})")
        print("  by category (better / worse / equal):", {c: tuple(x) for c, x in sorted(per_cat.items())})
        for arm in arms:
            byc = collections.defaultdict(lambda: [0, 0])
            for key, r in recs.items():
                if key.startswith(arm + "-"):
                    byc[r["cat"]][0] += v[key][0] == "correct"
                    byc[r["cat"]][1] += 1
            print(f"  {arm:6} correct by category:", {c: f"{x[0]}/{x[1]}" for c, x in sorted(byc.items())})


if __name__ == "__main__":
    {"sheet": sheet, "report": report}[sys.argv[1] if len(sys.argv) > 1 else "report"]()
