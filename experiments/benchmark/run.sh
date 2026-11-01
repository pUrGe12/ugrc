#!/usr/bin/env bash
# The benchmark's answers on the Modal vLLM server (PLAN.md): part 1, part 2 alone and part 2's conversations, side by
# side. A record that exists is skipped, so this resumes.   ./experiments/benchmark/run.sh [WORKERS]
set -uo pipefail
cd "$(dirname "$0")/../.."
W=${1:-8}
URL=${MODAL_LLAMA_URL:-https://helloitsme0218--ugrc-llama-server.us-east.modal.direct}
LOG=experiments/benchmark/answer.log
echo "== $(date -Is) waking $URL" | tee -a "$LOG"
for i in $(seq 1 120); do [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$URL/health")" = 200 ] && break; sleep 15; done
[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$URL/health")" = 200 ] || { echo "server not healthy" >&2; exit 1; }
echo "== $(date -Is) healthy" | tee -a "$LOG"
export LLAMA_URL="$URL/v1" LLAMA_KEY="$(cat ~/.ugrc_vllm_key)" LLAMA_MODEL=llama-3.1-8b-instruct UGRC_LLM_TIMEOUT_S=900
.venv/bin/python experiments/benchmark/run.py chat >> "$LOG" 2>&1 &
.venv/bin/python experiments/benchmark/run.py answer --workers "$W" >> "$LOG" 2>&1 &
.venv/bin/python experiments/benchmark/run.py solo --workers 4 >> "$LOG" 2>&1 &
wait
echo "== $(date -Is) end" | tee -a "$LOG"
