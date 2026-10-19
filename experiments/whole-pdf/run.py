"""Baseline: the same questions answered by Claude with the whole PDF(s) in the prompt, no ugrc.

    ANTHROPIC_API_KEY=... python experiments/whole-pdf/run.py [ID ...]      # IDs like p2-C1, prof-G1

Same model and effort as the ugrc runs (claude-opus-5-5, effort high). Each PDF is uploaded once through
the Files API (the 10 papers are 34 MB together, over the 32 MB request limit for inline PDFs) and sent as
a document block; the documents are a cached prefix, so the first question on a set writes the cache and
the rest read it. Each answer is saved to answers/<set>-<id>.json with its text and token usage.
"""
import json
import os
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from ugrc import llm  # noqa: E402

DOWNLOADS = Path.home() / "Downloads"
PAPERS = Path.home() / "Desktop" / "papers"
OUT = HERE / os.environ.get("ANSWERS", "answers")     # another folder for another model
FILES = HERE / "files.json"          # uploaded file ids, reused while they live
EXPIRES_S = 2 * 24 * 3600
WORKERS = 6

SYSTEM = ("You answer questions about the attached paper(s), using only what they contain. "
          "Give the page (and, when there are several papers, the paper) for every fact you state. "
          "If the papers do not answer the question, say so.")

lock = threading.Lock()


def log(msg):
    with lock:
        print(msg, flush=True)


def corpus_papers():
    con = duckdb.connect(str(ROOT / "runs" / "papers-corpus" / "atoms.duckdb"), read_only=True)
    return [(key, PAPERS / Path(f).name) for key, f in con.execute("SELECT id, file FROM documents ORDER BY id").fetchall()]


def sets():
    probes = lambda f: [{"id": p["id"], "q": p["q"]} for p in json.loads(f.read_text())["probes"]]
    prof = [{"id": q["id"], "q": q["q"]} for q in json.loads((ROOT / "experiments/prof-rag/questions.json").read_text())["questions"]]
    return {
        "p2": ([("paper2", DOWNLOADS / "1-s2.0-S1385894726097068-main.pdf")], probes(ROOT / "experiments/hallucination-paper2/probes.json")),
        "p3": ([("paper3", DOWNLOADS / "1-s2.0-S1385894726098189-main.pdf")], probes(ROOT / "experiments/paper3/probes.json")),
        "prof": (corpus_papers(), prof),
    }


def upload(cl, papers):
    known = json.loads(FILES.read_text()) if FILES.exists() else {}
    ids = []
    for key, path in papers:
        entry = known.get(str(path))
        if not entry or entry["expires"] < time.time() + 3600:
            meta = cl.files.upload(file=path, expires_in_seconds=EXPIRES_S)
            entry = known[str(path)] = {"id": meta.id, "expires": time.time() + EXPIRES_S}
            FILES.write_text(json.dumps(known, indent=2))
        ids.append((key, entry["id"]))
    return ids


def ask_whole(cl, docs, question):
    content = [{"type": "document", "source": {"type": "file", "file_id": fid}, "title": key} for key, fid in docs]
    content[-1]["cache_control"] = {"type": "ephemeral"}
    content.append({"type": "text", "text": question})
    t0 = time.time()
    resp = llm.create(cl, model=llm.MODEL, max_tokens=16000, system=SYSTEM, output_config={"effort": "high"},
                      messages=[{"role": "user", "content": content}])
    u = resp.usage
    return {"answer": llm.text_of(resp), "served_by": resp.model, "stop_reason": resp.stop_reason, "seconds": round(time.time() - t0, 1),
            "usage": {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                      "cache_read_input_tokens": u.cache_read_input_tokens or 0,
                      "cache_creation_input_tokens": u.cache_creation_input_tokens or 0}}


def one(cl, name, docs, q):
    path = OUT / f"{name}-{q['id']}.json"
    if path.exists():
        return log(f"skip  {name}-{q['id']}")
    try:
        rec = dict(ask_whole(cl, docs, q["q"]), set=name, probe=q["id"], question=q["q"], model=llm.MODEL,
                   papers=[k for k, _ in docs])
        path.write_text(json.dumps(rec, indent=2, ensure_ascii=False))
        u = rec["usage"]
        log(f"done  {name}-{q['id']:4} in={u['input_tokens'] + u['cache_read_input_tokens'] + u['cache_creation_input_tokens']:,} "
            f"(cached {u['cache_read_input_tokens']:,}) out={u['output_tokens']:,} {rec['seconds']}s")
    except Exception as e:
        log(f"FAIL  {name}-{q['id']}: {type(e).__name__}: {e}")
        (OUT / f"{name}-{q['id']}.error.txt").write_text(traceback.format_exc())


def run_set(cl, name, papers, qs):
    docs = upload(cl, papers)
    todo = [q for q in qs if not (OUT / f"{name}-{q['id']}.json").exists()]
    if not todo:
        return log(f"{name}: all answered")
    one(cl, name, docs, todo[0])                  # writes the cache; the rest read it
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(lambda q: one(cl, name, docs, q), todo[1:]))


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    only = sys.argv[1:]
    cl = llm.client()
    for name, (papers, qs) in sets().items():
        if only:
            qs = [q for q in qs if f"{name}-{q['id']}" in only]
        if qs:
            log(f"{name}: {len(qs)} questions over {len(papers)} PDF(s)")
            run_set(cl, name, papers, qs)
    log("all done")
