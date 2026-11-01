"""Dense scores for the RAG arms (PLAN.md), with BAAI/bge-base-en-v1.5: every chunk and every query embedded (CLS,
normalized; queries carry bge's retrieval instruction), and each query's cosine score against every chunk.

    .venv-laya/bin/python experiments/benchmark/embed.py      reads chunks.jsonl, queries.json; writes dense.json.gz

Runs on the CPU in the environment that has torch and transformers (.venv-laya); run.py reads only its output.
"""
import gzip
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import torch
from transformers import AutoModel, AutoTokenizer

HERE = Path(__file__).resolve().parent
MODEL = "BAAI/bge-base-en-v1.5"
REVISION = os.environ.get("BGE_REVISION", "main")
INSTRUCTION = "Represent this sentence for searching relevant passages: "
torch.set_num_threads(int(os.environ.get("EMBED_THREADS", 16)))


def embed(tok, model, texts, batch=32, label=""):
    out, t = [], time.time()
    for s in range(0, len(texts), batch):
        enc = tok(texts[s:s + batch], padding=True, truncation=True, max_length=512, return_tensors="pt")
        with torch.inference_mode():
            v = model(**enc).last_hidden_state[:, 0]
        out.append(torch.nn.functional.normalize(v, dim=-1))
        if s // batch % 20 == 0:
            print(f"  {label} {s + len(texts[s:s + batch])}/{len(texts)} {time.time() - t:.0f}s", flush=True)
    return torch.cat(out)


def main():
    rows = [json.loads(line) for line in open(HERE / "chunks.jsonl")]
    queries = json.loads((HERE / "queries.json").read_text())
    tok = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
    model = AutoModel.from_pretrained(MODEL, revision=REVISION).eval()
    commit = getattr(model.config, "_commit_hash", None)
    print(f"{MODEL} @ {commit}: {len(rows)} chunks, {len(queries)} queries", flush=True)
    qids = list(queries)
    q = embed(tok, model, [INSTRUCTION + queries[k] for k in qids], label="queries")
    c = embed(tok, model, [r["text"] for r in rows], label="chunks")
    scores = (q @ c.T).tolist()
    out = {"model": MODEL, "revision": commit, "instruction": INSTRUCTION, "pooling": "cls, l2-normalized",
           "chunks_sha256": hashlib.sha256((HERE / "chunks.jsonl").read_bytes()).hexdigest(),
           "queries_sha256": hashlib.sha256((HERE / "queries.json").read_bytes()).hexdigest(),
           "scores": {k: [round(x, 5) for x in scores[i]] for i, k in enumerate(qids)}}
    with gzip.open(HERE / "dense.json.gz", "wt") as f:
        json.dump(out, f)
    print(f"wrote dense.json.gz ({len(qids)} x {len(rows)})")


if __name__ == "__main__":
    sys.exit(main())
