"""The benchmark (PLAN.md): four ways of answering over the whole 130-paper library, one question at a time (part 1),
and a 16-question conversation on one paper (part 2). Llama 3.1 8B answers in every arm.

  ours     keyword search (BM25 over every page of the 130 papers) picks one paper; its facts+prose form (Jev clause base)
  rag      a standard RAG: hybrid retrieval (BM25 + bge-base dense, reciprocal-rank fusion) over 200-word chunks of all
           130 papers' text, the best chunks up to BUDGET characters, by relevance, each headed by title and page
  chunks   the paper ours picks, then that paper's best chunks by the same hybrid retrieval, up to BUDGET, in page order:
           routing without the clause base
  pdf      the question's own paper (no choosing), its whole pdftotext

No model:
    python experiments/benchmark/run.py questions    questions.json: the fresh test's 80 + 80 of the big-library 388
    python experiments/benchmark/run.py chunks       chunks.jsonl: every library paper's text in 200-word windows
    python experiments/benchmark/run.py queries      queries.json: every retrieval query (then: embed.py, other venv)
    python experiments/benchmark/run.py route        routes.json: each question's paper over all 130 (and the chat's)
    python experiments/benchmark/run.py retrieve     retrieval.json: the chunks rag and chunks pick (needs dense.json.gz)
    python experiments/benchmark/run.py sizes | show ARM KEY | showchat ARM TURN
Model (LLAMA_URL, LLAMA_KEY):
    python experiments/benchmark/run.py answer [--arms ours,rag,chunks,pdf] [--workers 8]   part 1
    python experiments/benchmark/run.py solo [--workers 8]                                  part 2, each question alone, 3 runs
    python experiments/benchmark/run.py chat                                                part 2, conversations, 3 runs
"""
import gzip
import hashlib
import importlib.util
import json
import math
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
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


FR = _load("fresh_run", ROOT / "experiments" / "fresh" / "run.py")      # library of 120 + the 10 fresh papers
BL, R, L, P, C = FR.BL, FR.R, FR.L, FR.P, FR.C
scaling, llm = R.scaling, R.llm
cr = scaling.cr                                                          # chat(), MODEL, URL, KEY

ARMS = ("ours", "rag", "chunks", "pdf")
RUNS = 3                                     # part 2, per arm and mode
BUDGET = 24_000                              # characters of retrieved text: ours' facts+prose mean on the fresh test
WINDOW, STRIDE, TAIL = 200, 160, 60          # chunk words, step, a last window shorter than TAIL joins the one before
RRF_K = 60
SEED = "benchmark-2026-11-01"
CONV = json.loads((HERE / "conversation.json").read_text())
lock = threading.Lock()


def log(msg):
    with lock:
        print(msg, flush=True)


def install():
    FR.install()
    lib = BL.library()
    return sorted(set(lib) | set(FR.TITLES))                             # the 130 papers


def title(pid):
    return L.TITLES[pid]


# ---------------------------------------------------------------- part 1 questions (no model)

def build_questions():
    """All 80 fresh questions, and 80 of the big library's 388 drawn per category in proportion (largest remainder),
    each category's draw by a fixed seed."""
    fresh = FR.questions()
    big = BL.questions()
    want = 80
    cats = Counter(q["cat"] for q in big.values())
    share = {c: want * n / len(big) for c, n in cats.items()}
    take = {c: int(s) for c, s in share.items()}
    for c in sorted(share, key=lambda c: -(share[c] - take[c]))[:want - sum(take.values())]:
        take[c] += 1
    out = {}
    for key, q in fresh.items():
        out[key] = dict(q, set="fresh", source="fresh")
    for c in sorted(cats):
        keys = sorted(k for k, q in big.items() if q["cat"] == c)
        for key in random.Random(f"{SEED}:{c}").sample(keys, take[c]):
            out[key] = {k: big[key][k] for k in ("set", "paper", "id", "cat", "q", "expect", "trap", "must")} \
                | {"must_not": big[key].get("must_not", []), "source": "big-library"}
    (HERE / "questions.json").write_text(json.dumps({
        "about": "run.py questions: the fresh test's 80 questions and 80 of the big-library test's 388, drawn per "
                 f"category in proportion with seed {SEED!r}; wording and keys unchanged", "questions": out},
        indent=1, ensure_ascii=False) + "\n")
    print(Counter(q["source"] for q in out.values()), Counter(q["cat"] for q in out.values()))


