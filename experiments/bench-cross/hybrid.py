"""The hybrid: code (and Jev's clause base) finds the passages, the model reads them and answers in its own words, and
code checks the citations afterwards. No tools, no refusal loop: one reply.

    LLAMA_URL=<server>/v1 LLAMA_KEY=... python experiments/bench-cross/hybrid.py cross [--workers N] [--only W1,C2]
    LLAMA_URL=<server>/v1 LLAMA_KEY=... python experiments/bench-cross/hybrid.py bench [--workers N] [--papers a,b]
    either with [--runs 1,2,3] (default 1) and [--pick bm25] (no leads: pages by BM25 alone; arm llama-hybrid-bm25)

cross: the 33 cross-paper probes over runs/papers-corpus      -> bench-cross/answers/llama-hybrid-r1/<id>.json
bench: the 154 single-paper probes, each on its own paper     -> bench-llama/answers/llama-hybrid-r1/<bench>/<paper>-<id>.json
       (runs/bench/<paper>: the substrate and its clause base)

Passages are whole pages, rendered from ugrc's atoms with their ids: every line, every table row (cells joined, with
the column headers), every figure fact. Pages are picked in this order until BUDGET tokens (chars / 3.6):
  1. the pages of the leads (ugrc.leads: the clause-base sentences that best match the question, as ugrc sends them);
  2. the pages ranked by BM25 against the question.
A single paper that fits in BUDGET is passed whole. The model answers in its own words (asking an 8B model to cite ids
made it copy passage lines back and invent ids). Code then gives every number in the answer a pointer: the passage
atom that prints it and shares the most words with the answer's sentence (`pointers`); a number printed in no passage
is listed apart (computed by the model, or invented). Nothing is refused; grading is by hand.
"""
import json
import math
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from ugrc import leads, llm, store  # noqa: E402
sys.path.insert(0, str(ROOT / "experiments" / "bench-llama"))
from direct import TITLES  # noqa: E402

LLAMA_URL = os.environ.get("LLAMA_URL", "").rstrip("/")
LLAMA_KEY = os.environ.get("LLAMA_KEY")
MODEL = os.environ.get("LLAMA_MODEL", "llama-3.1-8b-instruct")
BUDGET = 24_000
ARM = "llama-hybrid"
PICK = "leads"                 # or "bm25": Jev's leads left out of page picking (set by --pick); or "leads-text"


# "leads-text": the same lead search without Jev's part. The clause base's readings of each value (what it is of, by
# what method, what it measures, its unit) and the aliases the judge accepted are left out; the sentences' own words,
# the paper's own "<long form> (SHORT)" definitions and the rest of ugrc.leads stay. Applied by patching ugrc.leads,
# so a process (or a single-threaded block) runs one way at a time.
class NoAliases:
    """A connection that answers the aliases query (leads.defined's only query) with no rows."""

    def __init__(self, con):
        self.con = con

    def execute(self, sql, *args):
        if "aliases" in sql:
            return self.con.execute("SELECT NULL, NULL WHERE false")
        return self.con.execute(sql, *args)


def _no_readings(m):
    return []


def _defined_without_aliases(con, question, texts, _defined=leads.defined):
    return _defined(NoAliases(con), question, texts)


JEV_OFF = {"_reading_text": _no_readings, "defined": _defined_without_aliases}
SYSTEM = ("You answer questions using only the documents below: pages selected from them, with tables written row by "
          "row. Answer briefly. If you compute a number, show the calculation. If the question assumes something "
          "the documents contradict, say so. If the documents do not hold the answer, say so.")
lock = threading.Lock()


def _q(con, sql, args=()):
    return con.execute(sql, list(args)).fetchall()


