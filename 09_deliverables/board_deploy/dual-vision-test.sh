#!/bin/sh
set -eu

LEFT_VIDEO=${1:?usage: dual-vision-test.sh left.mp4 right.mp4 [config.json]}
RIGHT_VIDEO=${2:?usage: dual-vision-test.sh left.mp4 right.mp4 [config.json]}
CONFIG=${3:-/etc/smartbag/config.json}

exec python3 /root/smartbag/controller/smartbag_alert_controller.py \
    --config "$CONFIG" \
    --detector-cwd /root/smartbag/vision \
    --left-video "$LEFT_VIDEO" \
    --right-video "$RIGHT_VIDEO" \
    --detector-restart-limit 0 \
    --exit-when-detectors-exit \
    --dry-run \
    --no-ble \
    --no-audio \
    --skip-pinmux
