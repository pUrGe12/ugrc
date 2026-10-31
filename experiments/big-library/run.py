"""The big library (PLAN.md): the routed pipeline (keyword search picks one paper, then that paper's facts+prose form) on
a library of about 125 papers on mixed and close topics, instead of 10.

    python experiments/big-library/run.py papers         no model: papers.json (every library paper), pdftotext caches
    python experiments/big-library/run.py build          no model: questions.json (the 246 library questions + 142 new)
    python experiments/big-library/run.py route          no model: routes.json, routing over the whole library
    python experiments/big-library/run.py routing        no model: routing accuracy by library and by set

Sets (runs/<dir>/<key>; pdftotext of the PDF the run ingested, checked against its manifest's sha256):
  cheme, cheme2   28 papers with questions (the library test's)            runs/cheme, runs/cheme2
  new6            6 papers with questions (four fields), extractor v5      runs/new6-v5
  bench           11 papers with questions (10 battery, 1 siRNA), v5        runs/bench-v5
  arxiv           32 arXiv battery papers, no questions (scaling-more)     runs/arxiv
  mixed           10 papers from ~/Downloads, no questions (ML, crypto hardware, maths, chip packaging, biology)
  cheme3          about 40 RSC Adv / ACS Omega papers on cheme2's topics, no questions (fetch.py)
"""
import hashlib
import importlib.util
import json
import math
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HOME = Path.home()


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R = _load("routed_run", ROOT / "experiments" / "routed" / "run.py")      # prompt(), the routed arms
L = R.L                                                                 # library test: SETS, TITLES, text_pages
P, C = L.P, L.C

SETS = {
    "cheme": {"runs": ROOT / "runs" / "cheme", "pdfs": HOME / "Desktop" / "papers-cheme",
              "text": ROOT / "experiments" / "cheme" / "direct-text"},
    "cheme2": {"runs": ROOT / "runs" / "cheme2", "pdfs": HOME / "Desktop" / "papers-cheme2",
               "text": ROOT / "experiments" / "cheme2" / "direct-text"},
    "new6": {"runs": ROOT / "runs" / "new6-v5", "pdfs": HOME / "Desktop" / "papers-new6",
             "text": ROOT / "experiments" / "new6" / "text"},
    "bench": {"runs": ROOT / "runs" / "bench-v5", "pdfs": HOME / "Desktop" / "papers-bench", "text": HERE / "text" / "bench"},
    "arxiv": {"runs": ROOT / "runs" / "arxiv", "pdfs": HOME / "Desktop" / "papers-arxiv", "text": HERE / "text" / "arxiv"},
    "mixed": {"runs": ROOT / "runs" / "mixed", "pdfs": HOME / "Desktop" / "papers-mixed", "text": HERE / "text" / "mixed"},
    "cheme3": {"runs": ROOT / "runs" / "cheme3", "pdfs": HOME / "Desktop" / "papers-cheme3", "text": HERE / "text" / "cheme3"},
}
ASKED = ("cheme", "cheme2", "new6", "bench")
MIXED_TITLES = {
    "3dic-thermal": "Thermal Sensitivity Analysis of 3D IC Face-to-Back Stacking Using Foundation Models for Physics",
    "cej-182243": "Intrinsic chiroptical structure-encoded single-probe sensor array for highly discriminative bacterial "
                  "identification",
    "cej-182355": "Serratia marcescens as an environmentally robust non-model chassis for green biomanufacturing of "
                  "natural products: Opportunities, challenges, and future perspectives",
    "contextbench": "ContextBench: Modifying Contexts for Targeted Latent Activation",
    "dana-tches": "DANA: Universal Dataflow Analysis for Gate-Level Netlist Reverse Engineering",
    "kimi-k2": "Kimi K2: Open Agentic Intelligence",
    "parks-np": "Parks: A Doubly Infinite Family of NP-Complete Puzzles and Generalizations of OEIS A002464",
    "polyominoes-1973": "A Procedure for Improving the Upper Bound for the Number of n-Ominoes",
    "semantic-synergy": "A Compositional Calculus for Semantic Synergy in Language Model Embeddings",
    "skill-state": "SKILL.state: Scalable Long-Horizon Agent Skills",
}
PAPERS = HERE / "papers.json"
QUESTIONS = HERE / "questions.json"
ROUTES = HERE / "routes.json"


