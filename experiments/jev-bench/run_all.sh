#!/usr/bin/env bash
# Jev (jev-latest) builds a clause base for each of the 10 papers with the questions in ugrc/clauses.py.
cd "$(dirname "$0")/../.."
export JEV_API_KEY="$(cat ~/.jev_key)"
TAG=${1:-v7}
for d in runs/papers/*/; do
  p=$(basename "$d"); out=experiments/jev-bench/runs/$TAG/$p
  [ -e "$out/clauses.duckdb" ] && { echo "skip $p"; continue; }
  echo "== $(date -Is) $p"
  .venv/bin/python -m ugrc clauses --db "$d" --out "$out" 2>&1 | grep -E "clauses:|Error|Traceback"
done
echo "all done"
