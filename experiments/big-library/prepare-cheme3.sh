#!/usr/bin/env bash
# Once fetch.py has written cheme3.json and the bench-v5 ingest is done, ingest every cheme3 paper.
cd "$(dirname "$0")/../.."
until [ -e experiments/big-library/cheme3.json ] && grep -q 'prepare finished' experiments/big-library/prepare-2.log 2>/dev/null; do sleep 20; done
keys=$(python3 -c "import json;print(' '.join(json.load(open('experiments/big-library/cheme3.json'))))")
exec ./experiments/big-library/prepare.sh cheme3 $keys