def _titles():
    """{set: {key: title}} of every candidate paper, before the ingest filter."""
    t = {s: {k.split("/")[1]: v for k, v in L.TITLES.items() if k.startswith(f"{s}/")} for s in ("cheme", "cheme2")}
    t["new6"] = dict(C.new6.TITLES)
    t["bench"] = dict(C.direct.TITLES)
    t["arxiv"] = {o["id"]: o["title"] for o in json.loads((ROOT / "experiments" / "scaling-more" / "papers.json")
                                                             .read_text())}
    t["mixed"] = dict(MIXED_TITLES)
    f = HERE / "cheme3.json"
    t["cheme3"] = {k: C._title(v["title"]) for k, v in json.loads(f.read_text()).items()} if f.exists() else {}
    return t


def pdftotext(s, key):
    """pdftotext -enc UTF-8 of the PDF the run ingested (sha256 checked against its manifest), cached."""
    out = SETS[s]["text"] / f"{key}.txt"
    if not out.exists():
        man = json.loads((SETS[s]["runs"] / key / "manifest.json").read_text())
        pdf = SETS[s]["pdfs"] / f"{key}.pdf"
        got = hashlib.sha256(pdf.read_bytes()).hexdigest()
        assert got == man["sha256"], (s, key, "PDF differs from the one ingested")
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["pdftotext", "-enc", "UTF-8", str(pdf), str(out)], check=True)
    return out.read_text()


def papers():
    """papers.json: every paper whose ingest and clause base exist, with its title and page count; the rest listed."""
    out, dropped = {}, {}
    for s, titles in _titles().items():
        for key in sorted(titles):
            run = SETS[s]["runs"] / key
            if not (run / "clauses.duckdb").exists():
                dropped[f"{s}/{key}"] = "no clause base" if (run / "atoms.duckdb").exists() else "no ingest"
                continue
            text = pdftotext(s, key)
            pages = [p for p in text.split("\f") if p.strip()]
            out[f"{s}/{key}"] = {"set": s, "key": key, "title": titles[key], "asked": s in ASKED, "pages": len(pages),
                                 "text_chars": len(text), "text_sha256": hashlib.sha256(text.encode()).hexdigest()}
    PAPERS.write_text(json.dumps({"about": "run.py papers: the big library (papers with an ingest and a clause base)",
                                  "papers": out, "dropped": dropped}, indent=1, ensure_ascii=False) + "\n")
    by = Counter(v["set"] for v in out.values())
    print(f"{len(out)} papers: " + ", ".join(f"{s} {n}" for s, n in by.items()) + f"; {len(dropped)} dropped")
    for k, why in dropped.items():
        print(f"  dropped {k}: {why}")


def library():
    return json.loads(PAPERS.read_text())["papers"]


def install():
    """Teach the library and routed modules the new sets, so their text_pages(), connect() and prompt() work on them."""
    lib = library()
    for s, d in SETS.items():
        L.SETS.setdefault(s, {"runs": d["runs"], "text": d["text"]})
    for pid, v in lib.items():
        L.TITLES.setdefault(pid, v["title"])
        C.TITLES.setdefault(pid, v["title"])
    return lib


# ---------------------------------------------------------------- questions (no model)

