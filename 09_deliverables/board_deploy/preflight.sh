#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CONFIG=${1:-/etc/smartbag/config.json}
fail=0

check_path() {
    if [ -e "$1" ]; then
        printf 'OK   %s\n' "$1"
    else
        printf 'MISS %s\n' "$1" >&2
        fail=1
    fi
}

config_value() {
    python3 - "$CONFIG" "$1" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
value = data
for part in sys.argv[2].split("."):
    value = value[part]
print(value)
PY
}

check_path "$CONFIG"
LEFT_DEVICE=$(config_value cameras.left.camera_device)
RIGHT_DEVICE=$(config_value cameras.right.camera_device)
LEFT_CALIBRATION=$(config_value cameras.left.calibration_file)
RIGHT_CALIBRATION=$(config_value cameras.right.calibration_file)
MODEL=$(config_value paths.model)
HARDWARE=$(config_value hardware_profile_file)
VIDEO_PORT=$(config_value stream_gateway.port)
LEFT_STREAM_PORT=$(config_value cameras.left.stream_port)
RIGHT_STREAM_PORT=$(config_value cameras.right.stream_port)

LEFT_REAL=$(readlink -f "$LEFT_DEVICE" 2>/dev/null || printf '%s' "$LEFT_DEVICE")
RIGHT_REAL=$(readlink -f "$RIGHT_DEVICE" 2>/dev/null || printf '%s' "$RIGHT_DEVICE")
if [ "$LEFT_REAL" = "$RIGHT_REAL" ]; then
    echo "FAIL left and right camera devices are identical: $LEFT_DEVICE" >&2
    fail=1
fi
if [ "$LEFT_STREAM_PORT" = "$RIGHT_STREAM_PORT" ]; then
    echo "FAIL left and right detector stream ports are identical" >&2
    fail=1
fi

for path in "$LEFT_DEVICE" "$RIGHT_DEVICE" "$LEFT_CALIBRATION" "$RIGHT_CALIBRATION" "$MODEL" "$HARDWARE" /dev/i2c-0 /dev/ttyAMA4 /sys/class/pwm; do
    check_path "$path"
done

"$SCRIPT_DIR/hardware-preflight.sh" "$HARDWARE" || fail=1

for port in "$VIDEO_PORT" "$LEFT_STREAM_PORT" "$RIGHT_STREAM_PORT"; do
    if python3 - "$port" <<'PY'
import socket
import sys

sock = socket.socket()
try:
    sock.bind(("127.0.0.1", int(sys.argv[1])))
finally:
    sock.close()
PY
    then
        echo "OK   port $port available"
    else
        echo "MISS port $port is occupied" >&2
        fail=1
    fi
done

if command -v v4l2-ctl >/dev/null 2>&1; then
    v4l2-ctl --device "$LEFT_DEVICE" --list-formats-ext || fail=1
    v4l2-ctl --device "$RIGHT_DEVICE" --list-formats-ext || fail=1
else
    echo "MISS v4l2-ctl" >&2
    fail=1
fi

camera_test_dir=$(mktemp -d)
trap 'rm -rf "$camera_test_dir"' EXIT INT TERM
"$SCRIPT_DIR/camera-test.sh" "$LEFT_DEVICE" >"$camera_test_dir/left.log" 2>&1 &
left_camera_pid=$!
"$SCRIPT_DIR/camera-test.sh" "$RIGHT_DEVICE" >"$camera_test_dir/right.log" 2>&1 &
right_camera_pid=$!
if wait "$left_camera_pid"; then
    cat "$camera_test_dir/left.log"
else
    cat "$camera_test_dir/left.log" >&2
    fail=1
fi
if wait "$right_camera_pid"; then
    cat "$camera_test_dir/right.log"
else
    cat "$camera_test_dir/right.log" >&2
    fail=1
fi
"$SCRIPT_DIR/check-runtime-deps.sh" || fail=1

systemctl is-active --quiet bluetooth.service || { echo "MISS bluetooth.service is not active" >&2; fail=1; }

[ "$fail" -eq 0 ] || exit 1
echo "Preflight passed. This does not prove dual-camera USB bandwidth, inference FPS, temperature, or phone playback."