def questions():
    return json.loads((HERE / "questions.json").read_text())["questions"]


def target(q):
    return f"{q['set']}/{q['paper']}"


# ---------------------------------------------------------------- chunks and queries (no model)

def build_chunks():
    """Each page's pdftotext words in windows of WINDOW, every STRIDE words; a page's last short window joins the one
    before. Chunks never cross a page."""
    rows = []
    for pid in install():
        for page, body in L.text_pages(pid).items():
            words = body.split()
            starts = list(range(0, max(len(words) - WINDOW, 0) + 1, STRIDE)) or [0]
            if starts[-1] + WINDOW < len(words):
                starts.append(starts[-1] + STRIDE)
            spans = [[s, min(s + WINDOW, len(words))] for s in starts]
            if len(spans) > 1 and spans[-1][1] - spans[-1][0] < TAIL:
                last = spans.pop()
                spans[-1][1] = last[1]
            for a, b in spans:
                if b > a:
                    rows.append({"i": len(rows), "paper": pid, "page": page, "w0": a, "w1": b,
                                 "text": " ".join(words[a:b])})
    with open(HERE / "chunks.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} chunks from {len({r['paper'] for r in rows})} papers; "
          f"mean {sum(len(r['text']) for r in rows) / len(rows):,.0f} characters")


def chunks():
    return [json.loads(line) for line in open(HERE / "chunks.jsonl")]


def chat_queries():
    """Part 2's retrieval queries per turn: the content query is this question and the one before (a follow-up names
    little); the routing query is every question so far (the conversation's subject)."""
    qs = [q["chat"] for q in CONV["questions"]]
    return {i + 1: {"content": " ".join(qs[max(i - 1, 0):i + 1]), "route": " ".join(qs[:i + 1])} for i in range(len(qs))}


def build_queries():
    out = {f"bench:{k}": q["q"] for k, q in questions().items()}
    out |= {f"solo:{q['n']}": q["solo"] for q in CONV["questions"]}
    out |= {f"chat:{n}": v["content"] for n, v in chat_queries().items()}
    (HERE / "queries.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(out)} queries")


# ---------------------------------------------------------------- routing (no model)

def build_routes():
    lib, ix = FR.index()
    allp = set(install())
    out = {}
    for key, q in questions().items():
        order, unsure = FR.summary(FR.ranked(ix, q["q"], allp))
        out[key] = {"target": target(q), "routed": order[0], "routed_right": order[0] == target(q),
                    "target_rank": order.index(target(q)) + 1, "unsure": unsure, "paper_order": order[:5]}
    for q in CONV["questions"]:
        order, _ = FR.summary(FR.ranked(ix, q["solo"], allp))
        out[f"solo:{q['n']}"] = {"target": CONV["paper"], "routed": order[0], "routed_right": order[0] == CONV["paper"]}
    for n, v in chat_queries().items():
        order, _ = FR.summary(FR.ranked(ix, v["route"], allp))
        out[f"chat:{n}"] = {"target": CONV["paper"], "routed": order[0], "routed_right": order[0] == CONV["paper"]}
    (HERE / "routes.json").write_text(json.dumps({"about": "run.py route: the paper of the top BM25 page over all 130 "
                                                           "library papers' pages, headed by title", "routes": out},
                                                 indent=1) + "\n")
    b = [v for k, v in out.items() if ":" not in k]
    print(f"part 1: {sum(v['routed_right'] for v in b)} of {len(b)} routed to their own paper over {len(allp)}")
    for kind in ("solo", "chat"):
        v = [r for k, r in out.items() if k.startswith(kind + ":")]
        print(f"part 2 {kind}: {sum(r['routed_right'] for r in v)} of {len(v)}")


