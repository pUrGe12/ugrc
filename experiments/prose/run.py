"""Facts plus prose (PLAN.md): the ChemE test's facts form, plus the number-free sentences that best match the question.

    LLAMA_URL=<server>/v1 LLAMA_KEY=... python experiments/prose/run.py [--runs 1,2,3] [--workers N] [--papers a,b]
    python experiments/prose/run.py check                 # no model: with nothing added the document is the facts form
    python experiments/prose/run.py sizes                 # no model: characters added per question, per paper
    python experiments/prose/run.py show PAPER-ID         # no model: the document one question gets

Answers: answers/llama-facts-prose-r<k>/<paper>-<id>.json; a record that exists is skipped, so a run resumes.
"""
import hashlib
import importlib.util
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


C = _load("cheme_run", ROOT / "experiments" / "cheme" / "run.py")   # probes, connect, TITLES, scaling, hybrid, llm
scaling, hybrid, llm = C.scaling, C.hybrid, C.llm

ARM = "llama-facts-prose"
MAX_SENTENCES = 30
MAX_CHARS = 5000
FORM = ("It is below, condensed: page by page, the sentences that state a value, with the few other sentences that "
        "best match the question (the rest are left out), then its tables row by row and facts read from its figures.")


def bm25_scores(question, docs, k1=1.5, b=0.75):
    """hybrid.bm25's formula, returning the scores."""
    toks = {k: hybrid._words(v) for k, v in docs.items()}
    avg = sum(len(t) for t in toks.values()) / max(len(toks), 1)
    terms = set(hybrid._words(question))
    df = {t: sum(t in set(d) for d in toks.values()) for t in terms}
    score = {}
    for k, d in toks.items():
        tf = {}
        for w in d:
            if w in terms:
                tf[w] = tf.get(w, 0) + 1
        score[k] = sum(math.log(1 + (len(toks) - df[t] + 0.5) / (df[t] + 0.5)) * tf[t] * (k1 + 1)
                       / (tf[t] + k1 * (1 - b + b * len(d) / avg)) for t in tf)
    return score


def document(con, question, max_sentences=MAX_SENTENCES, max_chars=MAX_CHARS):
    """The facts form (scaling.condensed) with the best-matching sentences it leaves out put back in page order."""
    values = set()
    for sid, role in con.execute("SELECT sentence, role FROM measures").fetchall():
        if role != "identifier":                 # as scaling.condensed
            values.add(sid)
    rows = sorted(con.execute("SELECT id, page, text FROM sentences").fetchall(), key=lambda r: scaling.cr._order(r[0]))
    others = {sid: text for sid, _, text in rows if sid not in values}
    score = bm25_scores(question, others) if others else {}
    picked, used = [], 0
    for sid in sorted(score, key=lambda k: -score[k]):
        if len(picked) >= max_sentences or score[sid] <= 0:
            break
        if used + len(others[sid]) > max_chars:
            continue
        picked.append(sid)
        used += len(others[sid])
    keep = values | set(picked)
    pages = {}
    for sid, page, text in rows:
        if sid in keep:
            pages.setdefault(page, []).append(f"- {text}")
    scaling._tables_and_figures(con, pages)
    doc = "\n\n".join(f"=== page {p} ===\n" + "\n".join(lines) for p, lines in sorted(pages.items()))
    return doc, picked, used


def prompt(paper, question, doc):
    title = C.TITLES[paper]
    system = scaling.SYSTEM.format(title=title, form=FORM)
    return system, f'<document title="{title}">\n{doc}\n</document>\n\nQuestion (about "{title}"): {question}'


def answer_path(run, paper, pid):
    return HERE / "answers" / f"{ARM}-r{run}" / f"{paper}-{pid}.json"


