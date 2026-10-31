"""The library test (PLAN.md): Llama 3.1 8B answers each question with a library of 10 chemical-engineering papers in
view and has to find the right paper itself. The question does not name its paper.

    python experiments/library/run.py build              -> questions.json, libraries.json (no model)
    python experiments/library/run.py sizes              no model: prompt sizes per library and arm
    python experiments/library/run.py show ARM KEY       no model: the prompt one question gets
    LLAMA_URL=<server>/v1 LLAMA_KEY=... python experiments/library/run.py answer --libraries L1 [--arms facts,prose,pages]
        [--workers 8]

Arms (answers/<arm>-r1/<set>__<paper>-<id>.json; a record that exists is skipped, so a run resumes):
  facts   every library paper in the facts form (experiments/scaling's condensed clause base, as in cheme and cheme2).
  prose   the same documents, then the number-free sentences of the 10 papers that best match the question (BM25, the
          prose test's limits: at most 30 sentences and 5,000 characters), shown after the documents by paper.
  pages   pdftotext pages of the 10 papers picked by BM25 on the question, best first, up to 24,000 tokens, shown in
          library order (as experiments/scaling-more's pages arm, on pdftotext pages instead of the hybrid's).
"""
import hashlib
import importlib.util
import json
import random
import sys
import threading
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


P = _load("prose_run", ROOT / "experiments" / "prose" / "run.py")    # bm25_scores, MAX_SENTENCES, MAX_CHARS; P.C = cheme
C = P.C
scaling, hybrid, llm, store = C.scaling, C.hybrid, C.llm, C.store

SETS = {s: {"runs": ROOT / "runs" / s, "text": ROOT / "experiments" / s / "direct-text",
            "papers": ROOT / "experiments" / s / "papers.json", "probes": ROOT / "experiments" / s / "probes.json"}
        for s in ("cheme", "cheme2")}
TITLES = {f"{s}/{k}": C._title(v["title"]) for s, d in SETS.items() for k, v in json.loads(d["papers"].read_text()).items()}
ARMS = ("facts", "prose", "pages")
SIZE = 10                     # papers per library
BUDGET = 24_000               # tokens of picked pages (len / 3.6, as scaling-more)
FIT = 120_000                 # tokens of documents a prompt may hold
SYSTEM = ("You answer questions about a library of {n} documents, using only what they contain. {form} The question does "
          "not say which document it is about: find the document that answers it, and name it. Answer briefly. If you "
          "compute a number, show the calculation. If the question assumes something the documents contradict, say so. "
          "If no document holds the answer, say so.")
CONDENSED = ("The documents are below, each condensed: page by page, the sentences that state a value (other sentences "
             "are left out), then its tables row by row and facts read from its figures.")
FORM = {
    "facts": CONDENSED,
    "prose": CONDENSED + " After the documents come the few left-out sentences that best match the question, by document.",
    "pages": ("Pages picked from the documents by a keyword search on the question are below. Their text is extracted "
              "from the PDFs, and each page's header names its document."),
}
lock = threading.Lock()


def log(msg):
    with lock:
        print(msg, flush=True)


def connect(pid):
    s, paper = pid.split("/")
    con = store.connect_question(SETS[s]["runs"] / paper)
    assert store.has_clauses(con), pid
    return con


_cache = {}


def _cached(kind, pid, make):
    with lock:
        if (kind, pid) not in _cache:
            _cache[(kind, pid)] = make()
        return _cache[(kind, pid)]


def facts(pid):
    return _cached("facts", pid, lambda: scaling.condensed(connect(pid), "facts"))


def paper_text(pid):
    """The paper's pdftotext, as the cheme / cheme2 pdf arms gave it (direct-text/, made from the hash-checked PDF)."""
    s, paper = pid.split("/")
    return _cached("text", pid, lambda: (SETS[s]["text"] / f"{paper}.txt").read_text())


def numbers(pid):
    return _cached("numbers", pid, lambda: scaling.cr.printed_numbers(connect(pid)))


