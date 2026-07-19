#!/bin/sh
set -eu

CONFIG=${1:-/etc/smartbag/config.json}
fail=0
[ -f "$CONFIG" ] || { echo "FAIL config missing: $CONFIG" >&2; exit 1; }

eval "$(python3 - "$CONFIG" <<'PY'
import json, shlex, sys
c = json.load(open(sys.argv[1], encoding="utf-8"))
a = c.get("alternating_camera", {})
p = c.get("paths", {})
cams = c.get("cameras", {})
values = {
    "MODE": c.get("vision_runtime", {}).get("mode", "fixed_dual_process"),
    "ENABLED": str(bool(a.get("enabled", False))).lower(),
    "LEFT": cams.get("left", {}).get("camera_device", ""),
    "RIGHT": cams.get("right", {}).get("camera_device", ""),
    "LEFT_CAL": cams.get("left", {}).get("calibration_file", ""),
    "RIGHT_CAL": cams.get("right", {}).get("calibration_file", ""),
    "MODEL": p.get("model", ""),
    "VISION": p.get("vision", "/root/smartbag/vision"),
    "PORT": a.get("serve_port", 8080),
    "CAL_MODE": a.get("calibration_mode", "diagnostic"),
}
for key, value in values.items():
    print(f"{key}={shlex.quote(str(value))}")
PY
)"

[ "$MODE" = alternating_single_model ] || { echo "FAIL vision_runtime.mode=$MODE" >&2; fail=1; }
[ "$ENABLED" = true ] || { echo "FAIL alternating_camera.enabled is false" >&2; fail=1; }

for path in "$LEFT" "$RIGHT" "$LEFT_CAL" "$RIGHT_CAL" "$MODEL"; do
    [ -e "$path" ] && echo "OK   $path" || { echo "FAIL missing: $path" >&2; fail=1; }
done

LEFT_REAL=$(readlink -f "$LEFT" 2>/dev/null || printf '%s' "$LEFT")
RIGHT_REAL=$(readlink -f "$RIGHT" 2>/dev/null || printf '%s' "$RIGHT")
[ "$LEFT_REAL" != "$RIGHT_REAL" ] || { echo "FAIL camera devices resolve to the same node" >&2; fail=1; }

for device in "$LEFT_REAL" "$RIGHT_REAL"; do
    if command -v fuser >/dev/null 2>&1 && fuser "$device" >/dev/null 2>&1; then
        echo "FAIL camera occupied: $device" >&2
        fail=1
    else
        echo "OK   camera free: $device"
    fi
done

if python3 - "$PORT" <<'PY'
import socket, sys
s = socket.socket()
try:
    s.bind(("127.0.0.1", int(sys.argv[1])))
finally:
    s.close()
PY
then
    echo "OK   gateway port $PORT available"
else
    echo "FAIL gateway port $PORT occupied" >&2
    fail=1
fi

CAL_CHECKER="$VISION/tools/check_camera_calibration.py"
[ -f "$CAL_CHECKER" ] || { echo "FAIL calibration checker missing: $CAL_CHECKER" >&2; fail=1; }
if [ -f "$CAL_CHECKER" ]; then
    python3 "$CAL_CHECKER" "$LEFT_CAL" --side left --mode "$CAL_MODE" || fail=1
    python3 "$CAL_CHECKER" "$RIGHT_CAL" --side right --mode "$CAL_MODE" || fail=1
fi
[ "$CAL_MODE" = production ] || echo "WARN calibration_mode=diagnostic; placeholder extrinsics are allowed" >&2

python3 - <<'PY' || fail=1
import importlib
for name in ("cv2", "numpy", "torch", "ultralytics", "lap"):
    module = importlib.import_module(name)
    print("OK   python:%s %s" % (name, getattr(module, "__version__", "present")))
PY

[ -r /sys/class/pwm/pwmchip0/npwm ] || { echo "FAIL pwmchip0 unavailable" >&2; fail=1; }
[ "$fail" -eq 0 ] || exit 1
echo "Alternating preflight passed; this does not replace the 30-minute hardware test."
