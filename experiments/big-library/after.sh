#!/usr/bin/env bash
# Wait until LOG holds N "prepare finished" lines, then run the rest of the arguments.
log=$1; n=$2; shift 2
until [ "$(grep -c 'prepare finished' "$log" 2>/dev/null)" -ge "$n" ]; do sleep 20; done
exec "$@"