def build():
    old = json.loads((ROOT / "experiments" / "library" / "questions.json").read_text())["questions"]
    reworded = json.loads((HERE / "reworded.json").read_text())["questions"]
    out = {}
    for key, q in old.items():
        out[key] = {k: v for k, v in q.items() if k != "library"} | {"origin": "library"}
    for s, f in (("new6", "new6/probes.json"), ("bench", "bench-leads/probes.json")):
        for paper, ps in json.loads((ROOT / "experiments" / f).read_text())["papers"].items():
            for p in ps:
                key = f"{s}/{paper}/{p['id']}"
                out[key] = {"set": s, "paper": paper, "id": p["id"], "cat": p["cat"], "q": reworded[key],
                            "q_original": p["q"], "expect": p["expect"], "trap": p.get("trap"), "must": p["must"],
                            "must_not": p.get("must_not", []), "origin": f}
    assert len(out) == 246 + 54 + 88, len(out)
    assert set(reworded) == {k for k in out if k.split("/")[0] in ("new6", "bench")}
    QUESTIONS.write_text(json.dumps({"about": "run.py build: the library test's 246 questions (its wording) and the new6 "
                                     "and bench-leads questions reworded in reworded.json; answer keys unchanged.",
                                     "questions": out}, indent=1, ensure_ascii=False) + "\n")
    print(Counter(q["set"] for q in out.values()), Counter(q["cat"] for q in out.values()))


def questions():
    return json.loads(QUESTIONS.read_text())["questions"]


# ---------------------------------------------------------------- routing (no model)

class Index:
    """BM25 over pages, as hybrid.bm25 (same tokens, k1, b, idf), with each page tokenized once."""

    def __init__(self, pages):
        self.keys = list(pages)
        self.tf = [Counter(P.hybrid._words(pages[k])) for k in self.keys]
        self.len = [sum(c.values()) for c in self.tf]

    def rank(self, question, subset=None, k1=1.5, b=0.75):
        idx = [i for i, k in enumerate(self.keys) if subset is None or k[0] in subset]
        n = len(idx)
        avg = sum(self.len[i] for i in idx) / max(n, 1)
        terms = set(P.hybrid._words(question))
        df = {t: sum(1 for i in idx if t in self.tf[i]) for t in terms}
        score = {}
        for i in idx:
            tf = self.tf[i]
            score[self.keys[i]] = sum(math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) * tf[t] * (k1 + 1)
                                      / (tf[t] + k1 * (1 - b + b * self.len[i] / avg)) for t in terms if tf[t])
        return sorted(score, key=lambda k: -score[k])


def index(lib):
    install()
    pages = {(d, n): f"=== {lib[d]['title']}, page {n} ===\n{body}" for d in lib for n, body in L.text_pages(d).items()}
    return Index(pages)


def paper_order(ranked):
    order = []
    for d, _ in ranked:
        if d not in order:
            order.append(d)
    return order


def route():
    lib = library()
    ix = index(lib)
    qs = questions()
    out = {}
    for key, q in qs.items():
        ranked = ix.rank(q["q"])
        order = paper_order(ranked)
        target = f"{q['set']}/{q['paper']}"
        out[key] = {"target": target, "routed": order[0], "top_page": list(ranked[0]), "routed_right": order[0] == target,
                    "target_rank": order.index(target) + 1, "paper_order": order[:10]}
    ROUTES.write_text(json.dumps({"about": f"run.py route: the paper of the top BM25 page among all {len(lib)} library "
                                           "papers' pdftotext pages, headed by title", "routes": out}, indent=1) + "\n")
    right = sum(r["routed_right"] for r in out.values())
    print(f"{right} of {len(out)} routed to their own paper over {len(lib)} papers")


