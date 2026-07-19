#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DURATION_S=${DURATION_S:-120}
COOLDOWN_S=${COOLDOWN_S:-5}

run_case() {
    name=$1
    width=$2
    height=$3
    fps=$4
    echo "[$name] ${width}x${height} MJPEG requested ${fps} FPS"
    WIDTH=$width HEIGHT=$height FPS=$fps DURATION_S=$DURATION_S SWITCH_COUNT=0 \
        "$SCRIPT_DIR/alternating-test.sh"
    sleep "$COOLDOWN_S"
    for device in /dev/video0 /dev/video2; do
        if [ -e "$device" ] && fuser "$device" >/dev/null 2>&1; then
            echo "camera still busy after $name: $device" >&2
            exit 1
        fi
    done
}

run_case A1 640 480 5
run_case A2 640 480 10
run_case A3 320 240 5
run_case A4 320 240 10