def pages(con) -> dict[tuple, dict]:
    """{(doc, page): {"text": rendered page, "atoms": {id: text}}} for every page of the substrate or corpus."""
    corpus = "doc" in {r[0] for r in _q(con, "DESCRIBE lines")}
    d = "doc" if corpus else "NULL"
    out = {}

    def page(doc, p):
        return out.setdefault((doc, p), {"lines": [], "atoms": {}, "tables": set()})

    for doc, p, i, t in _q(con, f"SELECT {d}, page, id, text FROM lines ORDER BY {'doc, ' if corpus else ''}page, line_no"):
        page(doc, p)["lines"].append(t)
        page(doc, p)["atoms"][i] = t
    heads = {}
    for tid, c, h in _q(con, "SELECT table_id, col_no, header FROM table_columns ORDER BY table_id, col_no"):
        heads.setdefault(tid, []).append(h or "")
    tables = {tid: (p, lab, cap) for tid, p, lab, cap in _q(con, f"SELECT id, page, label, caption FROM tables")}
    rows = {}
    for cid, tid, r, c, t in _q(con, "SELECT id, table_id, row_no, col_no, text FROM cells ORDER BY table_id, row_no, col_no"):
        rows.setdefault((tid, r), []).append(t or "")
    tdoc = {}
    if corpus:
        tdoc = dict(_q(con, "SELECT id, doc FROM tables"))
    for (tid, r), cells in sorted(rows.items(), key=lambda x: (x[0][0], x[0][1])):
        p, lab, cap = tables.get(tid, (None, None, None))
        pg = page(tdoc.get(tid), p)
        if tid not in pg["tables"]:
            pg["lines"].append(f"{lab or 'Table'}. {cap or ''}" + (f"\nColumns: {' | '.join(heads[tid])}" if tid in heads else ""))
            pg["tables"].add(tid)
        rid = f"{tid}.r{r}"
        pg["lines"].append(" | ".join(cells))
        pg["atoms"][rid] = " | ".join(cells)
    fdoc = dict(_q(con, "SELECT id, doc FROM figures")) if corpus else {}
    fpage = {fid: (p, lab, cap) for fid, p, lab, cap in _q(con, "SELECT id, page, label, caption FROM figures")}
    for kid, fid, st, v, u in _q(con, "SELECT id, figure_id, statement, value, unit FROM figure_facts ORDER BY figure_id, id"):
        p, lab, cap = fpage.get(fid, (None, None, None))
        pg = page(fdoc.get(fid), p)
        txt = f"{st}" + (f" ({v} {u or ''})" if v is not None else "")
        pg["lines"].append(f"({lab or 'Figure'}, read from the image) {txt}")
        pg["atoms"][kid] = txt
    for k, pg in out.items():
        pg["text"] = (f"=== {TITLES.get(k[0], k[0])}, page {k[1]} ===\n" if k[0] else f"=== page {k[1]} ===\n") + "\n".join(pg["lines"])
    return out


def _words(s):
    return re.findall(r"[a-z0-9]+", s.lower())


def bm25(question, docs: dict, k1=1.5, b=0.75):
    toks = {k: _words(v) for k, v in docs.items()}
    avg = sum(len(t) for t in toks.values()) / max(len(toks), 1)
    terms = set(_words(question))
    df = {t: sum(t in set(d) for d in toks.values()) for t in terms}
    score = {}
    for k, d in toks.items():
        tf = {}
        for w in d:
            if w in terms:
                tf[w] = tf.get(w, 0) + 1
        score[k] = sum(math.log(1 + (len(toks) - df[t] + 0.5) / (df[t] + 0.5)) * tf[t] * (k1 + 1)
                       / (tf[t] + k1 * (1 - b + b * len(d) / avg)) for t in tf)
    return sorted(score, key=lambda k: -score[k])


LEAD_PAGE = re.compile(r"(?:([a-z0-9][a-z0-9._-]*):)?p(\d+)\.L\d+")


def pick(con, question, pgs, way=None):
    way = way or PICK
    if way == "leads-text":
        assert leads._reading_text is _no_readings, "leads-text needs JEV_OFF applied to ugrc.leads"
    found = leads.find(con, question) if way in ("leads", "leads-text") else None
    lead_pages = []
    for sid in (found.sentences if found else []):
        m = LEAD_PAGE.match(sid)
        if m and (m.group(1), int(m.group(2))) not in lead_pages:
            lead_pages.append((m.group(1), int(m.group(2))))
    size = {k: len(v["text"]) / 3.6 for k, v in pgs.items()}
    if sum(size.values()) <= BUDGET:
        return sorted(pgs), found
    order = [k for k in lead_pages if k in pgs] + [k for k in bm25(question, {k: v["text"] for k, v in pgs.items()}) if k not in lead_pages]
    chosen, total = [], 0
    for k in order:
        if total + size[k] <= BUDGET:
            chosen.append(k)
            total += size[k]
    return sorted(chosen, key=lambda k: (k[0] or "", k[1])), found


NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def _n(s):
    return s.replace(",", "").replace("\u2009", "").rstrip(".")


def attribute(answer: str, atoms: dict) -> dict:
    """Every number of two or more characters in the answer, given a pointer by code: the passage atom that prints it
    and shares the most words with the answer's sentence around it. A number printed in no passage atom is left
    without one (computed by the model, or invented)."""
    index = {}
    for i, t in atoms.items():
        for x in NUM.findall(t or ""):
            index.setdefault(_n(x), set()).add(i)
    out = {"pointed": [], "not_in_passages": []}
    for sent in re.split(r"(?<=[.!?])\s+|\n+", answer):
        sw = set(_words(sent))
        for m in NUM.finditer(sent):
            v = _n(m.group())
            if len(v) == 1:
                continue
            cands = index.get(v)
            if not cands:
                out["not_in_passages"].append(v)
                continue
            scored = sorted(cands, key=lambda i: (-len(sw & set(_words(atoms[i]))), i))
            out["pointed"].append([v, scored[0], len(cands)])
    return out


