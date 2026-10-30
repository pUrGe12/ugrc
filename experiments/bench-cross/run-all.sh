#!/usr/bin/env bash
# Every Llama arm of the cross-paper and corpus comparison, back to back (so the server is never left idle).
#   ./experiments/bench-cross/run-all.sh      (needs ~/.ugrc_vllm_key and ~/.jev_key; a run resumes)
set -uo pipefail
cd "$(dirname "$0")/../.."
URL=${MODAL_LLAMA_URL:-https://helloitsme0218--ugrc-llama-server.us-east.modal.direct}
for i in $(seq 1 120); do [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$URL/health")" = 200 ] && break; sleep 15; done
export JEV_API_KEY="$(cat ~/.jev_key)" LLAMA_URL="$URL/v1" LLAMA_KEY="$(cat ~/.ugrc_vllm_key)" LLAMA_MODEL=llama-3.1-8b-instruct
echo "== $(date -Is) cross: ugrc corpus arms and pasted papers"
.venv/bin/python experiments/bench-cross/run.py llama-corpus-leads-sp,llama-corpus-plain-sp,llama-direct-fill --workers 6
echo "== $(date -Is) cross: hybrid"
.venv/bin/python experiments/bench-cross/hybrid.py cross --workers 6
echo "== $(date -Is) bench: hybrid"
.venv/bin/python experiments/bench-cross/hybrid.py bench --workers 6
echo "== $(date -Is) bench: ugrc + Jev on the 10-paper corpus"
.venv/bin/python experiments/bench-llama/run.py llama-corpus-leads-sp 1 --workers 8
echo "== $(date -Is) end"
