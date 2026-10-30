#!/usr/bin/env bash
# The clause-reasoning test (PLAN.md) on the Modal vLLM server. A record that exists is skipped, so a run resumes.
#   ./experiments/clause-reasoning/run.sh [RUNS, default 1]
set -uo pipefail
cd "$(dirname "$0")/../.."
URL=${MODAL_LLAMA_URL:-https://helloitsme0218--ugrc-llama-server.us-east.modal.direct}
for i in $(seq 1 120); do [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$URL/health")" = 200 ] && break; sleep 15; done
[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$URL/health")" = 200 ] || { echo "server not healthy" >&2; exit 1; }
export LLAMA_URL="$URL/v1" LLAMA_KEY="$(cat ~/.ugrc_vllm_key)" LLAMA_MODEL=llama-3.1-8b-instruct UGRC_LLM_TIMEOUT_S=900
.venv/bin/python experiments/clause-reasoning/run.py --ways clauses,text --runs "${1:-1}" --workers 6
