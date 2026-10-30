"""Cross-paper questions (probes.json, frozen) over the 10 battery papers of runs/papers-corpus. Llama only.

    LLAMA_URL=<server>/v1 LLAMA_KEY=... JEV_API_KEY=... python experiments/bench-cross/run.py ARM[,ARM...] [--workers N] [--only W1,C2]

ARM is one of
  llama-corpus-leads-sp   ugrc on the corpus with Jev's clause base (leads, measure runs, the pairing gate), the short
                          prompt in its corpus form (ask.SYSTEM_SMALL)
  llama-corpus-plain-sp   ugrc on the same corpus without the clause base (runs/papers-corpus-plain: the atoms only)
  llama-direct-fill       no ugrc: the papers' pdftotext texts in the prompt, ranked by BM25 against the question and
                          added in that order while they fit in FILL tokens (the strongest pasted-papers baseline that
                          fits Llama's window: all 10 are ~157k tokens). One reply, no tools.
Answers go to answers/<arm>-r1/<id>.json; a question with no accepted answer within 20 turns to <id>.error.json.
"""
import json
import math
import os
import re
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "bench-llama"))
from ugrc import ask, llm  # noqa: E402

LLAMA_URL = os.environ.get("LLAMA_URL", "").rstrip("/")
LLAMA_KEY = os.environ.get("LLAMA_KEY")
MODEL = os.environ.get("LLAMA_MODEL", "llama-3.1-8b-instruct")
MAX_TURNS = 20
FILL = 120_000
PAPERS = ["acsnano-7b02404", "adma-2020", "aenm-2022", "cssc-2020", "ensm-2020", "ensm-2021", "mattod-2020",
          "nanolett-6b05172", "nanolett-6b05174", "susmat-2020"]
ARMS = {"llama-corpus-leads-sp": ROOT / "runs" / "papers-corpus",
        "llama-corpus-plain-sp": ROOT / "runs" / "papers-corpus-plain",
        "llama-direct-fill": None}
SYSTEM_FILL = ("You answer questions about a collection of documents, using only what they contain. The texts of the "
               "{n} documents most related to the question, extracted from their PDFs, are below. A question may be "
               "about one of them, several, or all. If the documents do not hold what the question asks, say so.")
lock = threading.Lock()


def probes():
    import hashlib
    frozen = (HERE / "frozen.sha256").read_text().split()[0]
    if hashlib.sha256((HERE / "probes.json").read_bytes()).hexdigest() != frozen:
        raise SystemExit("probes.json changed since it was frozen")
    return json.loads((HERE / "probes.json").read_text())["probes"]


def log(msg):
    with lock:
        print(msg, flush=True)


# ── the pasted-papers baseline ──
def _words(s):
    return re.findall(r"[a-z0-9]+", s.lower())


def bm25_rank(question: str, texts: dict[str, str], k1=1.5, b=0.75) -> list[tuple[str, float]]:
    docs = {p: _words(t) for p, t in texts.items()}
    avg = sum(len(d) for d in docs.values()) / len(docs)
    terms = set(_words(question))
    df = {t: sum(t in set(d) for d in docs.values()) for t in terms}
    out = []
    for p, d in docs.items():
        tf = {}
        for w in d:
            if w in terms:
                tf[w] = tf.get(w, 0) + 1
        s = sum(math.log(1 + (len(docs) - df[t] + 0.5) / (df[t] + 0.5)) * tf[t] * (k1 + 1)
                / (tf[t] + k1 * (1 - b + b * len(d) / avg)) for t in tf)
        out.append((p, s))
    return sorted(out, key=lambda x: -x[1])


def fill_answer(probe):
    import direct
    direct.URL, direct.KEY, direct.MODEL = LLAMA_URL, LLAMA_KEY, MODEL
    texts = {p: direct.paper_text(p)[0] for p in PAPERS}
    ranked = bm25_rank(probe["q"], texts)
    chosen, total = [], 0
    for p, _ in ranked:
        n = direct.paper_tokens(p)
        if total + n <= FILL:
            chosen.append(p)
            total += n
    body = "\n\n".join(f'<document title="{direct.TITLES[p]}">\n{texts[p]}\n</document>' for p in chosen)
    resp = direct.chat(SYSTEM_FILL.format(n=len(chosen)), f"{body}\n\nQuestion: {probe['q']}")
    choice = resp["choices"][0]
    answer = choice["message"].get("content") or ""
    return {"rendered": answer, "finish_reason": choice.get("finish_reason"), "turns": 1, "tool_calls": 0,
            "door_refusals": [], "citations": [], "runs": [], "trace": [], "usage": resp.get("usage"),
            "documents": chosen, "ranking": ranked, "document_tokens": total,
            "needed_documents_in_prompt": [p for p in probe["papers"] if p in chosen],
            "prompt": {"style": "direct-fill", "system": SYSTEM_FILL, "fill_tokens": FILL}}


def one(job):
    arm, probe, client = job
    out = HERE / "answers" / f"{arm}-r1"
    out.mkdir(parents=True, exist_ok=True)
    if (out / f"{probe['id']}.json").exists() or (out / f"{probe['id']}.error.json").exists():
        return
    t = time.time()
    try:
        if ARMS[arm] is None:
            rec = fill_answer(probe)
        else:
            rec = ask.ask(ARMS[arm], probe["q"], model=MODEL, cl=client, log=lambda *_: None, prompt="small")
        rec = dict(rec, arm=arm, run=1, probe=probe["id"], cat=probe["cat"], papers=probe["papers"],
                   expect=probe["expect"], trap=probe.get("trap"), model=MODEL, llama_endpoint={"url": LLAMA_URL},
                   seconds=round(time.time() - t, 1))
        (out / f"{probe['id']}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False, default=str))
        log(f"done  {arm:22} {probe['id']:3} turns={rec['turns']} refusals={len(rec['door_refusals'])} {time.time() - t:.0f}s")
    except Exception as e:
        if isinstance(e, llm.ServerError):
            log(f"STOP  {arm} {probe['id']}: {e}")
            raise
        tried = getattr(e, "record", None) or {}
        (out / f"{probe['id']}.error.json").write_text(json.dumps({
            "arm": arm, "probe": probe["id"], "cat": probe["cat"], "error": f"{type(e).__name__}: {e}",
            "seconds": round(time.time() - t, 1), "turns": tried.get("turns"), "trace": tried.get("trace"),
            "door_refusals": tried.get("door_refusals"), "traceback": traceback.format_exc()},
            indent=2, ensure_ascii=False, default=str))
        log(f"FAIL  {arm:22} {probe['id']:3} {type(e).__name__}: {str(e)[:100]}")


if __name__ == "__main__":
    arms = sys.argv[1].split(",")
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 6
    only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
    ask.MAX_TURNS = MAX_TURNS
    clients = {a: llm.OpenAIChat(LLAMA_URL, LLAMA_KEY, one_call_per_turn=True) for a in arms}
    jobs = [(a, p, clients[a]) for p in probes() if not only or p["id"] in only for a in arms]
    log(f"{len(jobs)} jobs, arms {arms}, {workers} workers")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, jobs))
    log("all done")
