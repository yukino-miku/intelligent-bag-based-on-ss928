#!/bin/sh
set -eu

VISION_ROOT=${VISION_ROOT:-/root/smartbag/vision}
LEFT_DEVICE=${LEFT_DEVICE:-/dev/v4l/by-path/platform-10320000.xhci_1-usb-0:1.3:1.0-video-index0}
RIGHT_DEVICE=${RIGHT_DEVICE:-/dev/v4l/by-path/platform-10320000.xhci_1-usb-0:1.4:1.0-video-index0}
OUTPUT_DIR=${OUTPUT_DIR:-/var/log/smartbag/alternating-camera-runs}

exec /usr/bin/python3 "$VISION_ROOT/alternating_camera_test.py" \
    --left-device "$LEFT_DEVICE" \
    --right-device "$RIGHT_DEVICE" \
    --width "${WIDTH:-640}" \
    --height "${HEIGHT:-480}" \
    --fps "${FPS:-30}" \
    --slice-ms "${SLICE_MS:-300}" \
    --warmup-frames "${WARMUP_FRAMES:-0}" \
    --frames-per-slice "${FRAMES_PER_SLICE:-4}" \
    --switch-count "${SWITCH_COUNT:-0}" \
    --duration-s "${DURATION_S:-120}" \
    --output-dir "$OUTPUT_DIR" \
    "$@"