def answer(con, question, pgs, title=None, way=None):
    way = way or PICK
    chosen, found = pick(con, question, pgs, way)
    body = "\n\n".join(pgs[k]["text"] for k in chosen)
    atoms = {i: t for k in chosen for i, t in pgs[k]["atoms"].items()}
    sys_prompt = SYSTEM + (f' The documents are pages of "{title}".' if title else "")
    body_q = f"{body}\n\nQuestion: {question}"
    import urllib.request
    req = urllib.request.Request(f"{LLAMA_URL}/chat/completions", data=json.dumps({
        "model": MODEL, "messages": [{"role": "system", "content": sys_prompt}, {"role": "user", "content": body_q}],
        "max_tokens": llm.MAX_OUTPUT, "temperature": llm.TEMPERATURE, "top_p": llm.TOP_P}).encode(),
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {LLAMA_KEY}"} if LLAMA_KEY else {})})
    for attempt in range(llm.RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=llm.TIMEOUT_S) as r:
                resp = json.loads(r.read())
            break
        except Exception:
            if attempt == llm.RETRIES:
                raise
            time.sleep(min(2 ** attempt, 60))
    text = resp["choices"][0]["message"].get("content") or ""
    return {"rendered": text, "finish_reason": resp["choices"][0].get("finish_reason"), "turns": 1, "tool_calls": 0,
            "door_refusals": [], "citations": [], "runs": [], "trace": [], "usage": resp.get("usage"),
            "pages": [list(k) for k in chosen], "leads": found.record() if found else None, "pointers": attribute(text, atoms),
            "prompt": {"style": "hybrid", "system": sys_prompt, "budget_tokens": BUDGET, "pick": way}}


def log(msg):
    with lock:
        print(msg, flush=True)


def run_cross(workers, only, run):
    import importlib.util          # bench-llama's run.py is already imported as `run`
    spec = importlib.util.spec_from_file_location("cross_run", HERE / "run.py")
    cross = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cross)
    con = store.connect_question(ROOT / "runs" / "papers-corpus")
    pgs = pages(con)
    out = HERE / "answers" / f"{ARM}-r{run}"
    out.mkdir(parents=True, exist_ok=True)
    jobs = [p for p in cross.probes() if not only or p["id"] in only]

    def one(p):
        f = out / f"{p['id']}.json"
        if f.exists():
            return
        t = time.time()
        c = store.connect_question(ROOT / "runs" / "papers-corpus")
        rec = answer(c, p["q"], pgs)
        rec.update(arm=ARM, run=run, probe=p["id"], cat=p["cat"], papers=p["papers"], expect=p["expect"], trap=p.get("trap"),
                   model=MODEL, seconds=round(time.time() - t, 1),
                   needed_pages_in_prompt=sorted({k[0] for k in map(tuple, rec["pages"])} & set(p["papers"])))
        f.write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
        pt = rec["pointers"]
        log(f"done  {p['id']:3} pages={len(rec['pages'])} pointed={len(pt['pointed'])} not_in_passages={pt['not_in_passages']} {time.time() - t:.0f}s")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))


def run_bench(workers, only, run, papers=None):
    sys.path.insert(0, str(ROOT / "experiments" / "bench-llama"))
    import run as bench
    import direct
    out_root = ROOT / "experiments" / "bench-llama" / "answers" / f"{ARM}-r{run}"
    jobs = [(b, paper, p) for b, paper, p in bench.probes() if (not only or f"{b}/{paper}-{p['id']}" in only)
            and (not papers or paper in papers)]
    jobs.sort(key=lambda j: j[1])
    cache = {}

    def one(job):
        b, paper, p = job
        out = out_root / b
        out.mkdir(parents=True, exist_ok=True)
        f = out / f"{paper}-{p['id']}.json"
        if f.exists():
            return
        t = time.time()
        root = ROOT / "runs" / "bench" / paper
        c = store.connect_question(root)
        with lock:
            if paper not in cache:
                cache[paper] = pages(c)
        rec = answer(c, p["q"], cache[paper], title=direct.TITLES[paper])
        rec.update(arm=ARM, run=run, bench=b, paper=paper, probe=p["id"], cat=p["cat"], expect=p["expect"], trap=p.get("trap"),
                   question=p["q"], model=MODEL, seconds=round(time.time() - t, 1))
        f.write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
        pt = rec["pointers"]
        log(f"done  {b:15} {paper}-{p['id']:3} pages={len(rec['pages'])} pointed={len(pt['pointed'])} not_in_passages={pt['not_in_passages']} {time.time() - t:.0f}s")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))


