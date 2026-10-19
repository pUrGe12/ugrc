#!/usr/bin/env bash
# Ingest the domain expert's 10 papers, one substrate per paper (zero model; tesseract for figure OCR).
cd "$(dirname "$0")/../.."
P=~/Desktop/papers
OUT=${1:-runs/corpus}
declare -A NAME=(
  ["1-s2.0-S1369702120303060-main.pdf"]=mattod-2020
  ["1-s2.0-S221499372030484X-main.pdf"]=susmat-2020
  ["1-s2.0-S2405829720301641-main.pdf"]=ensm-2020
  ["1-s2.0-S2405829721001203-main.pdf"]=ensm-2021
  ["Advanced Energy Materials - 2022 - Muralidharan - Next‐Generation Cobalt‐Free Cathodes   A Prospective Solution to the.pdf"]=aenm-2022
  ["Advanced Materials - 2020 - Muralidharan - Lithium Iron Aluminum Nickelate  LiNixFeyAlzO2 New Sustainable Cathodes for.pdf"]=adma-2020
  ["ChemSusChem - 2020 - Bai - Sustainable Direct Recycling of Lithium‐Ion Batteries via Solvent Recovery of Electrode.pdf"]=cssc-2020
  ["nl6b05172.pdf"]=nanolett-6b05172
  ["nl6b05174.pdf"]=nanolett-6b05174
  ["nn7b02404.pdf"]=acsnano-7b02404
)
for f in "${!NAME[@]}"; do
  out=$OUT/${NAME[$f]}
  [ -e "$out/atoms.duckdb" ] && { echo "skip $out"; continue; }
  echo "== $(date -Is) ${NAME[$f]}"
  .venv/bin/python -m ugrc ingest "$P/$f" --out "$out" 2>&1
done
echo "all done"
