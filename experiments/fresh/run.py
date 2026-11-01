"""A fresh paper enters the 120-paper library (PLAN.md): the winning setup (keyword search picks the paper, then that
paper's facts+prose form) on 10 new ChemE papers, each added alone to the big-library test's 120 papers, with 80 new
questions; against the right paper's facts+prose form and its whole pasted PDF.

    python experiments/fresh/run.py intake      no model: what adding each paper took (prepare.log, stores); intake.json
    python experiments/fresh/run.py route       no model: routes.json (each question over 120 + its paper; and over 130)
    python experiments/fresh/run.py old         no model: do the 388 old questions still route the same with 130 papers?
    python experiments/fresh/run.py sizes       no model: prompt sizes per arm
    python experiments/fresh/run.py show ARM KEY
    python experiments/fresh/run.py answer [--arms top1,oracle,pdf] [--workers 8]   needs LLAMA_URL, LLAMA_KEY
"""
import datetime as dt
import hashlib
import importlib.util
import json
import math
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


BL = _load("big_run", ROOT / "experiments" / "big-library" / "run.py")    # router, library, install()
R, L, P, C = BL.R, BL.L, BL.P, BL.C

SET = "fresh"
BL.SETS[SET] = {"runs": ROOT / "runs" / SET, "pdfs": Path.home() / "Desktop" / "papers-fresh", "text": HERE / "text"}
PAPERS = json.loads((HERE / "papers.json").read_text())
TITLES = {f"{SET}/{k}": C._title(v["title"]) for k, v in PAPERS.items()}
ARMS = ("top1", "oracle", "pdf")
ROUTES = HERE / "routes.json"


def install():
    """The big library's sets and titles, plus the fresh papers' (pdftotext made from the hash-checked PDF)."""
    lib = BL.install()
    L.SETS.setdefault(SET, {"runs": BL.SETS[SET]["runs"], "text": BL.SETS[SET]["text"]})
    for pid, t in TITLES.items():
        L.TITLES.setdefault(pid, t)
        C.TITLES.setdefault(pid, t)
        BL.pdftotext(SET, pid.split("/")[1])
    return lib


def questions():
    return json.loads((HERE / "questions.json").read_text())["questions"]


# ---------------------------------------------------------------- intake (no model)

def intake():
    """Per fresh paper: seconds to ingest and to build the clause base (prepare.log), what the stores hold, Jev calls,
    and the size of what the router and the model see."""
    install()
    log = (HERE / "prepare.log").read_text().splitlines()
    stamps = {}
    for line in log:
        m = re.match(r"== (\S+) (ingest|clauses|done) fresh/(\S+)", line)
        if m:
            stamps.setdefault(m.group(3), {})[m.group(2)] = dt.datetime.fromisoformat(m.group(1))
    out = {}
    for key in PAPERS:
        pid, run = f"{SET}/{key}", BL.SETS[SET]["runs"] / key
        st = stamps[key]
        a = duckdb.connect(str(run / "atoms.duckdb"), read_only=True)
        cl = duckdb.connect(str(run / "clauses.duckdb"), read_only=True)
        q = lambda con, sql: con.execute(sql).fetchone()[0]  # noqa: E731
        text = L.paper_text(pid)
        printed = sorted({int(n) for n in re.findall(r"^\s*Table (\d+)", text, re.M)})
        con = L.connect(pid)
        facts = R.scaling.condensed(con, "facts")
        out[key] = {
            "pages": len(L.text_pages(pid)),
            "ingest_s": (st["clauses"] - st["ingest"]).total_seconds(),
            "clauses_s": (st["done"] - st["clauses"]).total_seconds(),
            "lines": q(a, "SELECT count(*) FROM lines"), "tables_found": q(a, "SELECT count(*) FROM tables"),
            "tables_printed": len(printed), "cells": q(a, "SELECT count(*) FROM cells"),
            "figures": q(a, "SELECT count(*) FROM figures"),
            "sentences": q(cl, "SELECT count(*) FROM sentences"), "values": q(cl, "SELECT count(*) FROM measures"),
            "labels": q(cl, "SELECT count(*) FROM measures WHERE role = 'identifier'"),
            "jev_calls": q(cl, "SELECT count(*) FROM jev_calls"),
            "pdf_tokens": round(len(text) / 3.6), "facts_tokens": round(len(facts) / 3.6),
        }
    (HERE / "intake.json").write_text(json.dumps(out, indent=1) + "\n")
    cols = ("pages", "ingest_s", "clauses_s", "tables_found", "tables_printed", "values", "labels", "jev_calls",
            "pdf_tokens", "facts_tokens")
    print(f"{'paper':22}" + "".join(f"{c:>15}" for c in cols))
    for k, v in out.items():
        print(f"{k:22}" + "".join(f"{v[c]:>15,.0f}" for c in cols))
    tot = {c: sum(v[c] for v in out.values()) for c in cols}
    print(f"{'total':22}" + "".join(f"{tot[c]:>15,.0f}" for c in cols))


