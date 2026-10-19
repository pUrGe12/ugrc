#!/usr/bin/env bash
# Jev as the judge: jev-latest and jev-preview, v6 and v5 questions, paper 2 (dev) and paper 3 (held-out).
set -u
cd "$(dirname "$0")"
LOG=runs/matrix-jev.log
export JEV_API_KEY="$(cat ~/.jev_key)"
for model in jev-latest jev-preview; do
  for v in v6 v5; do
    for p in 2 3; do
      out=runs/p$p-$v-$model
      [ -e "$out/clauses.duckdb" ] && { echo "skip $out (exists)" >> $LOG; continue; }
      echo "$(date -Is) start $out" >> $LOG
      ../../.venv/bin/python run.py $v ../../runs/paper$p $out --model $model --workers 8 >> $LOG 2>&1
      echo "$(date -Is) done  $out (exit $?)" >> $LOG
    done
  done
done
