"""Which pages would the hybrid hand the model, under each way of picking them? No model is called.

    python experiments/bench-cross/retrieval.py [--budgets 4000,8000,16000,24000]

Three ways of picking pages (hybrid.pick, with the page budget in tokens):
  bm25        pages ranked by BM25 against the question
  leads-text  the pages of the leads first, then BM25; the leads found from the sentences' own words only: the clause
              base's readings (what each value is of, by what method, what it measures, its unit) and the aliases the
              judge accepted are left out. The same search code as ugrc.leads, without Jev's part.
  leads       the pages of the leads as ugrc finds them (with Jev's readings and aliases), then BM25: the hybrid today

Three question sets:
  single    the 154 single-paper questions, each on its own paper (runs/bench/<paper>)
  corpus    the same questions on the 10-paper corpus, naming their paper as bench-llama/run.py does (140; cai2026 is
            not in the corpus)
  cross     the 33 cross-paper questions on the corpus

For each question, set, budget and way: the pages picked, whether every page the answer key cites is among them,
and whether two ways picked exactly the same pages (then their prompts are identical, and so is what the model
sees: a question like that cannot show a difference between them, only run-to-run noise).
"""
import collections
import json
import sys
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "experiments" / "bench-llama"))
from ugrc import leads, store  # noqa: E402
import hybrid  # noqa: E402

WAYS = ("bm25", "leads-text", "leads")
BUDGETS = [int(x) for x in sys.argv[sys.argv.index("--budgets") + 1].split(",")] if "--budgets" in sys.argv \
    else [4000, 8000, 16000, 24000]
OUT = HERE / "retrieval.json"


@contextmanager
def without_jev():
    """hybrid.JEV_OFF applied to ugrc.leads for the block (this script runs in one thread)."""
    saved = {name: getattr(leads, name) for name in hybrid.JEV_OFF}
    for name, fn in hybrid.JEV_OFF.items():
        setattr(leads, name, fn)
    try:
        yield
    finally:
        for name, fn in saved.items():
            setattr(leads, name, fn)


_find, _bm25, _memo = leads.find, hybrid.bm25, {}


def _cached_find(con, q):
    k = ("find", id(con), q, leads._reading_text is hybrid._no_readings)
    if k not in _memo:
        _memo[k] = _find(con, q)
    return _memo[k]


def _cached_bm25(q, docs):
    k = ("bm25", q, len(docs), next(iter(docs)))
    if k not in _memo:
        _memo[k] = _bm25(q, docs)
    return _memo[k]


leads.find, hybrid.bm25 = _cached_find, _cached_bm25     # neither depends on the budget: computed once per question


def picked(con, q, pgs, way, budget):
    hybrid.BUDGET = budget
    hybrid.PICK = "bm25" if way == "bm25" else "leads"
    if way == "leads-text":
        with without_jev():
            chosen, _ = hybrid.pick(con, q, pgs)
    else:
        chosen, _ = hybrid.pick(con, q, pgs)
    return [list(k) for k in chosen]


def key_pages(expect, papers, default=None):
    if "grade" not in _memo:
        import importlib.util
        spec = importlib.util.spec_from_file_location("cross_grade", HERE / "grade.py")
        g = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(g)
        _memo["grade"] = g
    return _memo["grade"].key_pages(expect, papers, default)


def questions():
    sys.path.insert(0, str(ROOT / "experiments" / "bench-llama"))
    import run as bench
    corpus_papers = [d.name for d in (ROOT / "runs" / "bench").iterdir()]
    for b, paper, p in bench.probes():
        kp = sorted(key_pages(p["expect"], [paper], default=paper))
        yield "single", f"{b}/{paper}-{p['id']}", p, ROOT / "runs" / "bench" / paper, p["q"], paper, kp
        if paper != "cai2026":
            q = hybrid.corpus_question(paper, p["q"])
            yield "corpus", f"{b}/{paper}-{p['id']}", p, ROOT / "runs" / "papers-corpus", q, None, kp
    for p in json.loads((HERE / "probes.json").read_text())["probes"]:
        kp = sorted(key_pages(p["expect"], corpus_papers))
        yield "cross", p["id"], p, ROOT / "runs" / "papers-corpus", p["q"], None, kp


def main():
    cons, pgs, rows = {}, {}, []
    for qset, qid, p, root, q, paper, kp in questions():
        if root not in cons:
            cons[root] = store.connect_question(root)
            pgs[root] = hybrid.pages(cons[root])
        con = cons[root]
        row = {"set": qset, "id": qid, "cat": p["cat"], "key_pages": kp, "picks": {}}
        for budget in BUDGETS:
            for way in WAYS:
                got = picked(con, q, pgs[root], way, budget)
                # a single paper's pages carry no document key; the key's pages carry the paper's
                have = {(d or paper, n) for d, n in got}
                row["picks"][f"{way}@{budget}"] = {
                    "pages": got, "all_key_pages": all(tuple(k) in have for k in kp) if kp else None,
                    "key_pages_in": sum(tuple(k) in have for k in kp)}
        rows.append(row)
        print(f"{qset:6} {qid}", file=sys.stderr, flush=True)
    OUT.write_text(json.dumps({"budgets": BUDGETS, "ways": WAYS, "rows": rows}, indent=1))
    report(rows)


def report(rows):
    for qset in ("single", "corpus", "cross"):
        rs = [r for r in rows if r["set"] == qset]
        with_key = [r for r in rs if r["key_pages"]]
        print(f"\n== {qset}: {len(rs)} questions, {len(with_key)} whose key cites pages "
              f"({sum(len(r['key_pages']) for r in with_key)} key pages)")
        print(f"{'budget':>7} | {'every key page in the prompt':^38} | {'questions where the pages differ':^44}")
        print(f"{'':>7} | " + " ".join(f"{w:>12}" for w in WAYS) + " | "
              + " ".join(f"{a + ' v ' + b:>14}" for a, b in (("bm25", "leads"), ("text", "leads"), ("bm25", "text"))))
        for budget in BUDGETS:
            cov = {w: sum(r["picks"][f"{w}@{budget}"]["all_key_pages"] is True for r in with_key) for w in WAYS}
            def differ(a, b):
                return sum(r["picks"][f"{a}@{budget}"]["pages"] != r["picks"][f"{b}@{budget}"]["pages"] for r in rs)
            print(f"{budget:>7} | " + " ".join(f"{cov[w]:>8}/{len(with_key):<3}" for w in WAYS) + " | "
                  + " ".join(f"{differ(a, b):>14}" for a, b in (("bm25", "leads"), ("leads-text", "leads"), ("bm25", "leads-text"))))
        # per question, where the two lead ways split on key-page coverage
        for budget in BUDGETS:
            wins = collections.Counter()
            for r in with_key:
                a, b = (r["picks"][f"{w}@{budget}"]["key_pages_in"] for w in ("leads-text", "leads"))
                wins["leads"] += b > a
                wins["leads-text"] += a > b
            c = collections.Counter()
            for r in with_key:
                a, b = (r["picks"][f"{w}@{budget}"]["key_pages_in"] for w in ("bm25", "leads"))
                c["leads"] += b > a
                c["bm25"] += a > b
            print(f"  @{budget}: more key pages, leads vs leads-text {wins['leads']}:{wins['leads-text']}; "
                  f"leads vs bm25 {c['leads']}:{c['bm25']}")


if __name__ == "__main__":
    if "--report" in sys.argv:
        report(json.loads(OUT.read_text())["rows"])
    else:
        main()
