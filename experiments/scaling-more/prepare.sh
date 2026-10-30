#!/usr/bin/env bash
# Ingest (no model) and build the clause base (Jev) of every selected arXiv paper; a paper already done is skipped.
#   JEV_API_KEY=... ./experiments/scaling-more/prepare.sh ID [ID ...]
cd "$(dirname "$0")/../.."
for id in "$@"; do
  out=runs/arxiv/$id
  pdf=~/Desktop/papers-arxiv/$id.pdf
  if [ ! -e "$out/atoms.duckdb" ]; then
    echo "== $(date -Is) ingest $id"
    .venv/bin/python -m ugrc ingest "$pdf" --out "$out" > "$out.ingest.log" 2>&1 || { echo "INGEST FAILED $id"; continue; }
  fi
  if [ ! -e "$out/clauses.duckdb" ]; then
    echo "== $(date -Is) clauses $id"
    .venv/bin/python -m ugrc clauses --db "$out" --out "$out" --workers 8 > "$out.clauses.log" 2>&1 || { echo "CLAUSES FAILED $id"; continue; }
  fi
  echo "== $(date -Is) done $id"
done
echo "prepare finished"
