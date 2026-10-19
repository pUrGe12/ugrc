"""Replay a seeded sample of Jev's recorded clause-base requests to Laya and compare decisions, question by question.

    LAYA_URL=http://127.0.0.1:8077/v1/systemone LAYA_KEY=... python agree.py N MODEL [MODEL ...]

A choice agrees when Laya picks Jev's label; a noul when both are on the same side of 0.5. Also records whether
Laya had to truncate the request to fit its context. Output: agree-<model>.jsonl, one line per request.
"""
import collections
import json
import os
import random
import sys
import time
import urllib.request
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASES = sorted((ROOT / "experiments/jev-bench/runs/v8").glob("*/clauses.duckdb")) + [
    ROOT / "experiments/jev-questions/runs/p2-v8-jev-latest/clauses.duckdb",
    ROOT / "experiments/jev-questions/runs/p3-v8-jev-latest/clauses.duckdb"]


def sample(n, seed=20261019):
    rows = []
    for b in BASES:
        con = duckdb.connect(str(b), read_only=True)
        rows += [(b.parent.name, *r) for r in con.execute("SELECT sha, kind, request, response FROM jev_calls ORDER BY sha").fetchall()]
        con.close()
    return random.Random(seed).sample(rows, n)


def laya(req, model):
    body = json.dumps({"state": req["state"], "questions": req["questions"], "model": model}).encode()
    r = urllib.request.Request(os.environ["LAYA_URL"], data=body, method="POST", headers={
        "Authorization": f"Bearer {os.environ['LAYA_KEY']}", "Content-Type": "application/json"})
    t = time.time()
    out = json.loads(urllib.request.urlopen(r, timeout=600).read())
    return out, time.time() - t


def side(a):
    if a.get("type") == "noul" or "noul" in a:
        return "yes" if a["noul"] >= 0.5 else "no"
    return a.get("choice")


if __name__ == "__main__":
    n, models = int(sys.argv[1]), sys.argv[2:]
    rows = sample(n)
    for model in models:
        path = HERE / f"agree-{model}.jsonl"
        done = {json.loads(l)["sha"] for l in path.open()} if path.exists() else set()
        with path.open("a") as f:
            for paper, sha, kind, req, resp in rows:
                if sha in done:
                    continue
                req, resp = json.loads(req), json.loads(resp)
                out, dt = laya(req, model)
                qs = {}
                for q, a in resp["answers"].items():
                    b = out["answers"].get(q, {})
                    qs[q] = {"jev": side(a), "laya": side(b), "n_opts": len(req["questions"][q].get("criteria") or {}) or 2,
                             "jev_p": a.get("confidence"), "laya_p": b.get("confidence")}
                u = out.get("usage", {})
                f.write(json.dumps({"sha": sha, "paper": paper, "kind": kind, "seconds": round(dt, 3), "questions": qs,
                                    "truncated": u.get("truncated"), "truncated_questions": u.get("truncated_questions"),
                                    "state_tokens_dropped": u.get("state_tokens_dropped"), "model": out.get("model")}) + "\n")
                f.flush()
        recs = [json.loads(l) for l in path.open()]
        by = collections.defaultdict(lambda: [0, 0])
        for r in recs:
            for q, v in r["questions"].items():
                key = (r["kind"], q.rstrip("0123456789").split("_")[0] if "_" in q else q.rstrip("0123456789"))
                by[r["kind"]][0] += v["jev"] == v["laya"]
                by[r["kind"]][1] += 1
        tot = [sum(x[0] for x in by.values()), sum(x[1] for x in by.values())]
        print(f"{model}: {len(recs)} requests, {tot[1]} questions, agreement with Jev {tot[0]}/{tot[1]} = {tot[0]/tot[1]:.3f}; "
              f"truncated requests {sum(1 for r in recs if r['truncated'])}; median {sorted(r['seconds'] for r in recs)[len(recs)//2]:.2f}s/call")
        for k, (a, b) in sorted(by.items()):
            print(f"   {k:10} {a}/{b} = {a/b:.3f}")
