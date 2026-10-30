#!/usr/bin/env bash
# The jev-pick test (PLAN.md) on the Modal vLLM server. A record that exists is skipped, so a run resumes.
#   ./experiments/bench-cross/jev-pick/run.sh 1      stage 1: leads and BM25, 3 runs, alternating
#   ./experiments/bench-cross/jev-pick/run.sh 2      stage 2: leads without Jev's readings, 3 runs
set -uo pipefail
cd "$(dirname "$0")/../../.."
STAGE=${1:?stage 1 or 2}
URL=${MODAL_LLAMA_URL:-https://helloitsme0218--ugrc-llama-server.us-east.modal.direct}
for i in $(seq 1 120); do [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$URL/health")" = 200 ] && break; sleep 15; done
[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$URL/health")" = 200 ] || { echo "server not healthy" >&2; exit 1; }
export LLAMA_URL="$URL/v1" LLAMA_KEY="$(cat ~/.ugrc_vllm_key)" LLAMA_MODEL=llama-3.1-8b-instruct UGRC_LLM_TIMEOUT_S=900
H=experiments/bench-cross/hybrid.py
echo "== $(date -Is) stage $STAGE start"
if [ "$STAGE" = 1 ]; then
  .venv/bin/python $H corpus --stage 1 --ways leads,bm25 --runs 1,2,3 --workers 6
else
  .venv/bin/python $H corpus --stage 2 --ways leads-text --runs 1,2,3 --workers 6
fi
echo "== $(date -Is) stage $STAGE end"