# ---------------------------------------------------------------- routing (no model)

def index():
    """One BM25 index over the 120 library papers' pages and the 10 fresh papers'; rank() takes the library subset."""
    lib = install()
    allp = dict(lib) | {pid: {"title": t} for pid, t in TITLES.items()}
    return lib, BL.index(allp)


def ranked(ix, question, subset, k1=1.5, b=0.75):
    """Index.rank with the scores kept: [(page key, score)], best first, over the pages of `subset` papers."""
    idx = [i for i, k in enumerate(ix.keys) if k[0] in subset]
    n = len(idx)
    avg = sum(ix.len[i] for i in idx) / n
    terms = set(P.hybrid._words(question))
    df = {t: sum(1 for i in idx if t in ix.tf[i]) for t in terms}
    score = {}
    for i in idx:
        tf = ix.tf[i]
        score[ix.keys[i]] = sum(math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) * tf[t] * (k1 + 1)
                                / (tf[t] + k1 * (1 - b + b * ix.len[i] / avg)) for t in terms if tf[t])
    return sorted(score.items(), key=lambda kv: -kv[1])


def summary(rk):
    order, best = [], {}
    for (d, _), s in rk:
        if d not in best:
            order.append(d)
            best[d] = s
    s1, s2 = best[order[0]], best[order[1]]
    return order, round(s2 / s1, 4) if s1 else 1.0


def route():
    lib, ix = index()
    qs = questions()
    out = {}
    for key, q in qs.items():
        target = f"{SET}/{q['paper']}"
        rk = ranked(ix, q["q"], set(lib) | {target})                         # the 120 papers + this one
        order, unsure = summary(rk)
        order130, _ = summary(ranked(ix, q["q"], set(lib) | set(TITLES)))     # all 10 fresh papers at once
        out[key] = {"target": target, "routed": order[0], "top_page": list(rk[0][0]),
                    "routed_right": order[0] == target, "target_rank": order.index(target) + 1,
                    "paper_order": order[:5], "unsure": unsure,
                    "routed_130": order130[0], "target_rank_130": order130.index(target) + 1}
    ROUTES.write_text(json.dumps({"about": "run.py route: each question's paper of the top BM25 page over the 120 "
                                           "library papers plus its own fresh paper (and, as a check, over all 130); "
                                           "unsure = the second paper's best page score over the first's",
                                  "routes": out}, indent=1) + "\n")
    right = sum(r["routed_right"] for r in out.values())
    print(f"{right} of {len(out)} routed to their own paper over 121 papers; "
          f"{sum(r['target_rank'] <= 2 for r in out.values())} in the top 2; "
          f"over 130: {sum(r['target_rank_130'] == 1 for r in out.values())}")
    for k, r in out.items():
        if not r["routed_right"]:
            print(f"  {k:36} -> {r['routed']:40} own rank {r['target_rank']}, unsure {r['unsure']}")


def old():
    """The 388 big-library questions routed again over 130 papers: how many change paper, and to a fresh one?"""
    lib, ix = index()
    qs, before = BL.questions(), json.loads(BL.ROUTES.read_text())["routes"]
    allp = set(lib) | set(TITLES)
    changed, to_fresh, right = [], [], 0
    for key, q in qs.items():
        order, _ = summary(ranked(ix, q["q"], allp))
        right += order[0] == before[key]["target"]
        if order[0] != before[key]["routed"]:
            changed.append(key)
            to_fresh += [key] if order[0].startswith(f"{SET}/") else []
    print(f"388 old questions over 130 papers: {right} to their own paper (120 papers: "
          f"{sum(r['routed_right'] for r in before.values())}); {len(changed)} change paper, {len(to_fresh)} to a "
          f"fresh one: {' '.join(to_fresh)}")
    (HERE / "old-routes.json").write_text(json.dumps({"changed": changed, "to_fresh": to_fresh, "right": right},
                                                     indent=1) + "\n")


# ---------------------------------------------------------------- prompts and answers

