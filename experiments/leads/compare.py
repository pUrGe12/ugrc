"""Haiku in the question loop, three ways: plain (answers-haiku), with the clause base attached (answers-haiku-routed),
and with leads sent with each question and measure runs (answers-haiku-leads).

    python experiments/leads/compare.py

Same 71 questions in each: the 60 probes of experiments/claude-capability and the professor's 11 of
experiments/prof-rag. Grades: experiments/whole-pdf/grades-haiku.json ("ugrc"), grades-haiku-routed.json, and
grades-haiku-leads.json here, all by the same rubric (correct / partial / wrong, with a note).
"""
import collections
import json
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRICE = (0.10, 0.125, 0.01, 0.50)      # Haiku 5.5 $/M under 100K: input, cache write, cache read, output
KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
ARMS = {"plain": ("answers-haiku", ROOT / "experiments/whole-pdf/grades-haiku.json", "ugrc"),
        "clause base attached": ("answers-haiku-routed", ROOT / "experiments/whole-pdf/grades-haiku-routed.json", None),
        "leads + measure runs": ("answers-haiku-leads", HERE / "grades-haiku-leads.json", None)}


def records(folder):
    out = {}
    for f in sorted((ROOT / "experiments/claude-capability" / folder).glob("*.json")):
        out[f.stem] = json.loads(f.read_text())
    for f in sorted((ROOT / "experiments/prof-rag" / folder).glob("*.json")):
        out["prof-" + f.stem] = json.loads(f.read_text())
    return out


def grades(path, key):
    if not path.exists():
        return {}
    g = json.loads(path.read_text())
    return g[key] if key else g


def main():
    print(f"{'':22} {'n':>3} {'right':>5} {'part':>4} {'wrong':>5} | {'refused':>7} {'tools':>5} {'turns':>5} "
          f"{'max':>3} | {'cost':>6} | {'measure runs':>12} {'answers using them':>18}")
    per = {}
    for arm, (folder, gpath, key) in ARMS.items():
        recs, g = records(folder), grades(gpath, key)
        per[arm] = (recs, g)
        v = collections.Counter(g[k]["verdict"] for k in recs if k in g)
        refused = sum(len(r["door_refusals"]) for r in recs.values())
        tools = st.median(r["tool_calls"] for r in recs.values())
        turns = [r["turns"] for r in recs.values()]
        cost = sum(sum(r["usage"].get(k, 0) * p for k, p in zip(KEYS, PRICE)) / 1e6 for r in recs.values())
        mruns = [sum(1 for x in r.get("runs") or [] if isinstance(x, dict) and "measure" in x) for r in recs.values()]
        print(f"{arm:22} {len(recs):>3} {v['correct']:>5} {v['partial']:>4} {v['wrong']:>5} | {refused:>7} {tools:>5} "
              f"{st.median(turns):>5} {max(turns):>3} | ${cost:>5.2f} | {sum(mruns):>12} {sum(1 for m in mruns if m):>18}")
    recs, _ = per["leads + measure runs"]
    rules = collections.Counter(x["rule"] for r in recs.values() for rnd in r["door_refusals"] for x in rnd)
    print("\nrefusal rules, leads arm:", dict(rules.most_common()))
    plain = collections.Counter(x["rule"] for r in per["plain"][0].values() for rnd in r["door_refusals"] for x in rnd)
    print("refusal rules, plain arm:", dict(plain.most_common()))
    no_search = sum(1 for r in recs.values() if not any(t["tool"] in ("sql", "view_figure") for t in r["trace"]))
    print(f"leads-arm answers that never searched (answered from the leads alone): {no_search} of {len(recs)}")
    g0, g1, g2 = (per[a][1] for a in ARMS)
    changed = [(k, g0.get(k, {}).get("verdict"), g1.get(k, {}).get("verdict"), g2[k]["verdict"], g2[k].get("note"))
               for k in sorted(g2) if len({g0.get(k, {}).get("verdict"), g1.get(k, {}).get("verdict"), g2[k]["verdict"]}) > 1]
    if changed:
        print("\nquestions graded differently across the arms (plain, attached, leads):")
        for k, a, b, c, note in changed:
            print(f"  {k:9} {a:8} {b:8} {c:8} {note or ''}")


if __name__ == "__main__":
    main()
