#!/usr/bin/env bash
# Does Jev's page picking help the hybrid? Pages by BM25 alone (llama-hybrid-bm25, runs 1-3) against leads then BM25
# (llama-hybrid, runs 2-3 beside the existing run 1), on the 33 cross-paper questions and on the two single papers
# too long to pass whole (ensm-2021, cai2026: 28 questions). A record that exists is skipped.
set -uo pipefail
cd "$(dirname "$0")/../.."
URL=${MODAL_LLAMA_URL:-https://helloitsme0218--ugrc-llama-server.us-east.modal.direct}
for i in $(seq 1 120); do [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$URL/health")" = 200 ] && break; sleep 15; done
export LLAMA_URL="$URL/v1" LLAMA_KEY="$(cat ~/.ugrc_vllm_key)" LLAMA_MODEL=llama-3.1-8b-instruct UGRC_LLM_TIMEOUT_S=900
H=experiments/bench-cross/hybrid.py
echo "== $(date -Is) start"
.venv/bin/python $H cross --pick bm25 --runs 1,2,3 --workers 6
.venv/bin/python $H cross --pick leads --runs 2,3 --workers 6
.venv/bin/python $H bench --pick bm25 --runs 1,2,3 --papers ensm-2021,cai2026 --workers 6
.venv/bin/python $H bench --pick leads --runs 2,3 --papers ensm-2021,cai2026 --workers 6
echo "== $(date -Is) end"
