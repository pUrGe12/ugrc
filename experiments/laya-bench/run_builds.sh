#!/usr/bin/env bash
# Build the 12 clause bases of the Jev bench with Laya as the judge: the same code, questions and substrates as
# experiments/jev-bench/runs/v8 and experiments/jev-questions/runs/p{2,3}-v8-jev-latest, with ugrc/jev.py
# pointed at a local laya-serve (the Jev-compatible POST /v1/systemone).
#   LAYA_KEY=... experiments/laya-bench/run_builds.sh CHECKPOINT [PAPER ...]
# Papers default to the held-out ones first (the honest column), then papers 2 and 3, then the tuning ones.
cd "$(dirname "$0")/../.."
CK=${1:?checkpoint: english or multilingual}; shift
export JEV_URL=${LAYA_URL:-http://127.0.0.1:8077/v1/systemone} JEV_MODEL=$CK JEV_API_KEY="$LAYA_KEY" JEV_TIMEOUT_S=600
PAPERS=${*:-"acsnano-7b02404 aenm-2022 ensm-2021 nanolett-6b05172 susmat-2020 paper2 paper3 adma-2020 cssc-2020 ensm-2020 mattod-2020 nanolett-6b05174"}
for p in $PAPERS; do
  d=runs/papers/$p; [ -d "$d" ] || d=runs/$p
  out=experiments/laya-bench/runs/$CK/$p
  [ -e "$out/clauses.duckdb" ] && { echo "skip $p"; continue; }
  echo "== $(date -Is) $p"
  .venv/bin/python -m ugrc clauses --db "$d" --out "$out" --workers 2 2>&1 | grep -E "clauses:|Error|Traceback|judge: .*/.* calls$" | tail -3
done
echo "all done $CK"