def routes():
    return json.loads((HERE / "routes.json").read_text())["routes"]


# ---------------------------------------------------------------- retrieval (no model; dense scores from embed.py)

class ChunkIndex:
    def __init__(self, rows):
        self.rows = rows
        self.tf = [Counter(P.hybrid._words(r["text"])) for r in rows]
        self.len = [sum(c.values()) for c in self.tf]

    def bm25(self, query, ids, k1=1.5, b=0.75):
        n = len(ids)
        avg = sum(self.len[i] for i in ids) / n
        terms = set(P.hybrid._words(query))
        df = {t: sum(1 for i in ids if t in self.tf[i]) for t in terms}
        return {i: sum(math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) * self.tf[i][t] * (k1 + 1)
                       / (self.tf[i][t] + k1 * (1 - b + b * self.len[i] / avg)) for t in terms if self.tf[i][t])
                for i in ids}


def fuse(ix, query, dense, ids):
    """Reciprocal-rank fusion of BM25 and dense ranks over `ids`; best first."""
    bm = ix.bm25(query, ids)
    rb = {i: r for r, i in enumerate(sorted(ids, key=lambda i: (-bm[i], i)))}
    rd = {i: r for r, i in enumerate(sorted(ids, key=lambda i: (-dense[i], i)))}
    return sorted(ids, key=lambda i: (-(1 / (RRF_K + rb[i]) + 1 / (RRF_K + rd[i])), i))


def fill(rows, ranked):
    """The best chunks while their text fits in BUDGET characters (a chunk that would not fit is skipped)."""
    out, used = [], 0
    for i in ranked:
        n = len(rows[i]["text"])
        if used + n > BUDGET:
            continue
        out.append(i)
        used += n
        if used > BUDGET - 300:
            break
    return out


def build_retrieval():
    rows = chunks()
    ix = ChunkIndex(rows)
    dense = json.loads(gzip.open(HERE / "dense.json.gz").read())
    assert dense["chunks_sha256"] == hashlib.sha256((HERE / "chunks.jsonl").read_bytes()).hexdigest()
    qtext = json.loads((HERE / "queries.json").read_text())
    rt = routes()
    by_paper = {}
    for r in rows:
        by_paper.setdefault(r["paper"], []).append(r["i"])
    everything = list(range(len(rows)))
    out = {}
    for qid, text in qtext.items():
        d = dense["scores"][qid]
        key = qid.split(":", 1)[1] if qid.startswith("bench:") else qid
        routed = rt[key]["routed"]
        out[qid] = {"rag": fill(rows, fuse(ix, text, d, everything)),
                    "chunks": fill(rows, fuse(ix, text, d, by_paper[routed])), "routed": routed}
    (HERE / "retrieval.json").write_text(json.dumps({"about": "run.py retrieve: chunk ids per query, best first; rag over "
                                                              "all chunks, chunks over the routed paper's",
                                                     "budget": BUDGET, "retrieval": out}) + "\n")
    tg = {f"bench:{k}": v["target"] for k, v in rt.items() if ":" not in k}
    hit = [qid for qid, t in tg.items() if any(rows[i]["paper"] == t for i in out[qid]["rag"])]
    own = [sum(rows[i]["paper"] == tg[q] for i in out[q]["rag"]) / len(out[q]["rag"]) for q in tg]
    print(f"rag: {len(hit)} of {len(tg)} prompts hold a chunk of the question's paper; "
          f"{sum(own) / len(own):.0%} of chunks are from it on average; "
          f"{sum(len(v['rag']) for v in out.values()) / len(out):.1f} chunks a prompt")


def retrieval():
    return json.loads((HERE / "retrieval.json").read_text())["retrieval"]


# ---------------------------------------------------------------- prompts

def system_for(form, ttl):
    return scaling.SYSTEM.format(title=ttl, form=form)


TEXT_FORM = "Its text, extracted from the PDF, is below."
CHUNK_FORM = ("Below are the passages of its text, extracted from the PDF, that best match the question, in page order "
              "(the rest is left out).")
