"""Grade the Haiku and Llama arms on both frozen probe sets.

    python experiments/bench-llama/grade.py sheet     the hand-review sheet: every answer the check does not pass,
                                                      and a seeded 15% sample of the ones it does
    python experiments/bench-llama/grade.py report    the tables
    python experiments/bench-llama/grade.py modes     how the answers went: refusals by rule, absence claims and
                                                      their terms, unread queries, the adapter's decodings

The automatic check is experiments/bench-leads/grade.py's (every `must` group present, numbers whole, no
`must_not`), against each probe's own key. A question with no accepted answer within the turn cap counts as
"no answer". hand.json ({"<arm>-r<k>/<bench>/<paper>-<id>": {"verdict", "note"}}) overrides the check.
"""
import collections
import json
import random
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "bench-leads"))
sys.path.insert(0, str(ROOT))
from grade import check, sign_test  # noqa: E402
from ugrc.answer import lead_in_gaps  # noqa: E402

BENCHES = ("bench-leads", "bench-multistep")
SAMPLE = 0.15


def load():
    probes = {}
    for b in BENCHES:
        for paper, ps in json.loads((ROOT / "experiments" / b / "probes.json").read_text())["papers"].items():
            for p in ps:
                probes[(b, paper, p["id"])] = p
    recs, errs = {}, {}
    for f in sorted((HERE / "answers").glob("*/*/*.json")):
        key = f"{f.parent.parent.name}/{f.parent.name}/{f.name.removesuffix('.error.json').removesuffix('.json')}"
        (errs if f.name.endswith(".error.json") else recs)[key] = json.loads(f.read_text())
    hand = json.loads((HERE / "hand.json").read_text()) if (HERE / "hand.json").exists() else {}
    for b in BENCHES:
        d = ROOT / "experiments" / b
        theirs = json.loads((d / "hand.json").read_text()) if (d / "hand.json").exists() else {}
        for f in sorted((d / "answers").glob("plain-r*/*.json")):
            key = f"haiku-earlier-{f.parent.name.removeprefix('plain-')}/{b}/{f.stem}"
            recs[key] = dict(json.loads(f.read_text()), bench=b)
            if f"{f.parent.name}/{f.stem}" in theirs:
                hand.setdefault(key, theirs[f"{f.parent.name}/{f.stem}"])
    return probes, recs, errs, hand


def verdicts(probes, recs, errs, hand):
    out = {}
    for key, r in recs.items():
        ok, why = check(r, probes[(r["bench"], r["paper"], r["probe"])])
        out[key] = (hand[key]["verdict"], "hand") if key in hand else ("correct" if ok else "unreviewed", "check")
    for key in errs:
        out[key] = ("no answer", "loop")
    return out


def sheet():
    probes, recs, errs, hand = load()
    rng = random.Random(20261020)
    rows = []
    for key, r in sorted(recs.items()):
        if key in hand or key.startswith("haiku-earlier"):
            continue
        p = probes[(r["bench"], r["paper"], r["probe"])]
        ok, why = check(r, p)
        if ok and rng.random() >= SAMPLE:
            continue
        rows.append(f"### {key}  [{'check passes (sample)' if ok else 'check: ' + str(why)}] turns={r['turns']} "
                    f"tools={r['tool_calls']} refused={len(r['door_refusals'])}\nQ: {p['q']}\nEXPECT: {p['expect']}\n"
                    f"TRAP: {p.get('trap')}\nANSWER: {r['rendered']}\n")
    print(f"{len(rows)} to review\n")
    print("\n".join(rows))