def others(pid):
    """{sentence id: text} of the clause-base sentences the facts form leaves out (no value Jev did not read as an
    identifier), as prose/run.py's document() finds them."""
    def make():
        con = connect(pid)
        values = {sid for sid, role in con.execute("SELECT sentence, role FROM measures").fetchall()
                  if role != "identifier"}
        rows = sorted(con.execute("SELECT id, page, text FROM sentences").fetchall(),
                      key=lambda r: scaling.cr._order(r[0]))
        return {sid: text for sid, _, text in rows if sid not in values}
    return _cached("others", pid, make)


def text_pages(pid):
    return {i + 1: pg.strip() for i, pg in enumerate(paper_text(pid).split("\f")) if pg.strip()}


def pick_sentences(question, docs):
    """BM25 over the left-out sentences of every library paper; best first until 30 sentences or 5,000 characters
    (a sentence that would pass the character limit is skipped, as in prose/run.py)."""
    pool = {(d, sid): t for d in docs for sid, t in others(d).items()}
    score = P.bm25_scores(question, pool) if pool else {}
    picked, used = [], 0
    for k in sorted(score, key=lambda k: -score[k]):
        if len(picked) >= P.MAX_SENTENCES or score[k] <= 0:
            break
        if used + len(pool[k]) > P.MAX_CHARS:
            continue
        picked.append(k)
        used += len(pool[k])
    rank = {d: i for i, d in enumerate(docs)}
    shown = sorted(picked, key=lambda k: (rank[k[0]], scaling.cr._order(k[1])))
    blocks = []
    for d in docs:
        mine = [k for k in shown if k[0] == d]
        if mine:
            blocks.append(f"[{TITLES[d]}]\n" + "\n".join(f"- {pool[k]}" for k in mine))
    return picked, used, "\n\n".join(blocks)


def pick_pages(question, docs):
    """BM25 (the hybrid's) over every pdftotext page of every library paper, best first, until BUDGET tokens."""
    pages = {(d, n): f"=== {TITLES[d]}, page {n} ===\n{body}" for d in docs for n, body in text_pages(d).items()}
    chosen, total = [], 0
    for k in hybrid.bm25(question, pages):
        size = len(pages[k]) / 3.6
        if total + size <= BUDGET:
            chosen.append(k)
            total += size
    rank = {d: i for i, d in enumerate(docs)}
    chosen.sort(key=lambda k: (rank[k[0]], k[1]))
    return [(k, pages[k]) for k in chosen]


def library_body(docs):
    return "\n\n".join(f'<document title="{TITLES[d]}">\n{facts(d)}\n</document>' for d in docs)


def prompt(arm, q, docs):
    """(system, user, extra): the documents first, so every question on a library shares their prefill."""
    system = SYSTEM.format(n=len(docs), form=FORM[arm])
    if arm == "facts":
        return system, f"{library_body(docs)}\n\nQuestion: {q}", {}
    if arm == "prose":
        picked, used, block = pick_sentences(q, docs)
        extra = {"sentences": [list(k) for k in picked], "chars": used}
        tail = f"\n\n<sentences>\n{block}\n</sentences>" if block else ""
        return system, f"{library_body(docs)}{tail}\n\nQuestion: {q}", extra
    picked = pick_pages(q, docs)
    body = "\n\n".join(text for _, text in picked)
    return system, f"{body}\n\nQuestion: {q}", {"pages": [list(k) for k, _ in picked]}


# ---------------------------------------------------------------- build (no model)