RAG_SYSTEM = ("You answer questions using only the excerpts below. A search over a library of scientific papers "
              "retrieved them for the question; each excerpt is headed by its paper's title and page. The question is "
              "about one paper: answer from that paper's excerpts and name it. Answer briefly. If you compute a "
              "number, show the calculation. If the question assumes something the excerpts contradict, say so. If "
              "the excerpts do not hold the answer, say so.")


def passages(rows, ids):
    """A paper's chosen chunks in page order, overlapping windows of a page joined: '=== page N ===' blocks."""
    spans = {}
    for i in ids:
        r = rows[i]
        spans.setdefault(r["page"], []).append((r["w0"], r["w1"]))
    pid = rows[ids[0]]["paper"]
    pages = L.text_pages(pid)
    out = []
    for page in sorted(spans):
        words = pages[page].split()
        merged = []
        for a, b in sorted(spans[page]):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        out.append(f"=== page {page} ===\n" + "\n[...]\n".join(" ".join(words[a:b]) for a, b in merged))
    return "\n\n".join(out)


def excerpts(rows, ids):
    return "\n\n".join(f"[{title(rows[i]['paper'])}, page {rows[i]['page']}]\n{rows[i]['text']}" for i in ids)


def prompt(arm, qtext, routed, tgt, picks, rows):
    """(system, user, extra) for one question asked alone."""
    if arm == "ours":
        return R.prompt("prose", qtext, routed)
    if arm == "pdf":
        text = L.paper_text(tgt)
        return (system_for(TEXT_FORM, title(tgt)),
                f'<document title="{title(tgt)}">\n{text}\n</document>\n\nQuestion (about "{title(tgt)}"): {qtext}',
                {"source": {"tool": "pdftotext", "chars": len(text)}})
    if arm == "chunks":
        doc = passages(rows, picks["chunks"])
        return (system_for(CHUNK_FORM, title(routed)),
                f'<document title="{title(routed)}">\n{doc}\n</document>\n\nQuestion (about "{title(routed)}"): {qtext}',
                {"chunks": picks["chunks"], "chars": len(doc)})
    doc = excerpts(rows, picks["rag"])
    return RAG_SYSTEM, f"<excerpts>\n{doc}\n</excerpts>\n\nQuestion: {qtext}", {
        "chunks": picks["rag"], "papers": sorted({rows[i]["paper"] for i in picks["rag"]}), "chars": len(doc)}


# ---------------------------------------------------------------- answering, part 1 and part 2 alone

def frozen():
    install()
    C._check_frozen(ROOT / "experiments" / "fresh" / "frozen.sha256")
    C._check_frozen(HERE / "frozen.sha256")


def answer_path(part, arm, key, run=1):
    return HERE / "answers" / part / f"{arm}-r{run}" / (key.replace("/", "__") + ".json")


def numbers_outside(text, pid):
    return sorted({cr._n(x) for x in cr.NUM.findall(text)} - L.numbers(pid) - {""})


def one(part, arm, key, qtext, routed, tgt, picks, rows, run, meta):
    f = answer_path(part, arm, key, run)
    if f.exists():
        return
    t = time.time()
    system, user, extra = prompt(arm, qtext, routed, tgt, picks, rows)
    resp = cr.chat(system, user)
    choice = resp["choices"][0]
    text = choice["message"].get("content") or ""
    shown = {"ours": [routed], "chunks": [routed], "pdf": [tgt]}.get(arm, extra.get("papers"))
    rec = {"part": part, "arm": arm, "run": run, "key": key, **meta, "question": qtext, "model": cr.MODEL,
           "rendered": text, "finish_reason": choice.get("finish_reason"), "target": tgt, "routed": routed,
           "shown_papers": shown, "target_shown": tgt in shown, "numbers_not_in_paper": numbers_outside(text, tgt),
           **{k: v for k, v in extra.items() if k != "papers"},
           "prompt": {"system": system, "user_chars": len(user), "user_sha256": hashlib.sha256(user.encode()).hexdigest()},
           "usage": resp.get("usage"),
           "sampling": {"temperature": llm.TEMPERATURE, "top_p": llm.TOP_P, "max_tokens": llm.MAX_OUTPUT},
           "seconds": round(time.time() - t, 1)}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
    u = rec["usage"] or {}
    log(f"done  {part:5} {arm:6} r{run} {key:40} prompt={u.get('prompt_tokens', '?'):>6} "
        f"target_shown={rec['target_shown']!s:5} {rec['finish_reason']} {time.time() - t:5.1f}s")