def routing():
    """Top-1 and top-k routing per library size and per question set (no model)."""
    lib = library()
    ix = index(lib)
    qs = questions()
    libs10 = json.loads((ROOT / "experiments" / "library" / "libraries.json").read_text())["libraries"]
    asked = {d for d, v in lib.items() if v["asked"]}
    views = {"asked papers only": asked,
             "asked + cheme3": asked | {d for d in lib if d.startswith("cheme3/")},
             "asked + arxiv + mixed": asked | {d for d in lib if d.split("/")[0] in ("arxiv", "mixed")},
             "whole library": set(lib)}
    rows = {}
    for key, q in qs.items():
        target = f"{q['set']}/{q['paper']}"
        r = {}
        if q.get("origin") == "library":
            old = json.loads((ROOT / "experiments" / "library" / "questions.json").read_text())["questions"][key]
            r["10-paper library"] = paper_order(ix.rank(q["q"], set(libs10[old["library"]]["documents"]))).index(target) + 1
        for name, sub in views.items():
            r[name] = paper_order(ix.rank(q["q"], sub)).index(target) + 1
        rows[key] = r
    print(f"library sizes: asked {len(asked)}, " + ", ".join(f"{n} {len(s)}" for n, s in views.items()))
    groups = {"cheme+cheme2": lambda k: k.split("/")[0] in ("cheme", "cheme2"), "new6": lambda k: k.startswith("new6/"),
              "bench": lambda k: k.startswith("bench/"), "all": lambda k: True}
    for view in ["10-paper library"] + list(views):
        for g, f in groups.items():
            ks = [k for k in rows if f(k) and view in rows[k]]
            if not ks:
                continue
            top = [sum(rows[k][view] <= n for k in ks) for n in (1, 2, 3, 5)]
            print(f"  {view:24} {g:13} n={len(ks):3}  top1 {top[0]:3} ({top[0] / len(ks):.1%})  top2 {top[1]:3}  "
                  f"top3 {top[2]:3}  top5 {top[3]:3}")
    (HERE / "routing.json").write_text(json.dumps(rows, indent=1) + "\n")



# ---------------------------------------------------------------- prompts

ARMS = ("top1", "top2", "oracle")
TOP2_SYSTEM = ("You answer questions using only what two documents contain. A keyword search picked them from a larger "
               "library as the two most likely to answer the question. The question does not say which document it is "
               "about: find the one that answers it, and name it. Each document is below, condensed: page by page, the "
               "sentences that state a value, with the few other sentences that best match the question (the rest are "
               "left out), then its tables row by row and facts read from its figures. Answer briefly. If you compute a "
               "number, show the calculation. If the question assumes something the documents contradict, say so. If "
               "neither document holds the answer, say so.")


def shown(arm, key, route):
    """The papers an arm's prompt holds, in prompt order."""
    if arm == "top1":
        return [route["routed"]]
    if arm == "top2":
        return route["paper_order"][:2]
    return [route["target"]]


def prompt(arm, q, docs):
    """(system, user, extra). top1 and oracle: the routed test's prose prompt for one paper (byte-identical to it when
    the paper is the same); top2: both papers' facts+prose documents, best-ranked first."""
    if arm in ("top1", "oracle"):
        return R.prompt("prose", q, docs[0])
    blocks, extra = [], {"documents": []}
    for d in docs:
        doc, picked, used = P.document(L.connect(d), q)
        blocks.append(f'<document title="{L.TITLES[d]}">\n{doc}\n</document>')
        extra["documents"].append({"paper": d, "sentences": picked, "chars": len(doc), "added_chars": used,
                                   "sha256": hashlib.sha256(doc.encode()).hexdigest()})
    return TOP2_SYSTEM, "\n\n".join(blocks) + f"\n\nQuestion: {q}", extra


# ---------------------------------------------------------------- answering

def frozen():
    install()
    C._check_frozen(ROOT / "experiments" / "library" / "frozen.sha256")
    C._check_frozen(ROOT / "experiments" / "routed" / "frozen.sha256")
    C._check_frozen(HERE / "frozen.sha256")
    return questions(), json.loads(ROUTES.read_text())["routes"]


def answer_path(arm, key):
    s, paper, pid = key.split("/")
    return HERE / "answers" / f"{arm}-r1" / f"{s}__{paper}-{pid}.json"


def todo(arm, qs, routes):
    """oracle is answered only where top1's paper is not the question's: elsewhere its prompt is top1's, byte for byte."""
    keys = [k for k in qs if arm != "oracle" or not routes[k]["routed_right"]]
    return [k for k in keys if not answer_path(arm, k).exists()]