def build():
    ids = sorted(TITLES)
    assert len(ids) == 28, len(ids)
    order = list(ids)
    random.Random("library:draw").shuffle(order)
    groups = {"L1": order[:SIZE], "L2": order[SIZE:2 * SIZE], "L3": order[2 * SIZE:]}
    extra = random.Random("library:L3-extra").sample(order[:2 * SIZE], SIZE - len(groups["L3"]))
    libs = {}
    for name, asked in groups.items():
        docs = asked + (extra if name == "L3" else [])
        random.Random(f"library:{name}:order").shuffle(docs)
        libs[name] = {"documents": docs, "asked": sorted(asked)}
    sizes = {pid: {"facts_chars": len(facts(pid)), "text_chars": len(paper_text(pid)), "pages": len(text_pages(pid))}
             for pid in ids}
    (HERE / "libraries.json").write_text(json.dumps({"seed": "library:draw", "size": SIZE, "budget_tokens": BUDGET,
                                                     "libraries": libs, "papers": sizes}, indent=1) + "\n")
    reworded = json.loads((HERE / "reworded.json").read_text())["questions"]
    where = {pid: name for name, lib in libs.items() for pid in lib["asked"]}
    out = {}
    for name in libs:
        for s, d in SETS.items():
            for paper, ps in json.loads(d["probes"].read_text())["papers"].items():
                pid = f"{s}/{paper}"
                if where[pid] != name:
                    continue
                for p in ps:
                    key = f"{pid}/{p['id']}"
                    out[key] = {"library": name, "set": s, "paper": paper, "id": p["id"], "cat": p["cat"],
                                "q": reworded[key], "q_original": p["q"], "expect": p["expect"],
                                "trap": p.get("trap"), "must": p["must"], "must_not": p.get("must_not", [])}
    assert len(out) == 246, len(out)
    (HERE / "questions.json").write_text(json.dumps({"about": "Built by run.py build from reworded.json and the cheme / "
                                                     "cheme2 probes (answer keys unchanged).", "questions": out},
                                                    indent=1, ensure_ascii=False) + "\n")
    for name, lib in libs.items():
        n = sum(1 for v in out.values() if v["library"] == name)
        ft = sum(sizes[d]["facts_chars"] for d in lib["documents"]) / 3.6
        tt = sum(sizes[d]["text_chars"] for d in lib["documents"]) / 3.6
        print(f"{name}: {len(lib['documents'])} papers ({len(lib['asked'])} asked about), {n} questions; "
              f"facts ~{ft / 1000:.0f}k tokens, pdftotext ~{tt / 1000:.0f}k tokens")
        for d in lib["documents"]:
            print(f"   {'*' if d in lib['asked'] else ' '} {d:30} facts {sizes[d]['facts_chars'] / 3600:5.1f}k  "
                  f"text {sizes[d]['text_chars'] / 3600:5.1f}k  {TITLES[d][:70]}")


# ---------------------------------------------------------------- answering

def frozen():
    C._check_frozen(HERE / "frozen.sha256")
    return (json.loads((HERE / "questions.json").read_text())["questions"],
            json.loads((HERE / "libraries.json").read_text())["libraries"])


def answer_path(arm, key):
    s, paper, pid = key.split("/")
    return HERE / "answers" / f"{arm}-r1" / f"{s}__{paper}-{pid}.json"


def one(arm, key, q, docs):
    f = answer_path(arm, key)
    if f.exists():
        return
    t = time.time()
    system, user, extra = prompt(arm, q["q"], docs)
    resp = scaling.cr.chat(system, user)
    choice = resp["choices"][0]
    text = choice["message"].get("content") or ""
    target = f"{q['set']}/{q['paper']}"
    shown = sorted({k[0] for k in extra.get("pages", [])}) if arm == "pages" else list(docs)
    rec = {"arm": arm, "run": 1, "key": key, "library": q["library"], "set": q["set"], "paper": q["paper"],
           "probe": q["id"], "cat": q["cat"], "question": q["q"], "expect": q["expect"], "trap": q["trap"],
           "must": q["must"], "model": scaling.cr.MODEL, "rendered": text, "finish_reason": choice.get("finish_reason"),
           "numbers_not_in_paper": sorted({scaling.cr._n(x) for x in scaling.cr.NUM.findall(text)}
                                          - numbers(target) - {""}),
           "library_docs": list(docs), "target": target, "target_shown": target in shown, "shown_papers": shown,
           **extra,
           "prompt": {"style": f"library:{arm}", "system": system, "user_chars": len(user),
                      "user_sha256": hashlib.sha256(user.encode()).hexdigest()},
           "usage": resp.get("usage"),
           "sampling": {"temperature": llm.TEMPERATURE, "top_p": llm.TOP_P, "max_tokens": llm.MAX_OUTPUT},
           "seconds": round(time.time() - t, 1)}
    if arm == "prose":
        rec["target_sentences"] = sum(1 for d, _ in extra["sentences"] if d == target)
    if arm == "pages":
        rec["target_pages"] = sum(1 for d, _ in extra["pages"] if d == target)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    u = rec["usage"] or {}
    log(f"done  {arm:5} {key:36} prompt={u.get('prompt_tokens', '?'):>6} target_shown={rec['target_shown']!s:5} "
        f"{rec['finish_reason']} {time.time() - t:5.1f}s")


