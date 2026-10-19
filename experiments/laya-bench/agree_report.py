"""Summarise agree-<model>.jsonl: decision agreement with Jev by question kind, by Jev's confidence, truncation."""
import collections
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def qkind(kind, q):
    return f"{kind}:{re.sub(r'[0-9]+$', '', q.split('_')[0])}"


for model in sys.argv[1:]:
    recs = [json.loads(l) for l in (HERE / f"agree-{model}.jsonl").open()]
    by, conf, opts = (collections.defaultdict(lambda: [0, 0]) for _ in range(3))
    for r in recs:
        for q, v in r["questions"].items():
            ok = v["jev"] == v["laya"]
            for d, k in ((by, qkind(r["kind"], q)), (conf, "jev conf >= 0.8" if (v["jev_p"] or 0) >= 0.8 else "jev conf < 0.8"),
                         (opts, f"{min(v['n_opts'], 6)}{'+' if v['n_opts'] >= 6 else ''} options")):
                d[k][0] += ok
                d[k][1] += 1
    a = sum(x[0] for x in by.values()); n = sum(x[1] for x in by.values())
    secs = sorted(r["seconds"] for r in recs)
    print(f"== {model}: {len(recs)} requests, {n} questions; same decision as Jev {a}/{n} = {a/n:.3f}; "
          f"truncated requests {sum(1 for r in recs if r['truncated'])}; {secs[len(secs)//2]:.2f} s/call median, {sum(secs)/60:.1f} min total")
    for d in (by, conf, opts):
        for k, (x, m) in sorted(d.items()):
            print(f"   {k:28} {x:4}/{m:<4} {x/m:.3f}")
