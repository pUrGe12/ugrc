"""The scaling test (PLAN.md): as the library grows from 1 to 3 to 10 papers, does a condensed clause base hold up
better than the papers' PDF text? Llama 3.1 8B, one free reply per question, no tools.

    LLAMA_URL=<server>/v1 LLAMA_KEY=... python experiments/scaling/run.py libraries     tokens per document; the
                                                       documents each arm gets for each paper -> libraries.json
    python experiments/scaling/run.py show PAPER FORM   print one paper's document in a form (text|facts|readings)
    LLAMA_URL=<server>/v1 LLAMA_KEY=... python experiments/scaling/run.py answer [--arms a,b] [--workers 6]

Forms of a paper (PLAN.md):
  text      its pdftotext, as bench-llama/direct.py gives it (direct-text/<paper>.txt)
  facts     page by page: the clause-base sentences that print a value Jev did not read as an identifier (a sentence
            whose values are all identifiers, such as a reference, and a sentence with no value are left out), then
            its tables row by row and its figure facts, as the hybrid renders them
  readings  page by page: each of those values with Jev's reading (role; property; of; by; measures) and no sentence,
            then the same tables and figure facts
Answers go to experiments/bench-llama/answers/<arm>-r1/<bench>/<paper>-<id>.json in the shape bench-llama/grade.py
reads. A record that exists is skipped, so a run resumes.
"""
import hashlib
import http.client
import importlib.util
import json
import os
import random
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "bench-llama"))
from ugrc import store  # noqa: E402
import direct  # noqa: E402  (TITLES, paper_text)

_spec = importlib.util.spec_from_file_location("clause_reasoning_run", ROOT / "experiments" / "clause-reasoning" / "run.py")
cr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cr)                      # _order, _offset, _reading, printed_numbers, NUM, _n, chat

URL = os.environ.get("LLAMA_URL", "").rstrip("/")
KEY = os.environ.get("LLAMA_KEY")
MODEL = os.environ.get("LLAMA_MODEL", "llama-3.1-8b-instruct")
OUT = ROOT / "experiments" / "bench-llama" / "answers"
CORPUS = sorted(p for p in direct.TITLES if p != "cai2026")
BUDGET = 120_000                                  # tokens of documents the text arm may hold (as llama-direct-ctx120k)
ARMS = {"llama-scale-text-L1": ("text", 1), "llama-scale-text-L3": ("text", 3), "llama-scale-text-L10": ("text", 10),
        "llama-scale-facts-L1": ("facts", 1), "llama-scale-facts-L3": ("facts", 3),
        "llama-scale-facts-L10": ("facts", 10), "llama-scale-readings-L10": ("readings", 10)}
FORMS = ("text", "facts", "readings")

SYSTEM = ('You answer questions about one document, "{title}", using only what that document contains. {form} Answer '
          "briefly. If you compute a number, show the calculation. If the question assumes something the document "
          "contradicts, say so. If the document does not hold the answer, say so.")
FORM = {
    "text": "Its text, extracted from the PDF, is below{among}.",
    "facts": ("It is below{among}, condensed: page by page, the sentences that state a value (other sentences are left "
              "out), then its tables row by row and facts read from its figures."),
    "readings": ("It is below{among}, condensed: page by page, each value its sentences state, with what a classifier "
                 "read it to be (its role: result, setting, background or count; what property it is; what it is of; "
                 "by what method; what it measures; the readings can be wrong; the sentences themselves are left "
                 "out), then its tables row by row and facts read from its figures."),
}
lock = threading.Lock()


def log(msg):
    with lock:
        print(msg, flush=True)


def connect(paper):
    con = store.connect_question(ROOT / "runs" / "bench" / paper)
    assert store.has_clauses(con), paper
    return con