def one(arm, key, q, route):
    f = answer_path(arm, key)
    if f.exists():
        return
    t = time.time()
    docs = shown(arm, key, route)
    system, user, extra = prompt(arm, q["q"], docs)
    resp = R.scaling.cr.chat(system, user)
    choice = resp["choices"][0]
    text = choice["message"].get("content") or ""
    target = route["target"]
    rec = {"arm": arm, "run": 1, "key": key, "set": q["set"], "paper": q["paper"], "probe": q["id"], "cat": q["cat"],
           "question": q["q"], "expect": q["expect"], "trap": q["trap"], "must": q["must"],
           "model": R.scaling.cr.MODEL, "rendered": text, "finish_reason": choice.get("finish_reason"),
           "shown_papers": docs, "target": target, "target_shown": target in docs,
           "routed": route["routed"], "target_rank": route["target_rank"], "top_page": route["top_page"],
           "numbers_not_in_paper": sorted({R.scaling.cr._n(x) for x in R.scaling.cr.NUM.findall(text)}
                                          - L.numbers(target) - {""}),
           **extra,
           "prompt": {"style": f"big-library:{arm}", "system": system, "user_chars": len(user),
                      "user_sha256": hashlib.sha256(user.encode()).hexdigest()},
           "usage": resp.get("usage"),
           "sampling": {"temperature": R.llm.TEMPERATURE, "top_p": R.llm.TOP_P, "max_tokens": R.llm.MAX_OUTPUT},
           "seconds": round(time.time() - t, 1)}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
    u = rec["usage"] or {}
    R.log(f"done  {arm:6} {key:40} prompt={u.get('prompt_tokens', '?'):>6} target_shown={rec['target_shown']!s:5} "
          f"{rec['finish_reason']} {time.time() - t:5.1f}s")


def answer(arms, workers):
    if not R.scaling.cr.URL:
        raise SystemExit("set LLAMA_URL (the server's /v1) and LLAMA_KEY")
    qs, routes = frozen()
    R.log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} start: arms {arms}")
    for arm in arms:
        keys = sorted(todo(arm, qs, routes), key=lambda k: (shown(arm, k, routes[k]), k))   # shared prefill
        R.log(f"-- {arm}: {len(keys)} questions")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda k: one(arm, k, qs[k], routes[k]), keys))
    R.log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} end")


def sizes():
    install()
    qs, routes = questions(), json.loads(ROUTES.read_text())["routes"]
    for arm in ARMS:
        n = []
        for k in qs:
            if arm == "oracle" and routes[k]["routed_right"]:
                continue
            system, user, _ = prompt(arm, qs[k]["q"], shown(arm, k, routes[k]))
            n.append((len(system) + len(user)) / 3.6)
        if n:
            print(f"{arm:6} {len(n):3} prompts, tokens (chars / 3.6): mean {sum(n) / len(n):,.0f}, max {max(n):,.0f}")


def show(arm, key):
    install()
    qs, routes = questions(), json.loads(ROUTES.read_text())["routes"]
    system, user, _ = prompt(arm, qs[key]["q"], shown(arm, key, routes[key]))
    print(f"SYSTEM: {system}\n\nUSER ({len(user):,} chars):\n{user[:1500]}\n...\n{user[-600:]}")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "papers":
        papers()
    elif cmd == "build":
        build()
    elif cmd == "route":
        route()
    elif cmd == "routing":
        routing()
    elif cmd == "sizes":
        sizes()
    elif cmd == "show":
        show(sys.argv[2], sys.argv[3])
    elif cmd == "answer":
        a = sys.argv[sys.argv.index("--arms") + 1].split(",") if "--arms" in sys.argv else list(ARMS)
        assert set(a) <= set(ARMS), a
        answer(a, int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 8)
    else:
        raise SystemExit(__doc__)