def one(job):
    s, paper, p, run = job
    f = answer_path(run, paper, p["id"])
    if f.exists():
        return
    t = time.time()
    con = C.connect(s, paper)
    doc, picked, used = document(con, p["q"])
    system, user = prompt(paper, p["q"], doc)
    resp = scaling.cr.chat(system, user)
    choice = resp["choices"][0]
    text = choice["message"].get("content") or ""
    rec = {"arm": ARM, "run": run, "set": s, "paper": paper, "probe": p["id"], "cat": p["cat"], "question": p["q"],
           "expect": p["expect"], "trap": p.get("trap"), "must": p["must"], "model": hybrid.MODEL,
           "rendered": text, "finish_reason": choice.get("finish_reason"), "turns": 1, "tool_calls": 0,
           "numbers_not_in_paper": sorted({scaling.cr._n(x) for x in scaling.cr.NUM.findall(text)}
                                          - C.cached("numbers", s, paper) - {""}),
           "added": {"sentences": picked, "chars": used},
           "document": {"form": "facts+prose", "chars": len(doc), "sha256": hashlib.sha256(doc.encode()).hexdigest()},
           "prompt": {"style": "prose", "system": system, "user_sha256": hashlib.sha256(user.encode()).hexdigest(),
                      "user_chars": len(user)},
           "usage": resp.get("usage"),
           "sampling": {"temperature": llm.TEMPERATURE, "top_p": llm.TOP_P, "max_tokens": llm.MAX_OUTPUT},
           "seconds": round(time.time() - t, 1)}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
    u = rec.get("usage") or {}
    with C.lock:
        print(f"done  {ARM}-r{run} {paper}-{p['id']:3} prompt={u.get('prompt_tokens', '?'):>6} added={len(picked):2} "
              f"{rec.get('finish_reason')} {time.time() - t:5.1f}s", flush=True)


def check():
    """With nothing added, the document is byte for byte the facts form."""
    for s in C.SETS:
        for paper in json.loads(C.SETS[s]["probes"].read_text())["papers"]:
            con = C.connect(s, paper)
            doc, picked, _ = document(con, "", max_sentences=0)
            assert not picked and doc == scaling.condensed(con, "facts"), paper
            print(f"ok  {paper}")


def sizes():
    per, facts = {}, {}
    for s, paper, p in C.probes():
        con = C.connect(s, paper)
        doc, picked, used = document(con, p["q"])
        per.setdefault(paper, []).append((len(picked), used, len(doc)))
        facts.setdefault(paper, len(scaling.condensed(con, "facts")))
    for paper, xs in per.items():
        n = len(xs)
        print(f"{paper:16} questions {n:2}  added sentences {sum(x[0] for x in xs) / n:5.1f}  "
              f"chars {sum(x[1] for x in xs) / n:6.0f}  document {sum(x[2] for x in xs) / n / 1000:5.1f}k  "
              f"(facts {facts[paper] / 1000:5.1f}k)")


if __name__ == "__main__":
    cmd = sys.argv[1:2]
    if cmd == ["check"]:
        check()
        sys.exit(0)
    if cmd == ["sizes"]:
        sizes()
        sys.exit(0)
    if cmd == ["show"]:
        key = sys.argv[2]
        s, paper, p = next((s, pp, p) for s, pp, p in C.probes() if f"{pp}-{p['id']}" == key)
        print(document(C.connect(s, paper), p["q"])[0])
        sys.exit(0)
    if not scaling.cr.URL:
        raise SystemExit("set LLAMA_URL (the server's /v1) and LLAMA_KEY")
    arg = lambda k, d: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d  # noqa: E731
    runs = [int(x) for x in arg("--runs", "1,2,3").split(",")]
    workers = int(arg("--workers", "6"))
    papers = arg("--papers", None)
    papers = set(papers.split(",")) if papers else None
    _check_frozen = C._check_frozen
    _check_frozen(HERE / "frozen.sha256")
    jobs = [(s, paper, p, r) for s, paper, p in C.probes() if not papers or paper in papers for r in runs]
    print(f"{len(jobs)} answers: {ARM}, runs {runs}, {workers} workers", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))
    print("all done", flush=True)