def _tables_and_figures(con, pages):
    q = lambda sql, args=(): con.execute(sql, list(args)).fetchall()  # noqa: E731
    heads = {}
    for tid, h in q("SELECT table_id, header FROM table_columns ORDER BY table_id, col_no"):
        heads.setdefault(tid, []).append(h or "")
    for tid, page, label, cap in q("SELECT id, page, label, caption FROM tables ORDER BY page, id"):
        out = pages.setdefault(page, [])
        out.append(f"{label or 'Table'}. {cap or ''}" + (f"\nColumns: {' | '.join(heads[tid])}" if tid in heads else ""))
        rows = {}
        for r, t in q("SELECT row_no, text FROM cells WHERE table_id = ? ORDER BY row_no, col_no", [tid]):
            rows.setdefault(r, []).append(t or "")
        out += [" | ".join(cells) for _, cells in sorted(rows.items())]
    for fid, page, label in q("SELECT id, page, label FROM figures WHERE label IS NOT NULL ORDER BY page, id"):
        for st, v, u in q("SELECT statement, value, unit FROM figure_facts WHERE figure_id = ? ORDER BY fact_no", [fid]):
            pages.setdefault(page, []).append(f"({label}, read from the image) {st}" + (f" ({v} {u or ''})" if v is not None else ""))


def condensed(con, form):
    """A paper in the facts or readings form (module docstring)."""
    values = {}
    for mid, sid, text, role, prop, about, method, quantity in con.execute(
            "SELECT id, sentence, text, role, property, about, method, quantity FROM measures").fetchall():
        if role != "identifier":
            values.setdefault(sid, []).append((mid, text, (role, prop, about, method, quantity)))
    pages = {}
    for sid, page, text in sorted(con.execute("SELECT id, page, text FROM sentences").fetchall(),
                                  key=lambda r: cr._order(r[0])):
        if sid not in values:
            continue
        out = pages.setdefault(page, [])
        if form == "facts":
            out.append(f"- {text}")
        else:
            out += [f"- value {v!r}: {cr._reading(m)}" for _, v, m in sorted(values[sid], key=lambda x: cr._offset(x[0]))]
    _tables_and_figures(con, pages)
    return "\n\n".join(f"=== page {p} ===\n" + "\n".join(lines) for p, lines in sorted(pages.items()))


_docs = {}


def document(paper, form):
    if (paper, form) not in _docs:
        _docs[(paper, form)] = direct.paper_text(paper)[0] if form == "text" else condensed(connect(paper), form)
    return _docs[(paper, form)]


def tokens(text):
    req = urllib.request.Request(URL.removesuffix("/v1") + "/tokenize", data=json.dumps(
        {"model": MODEL, "prompt": text}).encode(), headers={"Content-Type": "application/json",
                                                             **({"Authorization": f"Bearer {KEY}"} if KEY else {})})
    for attempt in range(5):                     # the reply lists every token id; a long one is sometimes cut off
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())["count"]
        except (OSError, ValueError, http.client.HTTPException):
            if attempt == 4:
                raise
            time.sleep(2 + attempt * 3)


def build_libraries():
    """Each paper's library order (the other 9 corpus papers, shuffled by a seed made from the paper), the documents
    each arm gets in prompt order, and every document's length in the model's tokens."""
    toks = {p: {f: tokens(document(p, f)) for f in FORMS} for p in CORPUS}
    lib = {"budget_tokens": BUDGET, "tokens": toks, "order": {}, "documents": {a: {} for a in ARMS}}
    for p in CORPUS:
        others = [x for x in CORPUS if x != p]
        random.Random(f"scaling:{p}").shuffle(others)
        lib["order"][p] = others
        for arm, (form, level) in ARMS.items():
            chosen = others[:level - 1]
            if form == "text" and level == 10:          # the target, then whole papers in library order while they fit
                chosen, total = [], toks[p]["text"]
                for x in others:
                    if total + toks[x]["text"] <= BUDGET:
                        chosen.append(x)
                        total += toks[x]["text"]
            docs = list(chosen)
            docs.insert(random.Random(f"scaling:{p}:{form if form == 'text' and level == 10 else 'all'}:L{level}:slot")
                        .randrange(len(docs) + 1), p)
            lib["documents"][arm][p] = docs
    (HERE / "libraries.json").write_text(json.dumps(lib, indent=1) + "\n")
    for arm in ARMS:
        form = ARMS[arm][0]
        sizes = [sum(toks[d][form] for d in lib["documents"][arm][p]) for p in CORPUS]
        n = [len(lib["documents"][arm][p]) for p in CORPUS]
        print(f"{arm:26} papers {min(n)}-{max(n)}  document tokens {min(sizes):>7,}-{max(sizes):>7,}")