def routes():
    return json.loads(ROUTES.read_text())["routes"]


def paper(arm, r):
    return r["routed"] if arm == "top1" else r["target"]


def prompt(arm, q, r):
    """top1, oracle: the routed test's facts+prose prompt on one paper; pdf: its pasted-PDF prompt on the right paper."""
    return R.prompt("pdf" if arm == "pdf" else "prose", q, paper(arm, r))


def frozen():
    install()
    C._check_frozen(ROOT / "experiments" / "big-library" / "frozen.sha256")
    C._check_frozen(HERE / "frozen.sha256")
    return questions(), routes()


def answer_path(arm, key):
    _, p, pid = key.split("/")
    return HERE / "answers" / f"{arm}-r1" / f"{p}-{pid}.json"


def todo(arm, qs, rt):
    """oracle only where top1's paper is not the question's: elsewhere its prompt is top1's, byte for byte."""
    return [k for k in qs if (arm != "oracle" or not rt[k]["routed_right"]) and not answer_path(arm, k).exists()]


def one(arm, key, q, r):
    f = answer_path(arm, key)
    if f.exists():
        return
    t = time.time()
    system, user, extra = prompt(arm, q["q"], r)
    resp = R.scaling.cr.chat(system, user)
    choice = resp["choices"][0]
    text = choice["message"].get("content") or ""
    rec = {"arm": arm, "run": 1, "key": key, "paper": q["paper"], "probe": q["id"], "cat": q["cat"],
           "question": q["q"], "expect": q["expect"], "trap": q["trap"], "must": q["must"],
           "model": R.scaling.cr.MODEL, "rendered": text, "finish_reason": choice.get("finish_reason"),
           "shown_paper": paper(arm, r), "target": r["target"], "target_shown": paper(arm, r) == r["target"],
           "routed": r["routed"], "target_rank": r["target_rank"],
           "numbers_not_in_paper": sorted({R.scaling.cr._n(x) for x in R.scaling.cr.NUM.findall(text)}
                                          - L.numbers(r["target"]) - {""}),
           **extra,
           "prompt": {"style": f"fresh:{arm}", "system": system, "user_chars": len(user),
                      "user_sha256": hashlib.sha256(user.encode()).hexdigest()},
           "usage": resp.get("usage"),
           "sampling": {"temperature": R.llm.TEMPERATURE, "top_p": R.llm.TOP_P, "max_tokens": R.llm.MAX_OUTPUT},
           "seconds": round(time.time() - t, 1)}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
    u = rec["usage"] or {}
    R.log(f"done  {arm:6} {key:32} prompt={u.get('prompt_tokens', '?'):>6} target_shown={rec['target_shown']!s:5} "
          f"{rec['finish_reason']} {time.time() - t:5.1f}s")


def answer(arms, workers):
    if not R.scaling.cr.URL:
        raise SystemExit("set LLAMA_URL (the server's /v1) and LLAMA_KEY")
    qs, rt = frozen()
    R.log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} fresh start: arms {arms}")
    for arm in arms:
        keys = sorted(todo(arm, qs, rt), key=lambda k: (paper(arm, rt[k]), k))       # shared prefill
        R.log(f"-- {arm}: {len(keys)} questions")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda k: one(arm, k, qs[k], rt[k]), keys))
    R.log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} fresh end")


def sizes():
    install()
    qs, rt = questions(), routes()
    for arm in ARMS:
        n = [sum(map(len, prompt(arm, qs[k]["q"], rt[k])[:2])) / 3.6 for k in qs
             if arm != "oracle" or not rt[k]["routed_right"]]
        if n:
            print(f"{arm:6} {len(n):3} prompts, tokens (chars / 3.6): mean {sum(n) / len(n):,.0f}, max {max(n):,.0f}")


def show(arm, key):
    install()
    system, user, _ = prompt(arm, questions()[key]["q"], routes()[key])
    print(f"SYSTEM: {system}\n\nUSER ({len(user):,} chars):\n{user[:1500]}\n...\n{user[-600:]}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd in ("intake", "route", "old", "sizes"):
        globals()[cmd]()
    elif cmd == "show":
        show(sys.argv[2], sys.argv[3])
    elif cmd == "answer":
        a = sys.argv[sys.argv.index("--arms") + 1].split(",") if "--arms" in sys.argv else list(ARMS)
        assert set(a) <= set(ARMS), a
        answer(a, int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 8)
    else:
        raise SystemExit(__doc__)
