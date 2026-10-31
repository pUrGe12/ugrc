#!/usr/bin/env bash
# Ingest with extractor v5 (no model) and build the clause base (Jev) of each paper; a step already done is skipped.
#   JEV_API_KEY=... ./experiments/cheme2/prepare.sh KEY [KEY ...]      ~/Desktop/papers-cheme2/KEY.pdf -> runs/cheme2/KEY
cd "$(dirname "$0")/../.."
want=$(cut -d' ' -f1 experiments/cheme/extract.sha256)
[ "$(sha256sum ugrc/extract.py | cut -d' ' -f1)" = "$want" ] || { echo "ugrc/extract.py changed since it was frozen"; exit 1; }
src=~/Desktop/papers-cheme2; dst=runs/cheme2
mkdir -p $dst
for id in "$@"; do
  out=$dst/$id
  if [ ! -e "$out/atoms.duckdb" ]; then
    echo "== $(date -Is) ingest $id"
    .venv/bin/python -m ugrc ingest "$src/$id.pdf" --out "$out" > "$out.ingest.log" 2>&1 || { echo "INGEST FAILED $id"; continue; }
  fi
  if [ ! -e "$out/clauses.duckdb" ]; then
    echo "== $(date -Is) clauses $id"
    .venv/bin/python -m ugrc clauses --db "$out" --out "$out" --workers 8 > "$out.clauses.log" 2>&1 || { echo "CLAUSES FAILED $id"; continue; }
  fi
  echo "== $(date -Is) done $id"
done
echo "prepare finished"