def frozen():
    for line in (HERE / "frozen.sha256").read_text().splitlines():
        if len(line.split()) != 2:                  # the date line
            continue
        digest, name = line.split()
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != digest:
            raise SystemExit(f"scaling/{name} changed since it was frozen")
    return json.loads((HERE / "questions.json").read_text())["stage1"], json.loads((HERE / "libraries.json").read_text())


def prompt(arm, paper, question, lib):
    form, _ = ARMS[arm]
    docs = lib["documents"][arm][paper]
    among = f" among {len(docs)} documents" if len(docs) > 1 else ""
    system = SYSTEM.format(title=direct.TITLES[paper], form=FORM[form].format(among=among))
    body = "\n\n".join(f'<document title="{direct.TITLES[d]}">\n{document(d, form)}\n</document>' for d in docs)
    return system, f'{body}\n\nQuestion (about "{direct.TITLES[paper]}"): {question}', docs


def answer(arms, workers):
    import run as bench                            # bench-llama/run.py: probes()
    keys, lib = frozen()
    probes = {f"{b}/{paper}-{p['id']}": (b, paper, p) for b, paper, p in bench.probes()}
    assert set(keys) <= set(probes)
    nums = {p: cr.printed_numbers(connect(p)) for p in CORPUS}
    for p in CORPUS:                                # render every document once, before the threads start
        for f in FORMS:
            document(p, f)
    # an arm's questions on one paper run together, so the server reuses the prefill of their shared documents
    jobs = [(arm, k) for arm in arms for paper in CORPUS for k in keys if probes[k][1] == paper]

    def one(job):
        arm, k = job
        b, paper, p = probes[k]
        out = OUT / f"{arm}-r1" / b
        f = out / f"{paper}-{p['id']}.json"
        if f.exists():
            return
        t = time.time()
        system, user, docs = prompt(arm, paper, p["q"], lib)
        resp = cr.chat(system, user)
        text = resp["choices"][0]["message"].get("content") or ""
        form, level = ARMS[arm]
        rec = {"arm": arm, "run": 1, "bench": b, "paper": paper, "probe": p["id"], "cat": p["cat"],
               "expect": p["expect"], "trap": p.get("trap"), "question": p["q"], "model": MODEL,
               "rendered": text, "finish_reason": resp["choices"][0].get("finish_reason"), "usage": resp.get("usage"),
               "turns": 1, "tool_calls": 0, "door_refusals": [], "citations": [], "runs": [], "trace": [],
               "numbers_not_in_paper": sorted({cr._n(x) for x in cr.NUM.findall(text)} - nums[paper] - {""}),
               "library": {"form": form, "level": level, "documents": docs, "target_slot": docs.index(paper),
                           "document_tokens": sum(lib["tokens"][d][form] for d in docs)},
               "prompt": {"style": f"scaling:{form}", "system": system,
                          "user_sha256": hashlib.sha256(user.encode()).hexdigest(), "user_chars": len(user)},
               "sampling": {"temperature": cr.llm.TEMPERATURE, "top_p": cr.llm.TOP_P, "max_tokens": cr.llm.MAX_OUTPUT},
               "seconds": round(time.time() - t, 1)}
        out.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(rec, indent=2, ensure_ascii=False))
        log(f"done  {arm:26} {k:40} {rec['usage'].get('prompt_tokens') if rec['usage'] else '?':>7} tok "
            f"{time.time() - t:4.0f}s")

    log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} start: {len(jobs)} jobs, arms {arms}")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))
    log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} end")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "show":
        print(document(sys.argv[2], sys.argv[3]))
    elif cmd == "libraries":
        build_libraries()
    elif cmd == "answer":
        arms = sys.argv[sys.argv.index("--arms") + 1].split(",") if "--arms" in sys.argv else list(ARMS)
        assert set(arms) <= set(ARMS), arms
        answer(arms, int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 6)
    else:
        raise SystemExit(__doc__)
