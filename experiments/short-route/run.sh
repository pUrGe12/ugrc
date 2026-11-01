#!/usr/bin/env bash
# The short-question answers on the Modal vLLM server (ANSWER.md). A record that exists is skipped, so this resumes.
#   ./experiments/short-route/run.sh [--workers 8]
set -uo pipefail
cd "$(dirname "$0")/../.."
URL=${MODAL_LLAMA_URL:-https://helloitsme0218--ugrc-llama-server.us-east.modal.direct}
echo "== $(date -Is) waking $URL"
for i in $(seq 1 120); do [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$URL/health")" = 200 ] && break; sleep 15; done
[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$URL/health")" = 200 ] || { echo "server not healthy" >&2; exit 1; }
echo "== $(date -Is) healthy"
export LLAMA_URL="$URL/v1" LLAMA_KEY="$(cat ~/.ugrc_vllm_key)" LLAMA_MODEL=llama-3.1-8b-instruct UGRC_LLM_TIMEOUT_S=900
.venv/bin/python experiments/short-route/answer.py answer "$@"
echo "== $(date -Is) end"
