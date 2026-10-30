"""More papers (PLAN.md): the 10-paper library grown with arXiv battery papers, to 20 and 40 papers. Llama 3.1 8B,
one free reply per question, the 140 corpus questions (their papers stay the 10 corpus papers; the arXiv papers are
added to every library and asked about by no question).

    python experiments/scaling-more/run.py libraries                -> libraries.json (needs LLAMA_URL)
    python experiments/scaling-more/run.py show ARM KEY             the prompt one question gets (no model call)
    LLAMA_URL=<server>/v1 LLAMA_KEY=... python experiments/scaling-more/run.py answer [--arms a,b] [--workers 6]

Arms (PLAN.md):
  llama-more-facts-L20 / -L40   every library paper in the condensed form (experiments/scaling's facts form)
  llama-more-pages-L40          pages picked by BM25 from every library paper's pages rendered from its atoms, as the
                                hybrid renders them (tables row by row), up to BUDGET tokens
  llama-more-factpages-L40      pages picked the same way from every library paper's condensed form, same budget
"""
import hashlib
import importlib.util
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "bench-llama"))
from ugrc import store  # noqa: E402
import direct  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scaling = _load("scaling_run", ROOT / "experiments" / "scaling" / "run.py")
hybrid = _load("hybrid_run", ROOT / "experiments" / "bench-cross" / "hybrid.py")
cr = scaling.cr

URL = os.environ.get("LLAMA_URL", "").rstrip("/")
MODEL = scaling.MODEL
OUT = ROOT / "experiments" / "bench-llama" / "answers"
CORPUS = scaling.CORPUS
EXTRA = json.loads((HERE / "papers.json").read_text())          # [{"id", "title", ...}] in the frozen order
TITLES = dict(direct.TITLES) | {p["id"]: p["title"] for p in EXTRA}
BUDGET = 24_000                                                  # tokens of picked pages, as the hybrid
FIT = 120_000                                                    # tokens of documents a prompt may hold
ARMS = {"llama-more-facts-L20": ("facts", 20), "llama-more-facts-L40": ("facts", 40),
        "llama-more-pages-L40": ("pages", 40), "llama-more-factpages-L40": ("factpages", 40)}
FORM = {
    "facts": scaling.FORM["facts"],
    "pages": ("Pages picked from the {n} documents of a library by a keyword search on the question are below, "
              "page by page, with tables written row by row."),
    "factpages": ("Pages picked from the {n} documents of a library by a keyword search on the question are below, "
                  "condensed: the sentences that state a value (other sentences are left out), then the page's tables "
                  "row by row and facts read from its figures."),
}
lock = threading.Lock()


def paper_dir(p):
    return ROOT / "runs" / ("bench" if p in direct.TITLES else "arxiv") / p


def connect(p):
    con = store.connect_question(paper_dir(p))
    assert store.has_clauses(con), p
    return con


_cache = {}


def condensed(p):
    if ("facts", p) not in _cache:
        _cache[("facts", p)] = scaling.condensed(connect(p), "facts")
    return _cache[("facts", p)]


def condensed_pages(p):
    """{page: text} of the condensed form, one entry per '=== page N ===' block."""
    out = {}
    for block in condensed(p).split("\n\n=== page "):
        head, _, body = block.partition("\n")
        n = int(head.replace("=== page ", "").replace(" ===", "").strip())
        out[n] = body
    return out


def atom_pages(p):
    if ("pages", p) not in _cache:
        pgs = hybrid.pages(connect(p))
        _cache[("pages", p)] = {k[1]: v["text"].split("\n", 1)[1] if "\n" in v["text"] else "" for k, v in pgs.items()
                                if k[1] is not None}
    return _cache[("pages", p)]


def tokens(text):
    scaling.URL, scaling.KEY = URL, os.environ.get("LLAMA_KEY")
    return scaling.tokens(text)


def query(paper, q):
    return f'About the document "{TITLES[paper]}": {q}'


def pick(question, docs, form):
    """BM25 over every page of every library document (the hybrid's own bm25), best first, until BUDGET tokens."""
    pages = {}
    for d in docs:
        src = atom_pages(d) if form == "pages" else condensed_pages(d)
        for n, body in src.items():
            if body.strip():
                pages[(d, n)] = f"=== {TITLES[d]}, page {n} ===\n{body}"
    chosen, total = [], 0
    for k in hybrid.bm25(question, pages):
        size = len(pages[k]) / 3.6
        if total + size <= BUDGET:
            chosen.append(k)
            total += size
    rank = {d: i for i, d in enumerate(docs)}
    chosen.sort(key=lambda k: (rank[k[0]], k[1]))
    return [(k, pages[k]) for k in chosen]


