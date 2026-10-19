"""Print every answer of one arm beside its answer key, compactly, for grading by hand.

    python experiments/hallucination-paper2/review.py independent|session|long > review-<arm>.txt
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = json.loads((HERE / "probes.json").read_text())
key = {p["id"]: p for p in spec["probes"]} | {t["id"]: t for t in spec["long_tasks"]}
arm = sys.argv[1]
order = spec["session"] if arm == "session" else [p["id"] for p in spec["probes"]] if arm == "independent" \
    else [t["id"] for t in spec["long_tasks"]]

for pid in order:
    f = HERE / "answers" / f"{arm}-{pid}.json"
    k = key[pid]
    print("=" * 110)
    print(f"{pid} [{k.get('cat', 'long')}] {k['q']}")
    print(f"  EXPECT: {k['expect']}")
    print(f"  TRAP:   {k['trap']}")
    if not f.exists():
        print("  (no answer)")
        continue
    r = json.loads(f.read_text())
    print(f"  refused rounds: {[[x['rule'] for x in rnd] for rnd in r['door_refusals']]}")
    print("  ANSWER:\n    " + r["rendered"].replace("\n", "\n    "))
    for c in r["citations"]:
        if c["kind"] == "computed":
            print(f"    [{c['n']}] computed {c['rendered']} ({c['strength']}) from {[s['atom'] for s in c['sources'][:6]]}: {' '.join(c['sql'].split())[:160]}")
        elif c["kind"] == "search":
            print(f"    [{c['n']}] search {c['terms']} -> {c['matches']} matches")
        else:
            s = c["source"]
            text = (s.get("text") or s.get("caption") or "")[:150]
            q = c.get("quote")
            shown = f" quote={q!r}" if q else ""
            print(f"    [{c['n']}] {c['kind']} {s.get('atom')} ({c.get('strength')}){shown} :: {text!r}")