def report():
    probes, recs, errs, hand = load()
    v = verdicts(probes, recs, errs, hand)
    arms = sorted({k.split("/")[0] for k in v})
    print(f"{len(recs)} answers, {len(errs)} with no accepted answer; {sum(1 for x in v.values() if x[1] == 'hand')} hand-graded; "
          f"{sum(1 for x in v.values() if x[0] == 'unreviewed')} not yet reviewed\n")
    print(f"{'arm':16} {'bench':16} {'n':>3} {'right':>5} {'part':>4} {'wrong':>5} {'none':>4} {'open':>4} | "
          f"{'turns':>5} {'tools':>5} {'refused':>7} {'gaps':>4} {'min/q':>6}")
    for arm in arms:
        for b in BENCHES:
            keys = [k for k in v if k.startswith(f"{arm}/{b}/")]
            if not keys:
                continue
            c = collections.Counter(v[k][0] for k in keys)
            rs = [recs[k] for k in keys if k in recs]
            secs = [r.get("seconds") for r in rs if r.get("seconds")] + [errs[k].get("seconds") for k in keys if k in errs]
            gaps = sum(1 for r in rs if lead_in_gaps(r["rendered"], r["citations"]))
            print(f"{arm:16} {b:16} {len(keys):>3} {c['correct']:>5} {c['partial']:>4} {c['wrong']:>5} {c['no answer']:>4} "
                  f"{c['unreviewed']:>4} | {st.median([r['turns'] for r in rs]) if rs else 0:>5} "
                  f"{st.median([r['tool_calls'] for r in rs]) if rs else 0:>5} {sum(len(r['door_refusals']) for r in rs):>7} "
                  f"{gaps:>4} {st.median(secs) / 60 if secs else 0:>6.1f}")
    # the two comparisons asked for: Haiku vs Llama without Jev, and Haiku alone vs Llama with Jev; then what Jev
    # adds to each model, and the two models with Jev
    pairs = [(h, l) for h in ("haiku-plain-r1", "haiku-earlier-r1") for l in ("llama-plain-r1", "llama-leads-r1")]
    for a, b in pairs + [("llama-plain-r1", "llama-leads-r1"), ("haiku-plain-r1", "haiku-leads-r1"),
                         ("haiku-leads-r1", "llama-leads-r1"),
                         # the short prompt: what it does to each Llama arm, and Jev's effect under it
                         ("llama-plain-r1", "llama-plain-sp-r1"), ("llama-leads-r1", "llama-leads-sp-r1"),
                         ("llama-plain-sp-r1", "llama-leads-sp-r1"), ("haiku-plain-r1", "llama-leads-sp-r1"),
                         # no ugrc at all: the PDF's text in the prompt, one reply (direct.py)
                         ("llama-direct-r1", "llama-leads-sp-r1"), ("llama-direct-r1", "llama-plain-sp-r1"),
                         ("haiku-plain-r1", "llama-direct-r1"),
                         # the hybrid (bench-cross/hybrid.py): code and Jev's leads pick pages, Llama answers, code points
                         ("llama-direct-r1", "llama-hybrid-r1"), ("llama-leads-sp-r1", "llama-hybrid-r1"),
                         # the length test, and ugrc + Jev on the 10-paper corpus
                         ("llama-direct-r1", "llama-direct-ctx120k-r1"), ("llama-direct-ctx120k-r1", "llama-corpus-leads-sp-r1"),
                         ("llama-leads-sp-r1", "llama-corpus-leads-sp-r1")]:
        if not any(k.startswith(a + "/") for k in v) or not any(k.startswith(b + "/") for k in v):
            continue
        wins = losses = ties = 0
        for (bench, paper, pid) in probes:
            ka, kb = f"{a}/{bench}/{paper}-{pid}", f"{b}/{bench}/{paper}-{pid}"
            if ka not in v or kb not in v:
                continue
            ca, cb = v[ka][0] == "correct", v[kb][0] == "correct"
            wins += cb and not ca
            losses += ca and not cb
            ties += ca == cb
        print(f"\n{b} vs {a}, per question: {b} right where {a} is not on {wins}, the reverse on {losses}, "
              f"same on {ties} (sign test p = {sign_test(wins, losses):.3f})")


def _words(t):
    import re
    return len(re.findall(r"[^\W_]+", t))


def modes():
    probes, recs, errs, hand = load()
    arms = sorted({k.split("/")[0] for k in list(recs) + list(errs)})
    for arm in arms:
        rs = {k: r for k, r in recs.items() if k.startswith(arm + "/")}
        es = {k: r for k, r in errs.items() if k.startswith(arm + "/")}
        rules = collections.Counter(x["rule"] for r in list(rs.values()) + list(es.values())
                                    for sub in r.get("door_refusals") or [] for x in sub)
        absent = [k for k, r in rs.items() if any(run.get("absent") for run in r.get("runs") or [])]
        long_terms = [k for k, r in rs.items() if any(_words(t) >= 4 for run in r.get("runs") or []
                                                      for t in run.get("absent") or [])]
        no_look = [k for k, r in rs.items() if not any(s["tool"] in ("sql", "view_figure") for s in r.get("trace") or [])]
        repairs = collections.Counter("host bug: " + x[5:] if x.startswith("host:") else "array sent as a string"
                                      if "." in x else x for r in rs.values() for x in r.get("adapter_repairs") or [])
        kinds = collections.Counter(e["error"].split(":")[0] + (" (turn cap)" if "model turns" in e["error"] else "")
                                    for e in es.values())
        print(f"{arm}: {len(rs)} accepted, {len(es)} with none ({dict(kinds)})")
        print(f"  accepted with an absence claim: {len(absent)}; of them, with a term of 4+ words: {len(long_terms)}")
        print(f"  accepted without one query or figure looked at: {len(no_look)}")
        print(f"  adapter repairs: {dict(repairs)}")
        print(f"  refusals by rule: {dict(rules.most_common(12))}")
        if long_terms:
            for k in long_terms[:8]:
                terms = [t for run in rs[k]["runs"] for t in run.get("absent") or []]
                print(f"    {k}: {terms[:3]}")


if __name__ == "__main__":
    {"sheet": sheet, "report": report, "modes": modes}[sys.argv[1] if len(sys.argv) > 1 else "report"]()