def corpus_question(paper, q):
    """A single-paper question asked of the corpus: it names its paper, as bench-llama/run.py's corpus arm does."""
    return f'About the document "{TITLES[paper]}" ({paper}): {q}'


CORPUS_ARMS = {"leads": "llama-hybrid-corpus", "bm25": "llama-hybrid-corpus-bm25", "leads-text": "llama-hybrid-corpus-text"}
PLAN = HERE / "jev-pick"


def frozen_questions(stage):
    """The question keys the frozen plan (jev-pick/PLAN.md) names for this stage; refuses if the plan changed."""
    import hashlib
    for line in (PLAN / "frozen.sha256").read_text().splitlines():
        digest, name = line.split()
        if hashlib.sha256((PLAN / name).read_bytes()).hexdigest() != digest:
            raise SystemExit(f"jev-pick/{name} changed since it was frozen")
    return json.loads((PLAN / "questions.json").read_text())[f"stage{stage}"]


def run_corpus(workers, runs, ways, stage):
    """The single-paper probes on the 10-paper corpus (each naming its paper), only those the frozen plan lists for
    this stage; every way and run of a question are queued together, so a question's answers complete together."""
    sys.path.insert(0, str(ROOT / "experiments" / "bench-llama"))
    import run as bench
    keys = set(frozen_questions(stage))
    probes = {f"{b}/{paper}-{p['id']}": (b, paper, p) for b, paper, p in bench.probes()}
    assert keys <= set(probes), keys - set(probes)
    root = ROOT / "runs" / "papers-corpus"
    pgs = pages(store.connect_question(root))
    jobs = [(k, r, w) for k in sorted(keys, key=lambda k: (probes[k][1], k)) for r in runs for w in ways]

    def one(job):
        k, run, way = job
        b, paper, p = probes[k]
        arm = CORPUS_ARMS[way]
        out = ROOT / "experiments" / "bench-llama" / "answers" / f"{arm}-r{run}" / b
        out.mkdir(parents=True, exist_ok=True)
        f = out / f"{paper}-{p['id']}.json"
        if f.exists():
            return
        t = time.time()
        q = corpus_question(paper, p["q"])
        rec = answer(store.connect_question(root), q, pgs, way=way)
        rec.update(arm=arm, run=run, bench=b, paper=paper, probe=p["id"], cat=p["cat"], expect=p["expect"],
                   trap=p.get("trap"), question=p["q"], asked=q, model=MODEL, stage=stage, seconds=round(time.time() - t, 1),
                   pages_of_paper=sum(1 for d, _ in rec["pages"] if d == paper))
        f.write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
        log(f"done  {arm}-r{run} {k:32} pages={len(rec['pages'])} own={rec['pages_of_paper']} {time.time() - t:.0f}s")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))


if __name__ == "__main__":
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 6
    if sys.argv[1] == "corpus":
        # hybrid.py corpus --stage 1 --ways leads,bm25 --runs 1,2,3   (stage 2: --ways leads-text, alone in its process)
        ways = sys.argv[sys.argv.index("--ways") + 1].split(",")
        assert set(ways) <= set(CORPUS_ARMS), ways
        if "leads-text" in ways:
            assert ways == ["leads-text"], "leads-text patches ugrc.leads for the whole process: run it alone"
            for name, fn in JEV_OFF.items():
                setattr(leads, name, fn)
        runs = [int(x) for x in sys.argv[sys.argv.index("--runs") + 1].split(",")]
        stage = int(sys.argv[sys.argv.index("--stage") + 1])
        log(f"== corpus stage {stage}, ways {ways}, runs {runs}")
        run_corpus(workers, runs, ways, stage)
        log("all done")
        sys.exit(0)
    only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
    runs = [int(x) for x in sys.argv[sys.argv.index("--runs") + 1].split(",")] if "--runs" in sys.argv else [1]
    papers = sys.argv[sys.argv.index("--papers") + 1].split(",") if "--papers" in sys.argv else None
    if "--pick" in sys.argv:
        PICK = sys.argv[sys.argv.index("--pick") + 1]
        assert PICK in ("leads", "bm25"), PICK
        ARM = "llama-hybrid" if PICK == "leads" else "llama-hybrid-bm25"
    for run in runs:
        log(f"== {ARM} run {run}")
        if sys.argv[1] == "cross":
            run_cross(workers, only, run)
        else:
            run_bench(workers, only, run, papers)
    log("all done")