def answer(names, arms, workers):
    if not scaling.cr.URL:
        raise SystemExit("set LLAMA_URL (the server's /v1) and LLAMA_KEY")
    qs, libs = frozen()
    log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} start: libraries {names}, arms {arms}")
    for name in names:
        docs = libs[name]["documents"]
        keys = [k for k, q in qs.items() if q["library"] == name]
        for arm in arms:                       # one arm at a time, so the library's prefill stays cached
            todo = [k for k in keys if not answer_path(arm, k).exists()]
            if not todo:
                continue
            log(f"-- {name} {arm}: {len(todo)} questions")
            one(arm, todo[0], qs[todo[0]], docs)        # alone first: it fills the prefix cache
            with ThreadPoolExecutor(max_workers=workers if arm != "pages" else min(workers, 6)) as pool:
                list(pool.map(lambda k: one(arm, k, qs[k], docs), todo[1:]))
    log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} end")


def sizes():
    qs, libs = (json.loads((HERE / "questions.json").read_text())["questions"],
                json.loads((HERE / "libraries.json").read_text())["libraries"])
    for name, lib in libs.items():
        docs = lib["documents"]
        keys = [k for k, q in qs.items() if q["library"] == name]
        for arm in ARMS:
            n, hit, extra_n = [], 0, []
            for k in keys:
                system, user, extra = prompt(arm, qs[k]["q"], docs)
                n.append(len(system) + len(user))
                target = f"{qs[k]['set']}/{qs[k]['paper']}"
                if arm == "pages":
                    hit += target in {d for d, _ in extra["pages"]}
                    extra_n.append(sum(1 for d, _ in extra["pages"] if d == target))
                elif arm == "prose":
                    hit += any(d == target for d, _ in extra["sentences"])
                    extra_n.append(sum(1 for d, _ in extra["sentences"] if d == target))
                else:
                    hit += 1
            more = f"  target items mean {sum(extra_n) / len(extra_n):4.1f}" if extra_n else ""
            print(f"{name} {arm:5} questions {len(keys):3}  prompt ~{sum(n) / len(n) / 3600:5.1f}k tokens "
                  f"(max {max(n) / 3600:5.1f}k)  target paper present {hit}/{len(keys)}{more}")


if __name__ == "__main__":
    cmd = sys.argv[1:2]
    arg = lambda k, d: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d  # noqa: E731
    if cmd == ["build"]:
        build()
    elif cmd == ["sizes"]:
        sizes()
    elif cmd == ["show"]:
        arm, key = sys.argv[2], sys.argv[3]
        qs = json.loads((HERE / "questions.json").read_text())["questions"]
        libs = json.loads((HERE / "libraries.json").read_text())["libraries"]
        s, u, extra = prompt(arm, qs[key]["q"], libs[qs[key]["library"]]["documents"])
        print(s, "\n----\n", u[:2500], "\n...\n", u[-3000:], "\n----", {k: v for k, v in extra.items()})
    elif cmd == ["answer"]:
        names = arg("--libraries", "L1,L2,L3").split(",")
        arms = arg("--arms", ",".join(ARMS)).split(",")
        assert set(arms) <= set(ARMS), arms
        answer(names, arms, int(arg("--workers", "8")))
    else:
        raise SystemExit(__doc__)
