#!/usr/bin/env bash
# Ingest with extractor v5 (no model) and build the clause base (Jev) of each paper; a step already done is skipped.
#   JEV_API_KEY=... ./experiments/big-library/prepare.sh SET KEY [KEY ...]   ~/Desktop/papers-SET/KEY.pdf -> runs/SET/KEY
cd "$(dirname "$0")/../.."
want=$(cut -d' ' -f1 experiments/cheme/extract.sha256)
[ "$(sha256sum ugrc/extract.py | cut -d' ' -f1)" = "$want" ] || { echo "ugrc/extract.py changed since it was frozen"; exit 1; }
set=$1; shift
src=~/Desktop/papers-$set; dst=runs/$set
mkdir -p $dst
for id in "$@"; do
  out=$dst/$id
  if [ ! -e "$out/atoms.duckdb" ]; then
    echo "== $(date -Is) ingest $set/$id"
    .venv/bin/python -m ugrc ingest "$src/$id.pdf" --out "$out" > "$out.ingest.log" 2>&1 || { echo "INGEST FAILED $set/$id"; continue; }
  fi
  if [ ! -e "$out/clauses.duckdb" ]; then
    echo "== $(date -Is) clauses $set/$id"
    .venv/bin/python -m ugrc clauses --db "$out" --out "$out" --workers 8 > "$out.clauses.log" 2>&1 || { echo "CLAUSES FAILED $set/$id"; continue; }
  fi
  echo "== $(date -Is) done $set/$id"
done
echo "prepare finished"
