"""embed.py's dense scores, computed on a Modal GPU instead of this laptop's CPU (about an hour there): the same model at
a pinned revision, the same instruction, CLS pooling, l2-normalized, fp32. The image is the Llama server's (vLLM brings
torch and transformers), so nothing new is built.

    .venv/bin/modal run experiments/benchmark/embed_modal.py      reads chunks.jsonl, queries.json; writes dense.json.gz
"""
import gzip
import hashlib
import json
from pathlib import Path

import modal

MODEL = "BAAI/bge-base-en-v1.5"
REVISION = "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a"
INSTRUCTION = "Represent this sentence for searching relevant passages: "
HERE = Path(__file__).resolve().parent

image = (modal.Image.from_registry("nvidia/cuda:12.9.0-devel-ubuntu22.04", add_python="3.12")
         .entrypoint([])
         .uv_pip_install("vllm==0.21.0")
         .env({"HF_XET_HIGH_PERFORMANCE": "1"}))
hf_cache = modal.Volume.from_name("huggingface-cache", create_if_missing=True)
app = modal.App("ugrc-embed")


@app.function(image=image, gpu=["L40S", "A10G", "A100", "L4"], volumes={"/root/.cache/huggingface": hf_cache}, timeout=30 * 60)
def scores(chunks: list, queries: list) -> list:
    import torch
    from transformers import AutoModel, AutoTokenizer
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    tok = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
    model = AutoModel.from_pretrained(MODEL, revision=REVISION, torch_dtype=torch.float32).eval().to("cuda")

    def embed(texts, batch=64):
        out = []
        for s in range(0, len(texts), batch):
            enc = tok(texts[s:s + batch], padding=True, truncation=True, max_length=512, return_tensors="pt").to("cuda")
            with torch.inference_mode():
                v = model(**enc).last_hidden_state[:, 0]
            out.append(torch.nn.functional.normalize(v, dim=-1))
        return torch.cat(out)

    q = embed([INSTRUCTION + t for t in queries])
    c = embed(chunks)
    return [[round(x, 5) for x in row] for row in (q @ c.T).float().cpu().tolist()]


@app.local_entrypoint()
def main():
    rows = [json.loads(line) for line in open(HERE / "chunks.jsonl")]
    queries = json.loads((HERE / "queries.json").read_text())
    qids = list(queries)
    s = scores.remote([r["text"] for r in rows], [queries[k] for k in qids])
    out = {"model": MODEL, "revision": REVISION, "instruction": INSTRUCTION, "pooling": "cls, l2-normalized",
           "device": "Modal GPU (L40S, A10G, A100 or L4), fp32, tf32 off",
           "chunks_sha256": hashlib.sha256((HERE / "chunks.jsonl").read_bytes()).hexdigest(),
           "queries_sha256": hashlib.sha256((HERE / "queries.json").read_bytes()).hexdigest(),
           "scores": {k: s[i] for i, k in enumerate(qids)}}
    with gzip.open(HERE / "dense.json.gz", "wt") as f:
        json.dump(out, f)
    print(f"wrote dense.json.gz ({len(qids)} x {len(rows)})")
