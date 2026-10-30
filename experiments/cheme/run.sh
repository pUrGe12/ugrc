#!/usr/bin/env bash
# The ChemE held-out test on the Modal vLLM server: hybrid (v5), facts and pdf, 3 runs each (PLAN.md). A record that
# exists is skipped, so this resumes.
#   ./experiments/cheme/run.sh [run.py flags]
set -uo pipefail
cd "$(dirname "$0")/../.."
URL=${MODAL_LLAMA_URL:-https://helloitsme0218--ugrc-llama-server.us-east.modal.direct}
echo "== $(date -Is) waking $URL"
for i in $(seq 1 120); do [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$URL/health")" = 200 ] && break; sleep 15; done
[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$URL/health")" = 200 ] || { echo "server not healthy" >&2; exit 1; }
echo "== $(date -Is) healthy"
export LLAMA_URL="$URL/v1" LLAMA_KEY="$(cat ~/.ugrc_vllm_key)" LLAMA_MODEL=llama-3.1-8b-instruct UGRC_LLM_TIMEOUT_S=900
.venv/bin/python experiments/cheme/run.py --arms hybrid,facts,pdf --runs 1,2,3 --workers 6 "$@"
echo "== $(date -Is) end"
