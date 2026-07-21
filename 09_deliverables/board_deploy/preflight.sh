#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CONFIG=${1:-/etc/smartbag/config.json}
PYTHON=${SMARTBAG_PYTHON:-/root/smartbag/venv/bin/python}
[ -x "$PYTHON" ] || PYTHON=python3
fail=0

config_value() {
    "$PYTHON" - "$CONFIG" "$1" <<'PY'
import json, sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
for part in sys.argv[2].split("."):
    value = value[part]
print(value)
PY
}

"$PYTHON" "$SCRIPT_DIR/wait_for_hardware.py" \
    --profile controller --config "$CONFIG" --timeout-s 30 || fail=1

LEFT_DEVICE=$(config_value cameras.left.camera_device)
RIGHT_DEVICE=$(config_value cameras.right.camera_device)
HARDWARE=$(config_value hardware_profile_file)
VIDEO_PORT=$(config_value alternating_camera.serve_port)
LEFT_REAL=$(readlink -f "$LEFT_DEVICE" 2>/dev/null || printf '%s' "$LEFT_DEVICE")
RIGHT_REAL=$(readlink -f "$RIGHT_DEVICE" 2>/dev/null || printf '%s' "$RIGHT_DEVICE")
[ "$LEFT_REAL" != "$RIGHT_REAL" ] || { echo "FAIL left and right cameras resolve to one node" >&2; fail=1; }

"$SCRIPT_DIR/hardware-preflight.sh" "$HARDWARE" || fail=1

if "$PYTHON" - "$VIDEO_PORT" <<'PY'
import socket, sys
sock = socket.socket()
try: sock.bind(("127.0.0.1", int(sys.argv[1])))
finally: sock.close()
PY
then
    echo "OK   local video port $VIDEO_PORT available"
else
    echo "MISS local video port $VIDEO_PORT is occupied" >&2
    fail=1
fi

if command -v v4l2-ctl >/dev/null 2>&1; then
    v4l2-ctl --device "$LEFT_DEVICE" --list-formats-ext || fail=1
    v4l2-ctl --device "$RIGHT_DEVICE" --list-formats-ext || fail=1
else
    echo "MISS v4l2-ctl" >&2
    fail=1
fi

# Alternating runtime owns one UVC stream at a time, so probe the two paths sequentially.
"$SCRIPT_DIR/camera-test.sh" "$LEFT_DEVICE" || fail=1
"$SCRIPT_DIR/camera-test.sh" "$RIGHT_DEVICE" || fail=1
"$SCRIPT_DIR/check-runtime-deps.sh" "$CONFIG" || fail=1

systemctl is-active --quiet bluetooth.service \
    && echo "OK   bluetooth.service active" \
    || echo "WARN bluetooth.service unavailable; local alerting remains available" >&2

[ "$fail" -eq 0 ] || exit 1
echo "Preflight passed for alternating single-model runtime; no physical actuator was energized."