def answer(arms, workers):
    if not cr.URL:
        raise SystemExit("set LLAMA_URL (the server's /v1) and LLAMA_KEY")
    frozen()
    qs, rt, rv, rows = questions(), routes(), retrieval(), chunks()
    log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} part 1: arms {arms}")
    jobs = [(arm, k) for arm in arms for k in sorted(qs, key=lambda k: (rt[k]["routed"], k))
            if not answer_path("bench", arm, k).exists()]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda j: one("bench", j[0], j[1], qs[j[1]]["q"], rt[j[1]]["routed"], target(qs[j[1]]),
                                    rv[f"bench:{j[1]}"], rows, 1,
                                    {"source": qs[j[1]]["source"], "cat": qs[j[1]]["cat"]}), jobs))
    log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} part 1 end")


def solo(workers):
    if not cr.URL:
        raise SystemExit("set LLAMA_URL (the server's /v1) and LLAMA_KEY")
    frozen()
    rt, rv, rows = routes(), retrieval(), chunks()
    jobs = [(arm, q, run) for run in range(1, RUNS + 1) for arm in ARMS for q in CONV["questions"]]
    log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} part 2 solo: {len(jobs)} answers")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda j: one("solo", j[0], f"q{j[1]['n']:02d}", j[1]["solo"], rt[f"solo:{j[1]['n']}"]["routed"],
                                    CONV["paper"], rv[f"solo:{j[1]['n']}"], rows, j[2], {"n": j[1]["n"],
                                                                                          "cat": j[1]["cat"]}), jobs))
    log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} part 2 solo end")


# ---------------------------------------------------------------- part 2: the conversations

CHAT_OURS = ("You answer a series of questions about scientific papers, using only what the documents in this "
             "conversation contain. A keyword search picks the paper for each question. Each paper is shown once, "
             "condensed: page by page, the sentences that state a value, with the few other sentences that best match "
             "the question (the rest are left out), then its tables row by row and facts read from its figures; later "
             "questions may add more of its sentences. Answer briefly. If you compute a number, show the calculation. "
             "If the question assumes something the documents contradict, say so. If the documents do not hold the "
             "answer, say so.")
CHAT_CHUNKS = ("You answer a series of questions about scientific papers, using only what the documents in this "
               "conversation contain. A keyword search picks the paper for each question. Each paper is shown as the "
               "passages of its text, extracted from the PDF, that best match the question, in page order (the rest is "
               "left out); later questions may add more of its passages. Answer briefly. If you compute a number, show "
               "the calculation. If the question assumes something the documents contradict, say so. If the documents "
               "do not hold the answer, say so.")
CHAT_RAG = ("You answer a series of questions using only the excerpts in this conversation. For each question, a search "
            "over a library of scientific papers retrieves excerpts, each headed by its paper's title and page; "
            "excerpts already shown are not repeated. The conversation is about one paper: answer from that paper's "
            "excerpts and name it. Answer briefly. If you compute a number, show the calculation. If the question "
            "assumes something the excerpts contradict, say so. If the excerpts do not hold the answer, say so.")


