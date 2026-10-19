#!/usr/bin/env bash
# Llama 3.1 8B Instruct (Q4_K_M, bartowski rev bf5b95e, sha256 7b064f58...557c) on llama.cpp b11719 (Vulkan,
# Intel Arc iGPU), OpenAI-compatible at http://127.0.0.1:8090/v1. One slot of 32k context (a 20-turn question
# peaked at 8k tokens; two slots hung the iGPU: i915 "GPU HANG", context reset), the model's own
# chat template (--jinja) for tool calls. KEYFILE (one random token) locks it: without a key, any web page open
# in a browser on this machine could call it.
# Flash attention OFF: on this Intel iGPU, Vulkan flash attention returns garbage for prompts of a few thousand
# tokens (same prompt and seed: CPU and -fa off write a tool call, -fa on writes " date").
set -euo pipefail
LLAMA=${LLAMA:-$HOME/llm/llama.cpp-vulkan/llama-b11719}
MODEL=${MODEL:-$HOME/llm/models/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf}
exec "$LLAMA/llama-server" -m "$MODEL" --jinja -ngl 99 -fa off -c "${CTX:-32768}" -np "${SLOTS:-1}" \
  --host 127.0.0.1 --port "${PORT:-8090}" --alias llama-3.1-8b-instruct-q4_k_m --api-key-file "${KEYFILE:?a file holding the server key}" \
  --cors-origins http://127.0.0.1
