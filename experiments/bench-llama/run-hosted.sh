#!/usr/bin/env bash
# Both Llama arms through OpenRouter, pinned to CoreWeave (bf16, no fallback). Checks the credit balance first.
#   OPENROUTER_API_KEY=... ./experiments/bench-llama/run-hosted.sh [RUNS] [WORKERS]
# Needs ~/.jev_key (the leads arm's pairing gate). A run resumes: answered questions are skipped.
set -euo pipefail
cd "$(dirname "$0")/../.."
RUNS=${1:-1}
WORKERS=${2:-3}
NEED_USD=${NEED_USD:-8}          # one run of both arms cost ~$0.017 a question in the smoke test: ~$5 for 308
: "${OPENROUTER_API_KEY:?set OPENROUTER_API_KEY}"
[ -f ~/.jev_key ] || { echo "no ~/.jev_key" >&2; exit 1; }

K="$OPENROUTER_API_KEY" NEED="$NEED_USD" RUNS="$RUNS" .venv/bin/python -I -c '
import json, os, sys, urllib.request
req = urllib.request.Request("https://openrouter.ai/api/v1/credits", headers={"Authorization": "Bearer " + os.environ["K"]})
d = json.loads(urllib.request.urlopen(req, timeout=30).read())["data"]
left = d["total_credits"] - d["total_usage"]
need = float(os.environ["NEED"]) * int(os.environ["RUNS"])
print(f"OpenRouter credit left: ${left:.2f} (this run needs about ${need:.0f})")
sys.exit(0 if left >= need else 1)' || { echo "not enough credit: add some at openrouter.ai, or set NEED_USD lower" >&2; exit 1; }

LOG=experiments/bench-llama/run-hosted.log
echo "== $(date -Is) start, runs=$RUNS workers=$WORKERS" >> "$LOG"
JEV_API_KEY="$(cat ~/.jev_key)" LLAMA_URL=https://openrouter.ai/api/v1 LLAMA_KEY="$OPENROUTER_API_KEY" \
  LLAMA_MODEL=meta-llama/llama-3.1-8b-instruct LLAMA_HOST=coreweave/bf16 \
  .venv/bin/python experiments/bench-llama/run.py llama-plain,llama-leads "$RUNS" --workers "$WORKERS" 2>&1 | tee -a "$LOG"
.venv/bin/python experiments/bench-llama/grade.py report