def chat_turn(arm, n, state, rt, rv, rows):
    """The user message for turn n of a conversation; `state` holds what the conversation has shown."""
    q = CONV["questions"][n - 1]["chat"]
    if arm == "pdf":
        if n == 1:
            text = L.paper_text(CONV["paper"])
            return f'<document title="{title(CONV["paper"])}">\n{text}\n</document>\n\nQuestion: {q}', {}
        return f"Question: {q}", {}
    routed = rt[f"chat:{n}"]["routed"]
    content = chat_queries()[n]["content"]
    if arm == "ours":
        doc, picked, _ = P.document(L.connect(routed), content)
        shown = state.setdefault("sentences", {}).setdefault(routed, None)
        if shown is None:
            state["sentences"][routed] = set(picked)
            return f'<document title="{title(routed)}">\n{doc}\n</document>\n\nQuestion: {q}', {"routed": routed,
                                                                                               "new": len(picked)}
        new = [s for s in picked if s not in shown]
        shown.update(new)
        text = dict(L.connect(routed).execute("SELECT id, text FROM sentences").fetchall())
        page = dict(L.connect(routed).execute("SELECT id, page FROM sentences").fetchall())
        block = (f'More sentences from "{title(routed)}" that match this question:\n'
                 + "\n".join(f"- (page {page[s]}) {text[s]}" for s in new) + "\n\n") if new else ""
        return f"{block}Question: {q}", {"routed": routed, "new": len(new)}
    ids = rv[f"chat:{n}"][arm]                   # chunks: over the paper routed for this turn (build_retrieval)
    seen = state.setdefault("chunks", set())
    new = [i for i in ids if i not in seen]
    seen.update(new)
    if arm == "rag":
        block = (("Excerpts retrieved for this question:\n" if n > 1 else "") + excerpts(rows, new) + "\n\n") if new else ""
        return f"{block}Question: {q}", {"new": len(new), "papers": sorted({rows[i]["paper"] for i in new})}
    first = routed not in state.setdefault("papers", set())
    state["papers"].add(routed)
    if not new:
        return f"Question: {q}", {"routed": routed, "new": 0}
    head = f'<document title="{title(routed)}">\n' if first else f'More passages from "{title(routed)}" that match this question:\n'
    tail = "\n</document>" if first else ""
    return f"{head}{passages(rows, new)}{tail}\n\nQuestion: {q}", {"routed": routed, "new": len(new)}


def chat_call(messages):
    body = json.dumps({"model": cr.MODEL, "messages": messages, "max_tokens": llm.MAX_OUTPUT,
                       "temperature": llm.TEMPERATURE, "top_p": llm.TOP_P}).encode()
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {cr.KEY}"} if cr.KEY else {})}
    last = None
    for attempt in range(llm.RETRIES + 1):
        if attempt:
            time.sleep(min(2 ** attempt, 60))
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{cr.URL}/chat/completions", data=body, headers=headers),
                                        timeout=llm.TIMEOUT_S) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read()[:300]!r}"
            if e.code == 400:
                return {"error": last}                  # e.g. the conversation no longer fits the context window
            if e.code not in llm.RETRY_CODES:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = str(e)
    raise llm.ServerError(f"the model server kept failing: {last}")


def conversation(arm, run, rt, rv, rows):
    f = answer_path("chat", arm, "conversation", run)
    if f.exists():
        return
    system = {"ours": CHAT_OURS, "chunks": CHAT_CHUNKS, "rag": CHAT_RAG,
              "pdf": system_for(TEXT_FORM, title(CONV["paper"]))}[arm]
    messages, state, turns = [{"role": "system", "content": system}], {}, []
    for q in CONV["questions"]:
        t = time.time()
        user, info = chat_turn(arm, q["n"], state, rt, rv, rows)
        messages.append({"role": "user", "content": user})
        resp = chat_call(messages)
        if "error" in resp:
            turns.append({"n": q["n"], "cat": q["cat"], "rendered": "", "error": resp["error"], **info})
            messages.pop()
            log(f"chat  {arm:6} r{run} turn {q['n']:2} ERROR {resp['error'][:120]}")
            continue
        choice = resp["choices"][0]
        text = choice["message"].get("content") or ""
        messages.append({"role": "assistant", "content": text})
        u = resp.get("usage") or {}
        turns.append({"n": q["n"], "cat": q["cat"], "question": q["chat"], "rendered": text,
                      "finish_reason": choice.get("finish_reason"), "user_chars": len(user), "usage": u,
                      "numbers_not_in_paper": numbers_outside(text, CONV["paper"]), **info,
                      "seconds": round(time.time() - t, 1)})
        log(f"chat  {arm:6} r{run} turn {q['n']:2} prompt={u.get('prompt_tokens', '?'):>6} {time.time() - t:5.1f}s")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"part": "chat", "arm": arm, "run": run, "model": cr.MODEL, "system": system,
                             "turns": turns, "messages_sha256": hashlib.sha256(json.dumps(messages).encode()).hexdigest(),
                             "sampling": {"temperature": llm.TEMPERATURE, "top_p": llm.TOP_P,
                                          "max_tokens": llm.MAX_OUTPUT}}, indent=2, ensure_ascii=False))


