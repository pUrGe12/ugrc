"""Llama 3.1 8B Instruct at full precision (bf16), served by vLLM on Modal: an OpenAI-compatible endpoint for run.py.

    VLLM_API_KEY="$(cat ~/.ugrc_vllm_key)" .venv/bin/modal deploy experiments/bench-llama/modal_vllm.py
    .venv/bin/modal app stop ugrc-llama          # when done (it also scales to zero after 10 idle minutes)

then run.py with LLAMA_URL=<the deployed URL>/v1, LLAMA_KEY="$(cat ~/.ugrc_vllm_key)", LLAMA_MODEL=llama-3.1-8b-instruct
(experiments/bench-llama/run-modal.sh does this).

Weights: unsloth/Llama-3.1-8B-Instruct at a pinned revision. Its four safetensors files have the same hashes as
NousResearch/Meta-Llama-3.1-8B-Instruct (copied from Meta on release day), and its chat template is Meta's 3.1
template with tools (Meta's own repo is gated). Tool calls are parsed by vLLM's llama3_json parser. The endpoint is
public at Modal's edge and guarded by vLLM's API key, which is read on the deploying machine and handed to the
container as a secret: it is never written in this file or printed.
"""
import os
import subprocess

import modal

MODEL = "unsloth/Llama-3.1-8B-Instruct"
REVISION = "4699cc75b550f9c6f3173fb80f4703b62d946aa5"
SERVED = "llama-3.1-8b-instruct"
PORT = 8000
MAX_LEN = 131072          # Llama 3.1's own context, as on CoreWeave: a long conversation is never cut by the host
MINUTES = 60

image = (modal.Image.from_registry("nvidia/cuda:12.9.0-devel-ubuntu22.04", add_python="3.12")
         .entrypoint([])
         .uv_pip_install("vllm==0.21.0")        # the version Modal's own vLLM example runs on this image
         .env({"HF_XET_HIGH_PERFORMANCE": "1"}))
hf_cache = modal.Volume.from_name("huggingface-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("vllm-cache", create_if_missing=True)
app = modal.App("ugrc-llama")

_key = os.environ.get("VLLM_API_KEY")
if modal.is_local() and not _key:
    raise SystemExit("set VLLM_API_KEY (e.g. from ~/.ugrc_vllm_key): the endpoint is public and needs a key")
secrets = [modal.Secret.from_dict({"VLLM_API_KEY": _key})] if _key else []


@app.server(image=image, gpu="L40S", secrets=secrets,
            volumes={"/root/.cache/huggingface": hf_cache, "/root/.cache/vllm": vllm_cache},
            port=PORT, unauthenticated=True, startup_timeout=20 * MINUTES, scaledown_window=10 * MINUTES,
            target_concurrency=16, max_containers=1)
class Server:
    @modal.enter()
    def start(self):
        cmd = ["vllm", "serve", MODEL, "--revision", REVISION, "--served-model-name", SERVED,
               "--host", "0.0.0.0", "--port", str(PORT), "--dtype", "bfloat16", "--max-model-len", str(MAX_LEN),
               "--enable-auto-tool-choice", "--tool-call-parser", "llama3_json",
               "--api-key", os.environ["VLLM_API_KEY"]]
        print("vllm serve", MODEL, "@", REVISION[:10], "bf16, max len", MAX_LEN, "(api key set)")
        self.process = subprocess.Popen(cmd)

    @modal.exit()
    def stop(self):
        self.process.terminate()
