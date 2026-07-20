#!/bin/sh
set -eu

SIDE=${1:-}
LEVEL=${2:-}
CONFIRM=${3:-}
[ "$SIDE" = left ] || [ "$SIDE" = right ] || { echo "usage: $0 left|right 3|4 --confirm-live-output" >&2; exit 2; }
[ "$LEVEL" = 3 ] || [ "$LEVEL" = 4 ] || { echo "level must be 3 or 4" >&2; exit 2; }
[ "$CONFIRM" = --confirm-live-output ] || { echo "refusing physical output without --confirm-live-output" >&2; exit 2; }

if [ "$SIDE" = left ]; then CHANNEL=10; else CHANNEL=1; fi
if [ "$LEVEL" = 3 ]; then
    python3 "$(dirname "$0")/pwm-probe.py" --channel "$CHANNEL" --duty-percent 50 --hold-s 1 --apply
else
    count=0
    while [ "$count" -lt 3 ]; do
        python3 "$(dirname "$0")/pwm-probe.py" --channel "$CHANNEL" --duty-percent 80 --hold-s 0.2 --apply
        sleep 0.2
        count=$((count + 1))
    done
fi