def chat():
    if not cr.URL:
        raise SystemExit("set LLAMA_URL (the server's /v1) and LLAMA_KEY")
    frozen()
    rt, rv, rows = routes(), retrieval(), chunks()
    log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} part 2 chat: {len(ARMS)} arms x {RUNS} runs")
    with ThreadPoolExecutor(max_workers=len(ARMS) * RUNS) as pool:      # conversations side by side, turns in order
        list(pool.map(lambda j: conversation(j[0], j[1], rt, rv, rows), [(a, r) for r in range(1, RUNS + 1) for a in ARMS]))
    log(f"== {time.strftime('%Y-%m-%dT%H:%M:%S')} part 2 chat end")


# ---------------------------------------------------------------- inspection (no model)

def sizes():
    install()
    qs, rt, rv, rows = questions(), routes(), retrieval(), chunks()
    for arm in ARMS:
        n = [sum(map(len, prompt(arm, q["q"], rt[k]["routed"], target(q), rv[f"bench:{k}"], rows)[:2])) / 3.6
             for k, q in qs.items()]
        print(f"part 1 {arm:6} tokens (chars / 3.6): mean {sum(n) / len(n):,.0f}, max {max(n):,.0f}")
    for arm in ARMS:
        state, total = {}, len(system_for(TEXT_FORM, title(CONV["paper"])))
        for q in CONV["questions"]:
            user, _ = chat_turn(arm, q["n"], state, rt, rv, rows)
            total += len(user) + 600                                       # with a typical answer
        print(f"part 2 chat {arm:6} conversation after 16 turns: about {total / 3.6:,.0f} tokens")


def show(arm, key):
    install()
    qs, rt, rv, rows = questions(), routes(), retrieval(), chunks()
    system, user, _ = prompt(arm, qs[key]["q"], rt[key]["routed"], target(qs[key]), rv[f"bench:{key}"], rows)
    print(f"SYSTEM: {system}\n\nUSER ({len(user):,} chars):\n{user[:2500]}\n...\n{user[-800:]}")


def showchat(arm, upto):
    install()
    rt, rv, rows, state = routes(), retrieval(), chunks(), {}
    for q in CONV["questions"][:upto]:
        user, info = chat_turn(arm, q["n"], state, rt, rv, rows)
        print(f"--- turn {q['n']} ({len(user):,} chars) {info}\n{user[:700]}\n...\n{user[-300:]}\n")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 8
    if cmd == "questions":
        install()
        build_questions()
    elif cmd == "chunks":
        build_chunks()
    elif cmd == "queries":
        build_queries()
    elif cmd == "route":
        build_routes()
    elif cmd == "retrieve":
        install()
        build_retrieval()
    elif cmd == "sizes":
        sizes()
    elif cmd == "show":
        show(sys.argv[2], sys.argv[3])
    elif cmd == "showchat":
        showchat(sys.argv[2], int(sys.argv[3]))
    elif cmd == "answer":
        a = sys.argv[sys.argv.index("--arms") + 1].split(",") if "--arms" in sys.argv else list(ARMS)
        assert set(a) <= set(ARMS), a
        answer(a, workers)
    elif cmd == "solo":
        solo(workers)
    elif cmd == "chat":
        chat()
    else:
        raise SystemExit(__doc__)
