#!/usr/bin/env bash
cd "$(dirname "$0")/../.."
experiments/jev-bench/run_all.sh v8
export JEV_API_KEY="$(cat ~/.jev_key)"
for p in 2 3; do
  out=experiments/jev-questions/runs/p$p-v8-jev-latest
  [ -e "$out/clauses.duckdb" ] || .venv/bin/python -m ugrc clauses --db runs/paper$p --out $out 2>&1 | grep -E "clauses:|Error"
done
echo "v8 all done"
