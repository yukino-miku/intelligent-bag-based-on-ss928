#!/bin/sh
set -eu

ROOT=${1:-/var/log/smartbag/alternating-camera-runs}
SESSION=$(find "$ROOT" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort | tail -1)
[ -n "$SESSION" ] || { echo "no alternating-camera session under $ROOT" >&2; exit 1; }
printf 'Session: %s\n\n' "$SESSION"
cat "$SESSION/summary.md"
