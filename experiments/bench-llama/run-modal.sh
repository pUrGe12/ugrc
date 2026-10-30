#!/usr/bin/env bash
# The Llama arms against our own vLLM server on Modal (experiments/bench-llama/modal_vllm.py, bf16, L40S).
#   [ARMS=llama-plain-sp,llama-leads-sp] ./experiments/bench-llama/run-modal.sh [RUNS] [WORKERS] [run.py flags, e.g. --only ...]
# ARMS defaults to llama-plain,llama-leads (the full prompt).
# Needs ~/.ugrc_vllm_key (the endpoint's key) and ~/.jev_key (the leads arm's pairing gate). A run resumes.
# The server scales to zero after 10 idle minutes; this script wakes it and waits for /health first.
set -euo pipefail
cd "$(dirname "$0")/../.."
RUNS=${1:-1}
WORKERS=${2:-6}
shift $(( $# < 2 ? $# : 2 ))
ARMS=${ARMS:-llama-plain,llama-leads}
URL=${MODAL_LLAMA_URL:-https://helloitsme0218--ugrc-llama-server.us-east.modal.direct}
[ -f ~/.ugrc_vllm_key ] || { echo "no ~/.ugrc_vllm_key" >&2; exit 1; }
[ -f ~/.jev_key ] || { echo "no ~/.jev_key" >&2; exit 1; }

echo "waking $URL ..."
for i in $(seq 1 120); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$URL/health")" = 200 ] && break
  sleep 15
done
[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$URL/health")" = 200 ] || { echo "server not healthy" >&2; exit 1; }

LOG=experiments/bench-llama/run-modal.log
echo "== $(date -Is) start, arms=$ARMS runs=$RUNS workers=$WORKERS $* url=$URL" >> "$LOG"
JEV_API_KEY="$(cat ~/.jev_key)" LLAMA_URL="$URL/v1" LLAMA_KEY="$(cat ~/.ugrc_vllm_key)" \
  LLAMA_MODEL=llama-3.1-8b-instruct \
  .venv/bin/python experiments/bench-llama/run.py "$ARMS" "$RUNS" --workers "$WORKERS" "$@" 2>&1 | tee -a "$LOG"
.venv/bin/python experiments/bench-llama/grade.py report