def build_libraries():
    """Each corpus paper's library order: the other 9 corpus papers (as experiments/scaling ordered them), then the
    arXiv papers shuffled by a seed made from the paper. L20 = the paper, 9 corpus papers and the first 10 arXiv papers;
    L40 = all. Prompt order is a seeded shuffle; a library whose condensed form exceeds FIT keeps the paper and drops
    papers from the end of its order until it fits (the picking arms search the whole library, "L40-all")."""
    lib0 = json.loads((ROOT / "experiments" / "scaling" / "libraries.json").read_text())
    ids = [p["id"] for p in EXTRA]
    toks = {p: tokens(condensed(p)) for p in CORPUS + ids}
    out = {"fit_tokens": FIT, "budget_tokens": BUDGET, "facts_tokens": toks, "documents": {}}
    for target in CORPUS:
        extras = list(ids)
        random.Random(f"scaling-more:{target}").shuffle(extras)
        order = lib0["order"][target] + extras
        for level in (20, 40):
            members = order[:level - 1]
            everything = [target] + members                  # the picking arms search all of it
            random.Random(f"scaling-more:{target}:L{level}:order").shuffle(everything)
            out["documents"].setdefault(f"L{level}-all", {})[target] = everything
            while toks[target] + sum(toks[m] for m in members) > FIT:
                members = members[:-1]                       # the condensed-all arms hold what fits
            docs = [d for d in everything if d == target or d in members]
            out["documents"].setdefault(f"L{level}", {})[target] = docs
    (HERE / "libraries.json").write_text(json.dumps(out, indent=1) + "\n")
    for level in ("L20", "L40", "L40-all"):
        n = [len(v) for v in out["documents"][level].values()]
        t = [sum(toks[d] for d in v) for v in out["documents"][level].values()]
        print(f"{level}: papers {min(n)}-{max(n)}, condensed tokens {min(t):,}-{max(t):,}")


def frozen():
    for line in (HERE / "frozen.sha256").read_text().splitlines():
        if len(line.split()) != 2:
            continue
        digest, name = line.split()
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != digest:
            raise SystemExit(f"scaling-more/{name} changed since it was frozen")
    return json.loads((HERE / "libraries.json").read_text())


def prompt(arm, paper, q, lib):
    form, level = ARMS[arm]
    docs = lib["documents"][f"L{level}" if form == "facts" else f"L{level}-all"][paper]
    title = TITLES[paper]
    if form == "facts":
        system = scaling.SYSTEM.format(title=title, form=FORM["facts"].format(among=f" among {len(docs)} documents"))
        body = "\n\n".join(f'<document title="{TITLES[d]}">\n{condensed(d)}\n</document>' for d in docs)
        shown = docs
    else:
        picked = pick(query(paper, q), docs, form)
        system = scaling.SYSTEM.format(title=title, form=FORM[form].format(n=len(docs)))
        body = "\n\n".join(text for _, text in picked)
        shown = [list(k) for k, _ in picked]
    return system, f'{body}\n\nQuestion (about "{title}"): {q}', docs, shown


def answer(arms, workers):
    import run as bench
    lib = frozen()
    keys = json.loads((ROOT / "experiments" / "scaling" / "questions.json").read_text())["stage1"]
    probes = {f"{b}/{paper}-{p['id']}": (b, paper, p) for b, paper, p in bench.probes()}
    for p in CORPUS + [x["id"] for x in EXTRA]:
        condensed(p)
        atom_pages(p)
    nums = {p: cr.printed_numbers(connect(p)) for p in CORPUS}
    jobs = [(arm, k) for arm in arms for paper in CORPUS for k in keys if probes[k][1] == paper]

    def one(job):
        arm, k = job
        b, paper, p = probes[k]
        f = OUT / f"{arm}-r1" / b / f"{paper}-{p['id']}.json"
        if f.exists():
            return
        t = time.time()
        system, user, docs, shown = prompt(arm, paper, p["q"], lib)
        resp = cr.chat(system, user)
        text = resp["choices"][0]["message"].get("content") or ""
        form, level = ARMS[arm]
        rec = {"arm": arm, "run": 1, "bench": b, "paper": paper, "probe": p["id"], "cat": p["cat"],
               "expect": p["expect"], "trap": p.get("trap"), "question": p["q"], "model": MODEL,
               "rendered": text, "finish_reason": resp["choices"][0].get("finish_reason"), "usage": resp.get("usage"),
               "turns": 1, "tool_calls": 0, "door_refusals": [], "citations": [], "runs": [], "trace": [],
               "numbers_not_in_paper": sorted({cr._n(x) for x in cr.NUM.findall(text)} - nums[paper] - {""}),
               "library": {"form": form, "level": level, "documents": docs, "shown": shown,
                           "target_shown": any((s == paper) if isinstance(s, str) else (s[0] == paper) for s in shown)},
               "prompt": {"style": f"scaling-more:{form}", "system": system,
                          "user_sha256": hashlib.sha256(user.encode()).hexdigest(), "user_chars": len(user)},
               "sampling": {"temperature": cr.llm.TEMPERATURE, "top_p": cr.llm.TOP_P, "max_tokens": cr.llm.MAX_OUTPUT},
               "seconds": round(time.time() - t, 1)}
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(rec, indent=2, ensure_ascii=False))
        with lock:
            print(f"done  {arm:26} {k:40} {rec['usage'].get('prompt_tokens') if rec['usage'] else '?':>7} tok "
                  f"{time.time() - t:4.0f}s", flush=True)

    print(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} start: {len(jobs)} jobs", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))
    print(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} end", flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "libraries":
        build_libraries()
    elif cmd == "show":
        import run as bench
        arm, key = sys.argv[2], sys.argv[3]
        b, paper, p = next((b, pa, p) for b, pa, p in bench.probes() if f"{b}/{pa}-{p['id']}" == key)
        s, u, docs, shown = prompt(arm, paper, p["q"], json.loads((HERE / "libraries.json").read_text()))
        print(s, "\n----\n", u[:3000], "\n...\n", u[-1500:], "\n---- shown:", shown)
    elif cmd == "answer":
        arms = sys.argv[sys.argv.index("--arms") + 1].split(",") if "--arms" in sys.argv else list(ARMS)
        assert set(arms) <= set(ARMS), arms
        answer(arms, int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 6)
    else:
        raise SystemExit(__doc__)
