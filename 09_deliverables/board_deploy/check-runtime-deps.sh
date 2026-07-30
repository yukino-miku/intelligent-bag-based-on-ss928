#!/bin/sh
set -eu

CONFIG=${1:-/etc/smartbag/config.json}
fail=0
RUNTIME_MODE=legacy_dual_vision
SNAPSHOT_BACKEND=ss928_om
if [ -f "$CONFIG" ]; then
    RUNTIME_MODE=$(python3 - "$CONFIG" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
print(data.get("runtime_mode", "legacy_dual_vision"))
PY
    )
    SNAPSHOT_BACKEND=$(python3 - "$CONFIG" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
print(data.get("snapshot_classifier", {}).get("backend", "ss928_om"))
PY
    )
fi

# The broader board checker owns architecture, disk, ACL and physical-device
# validation. This file remains the Python dependency probe used by preflight.

COMMANDS="python3 curl bluetoothctl"
if [ "$RUNTIME_MODE" != "radar_only" ]; then
    COMMANDS="$COMMANDS v4l2-ctl"
fi
for command_name in $COMMANDS; do
    if command -v "$command_name" >/dev/null 2>&1; then
        echo "OK   $command_name"
    else
        echo "MISS $command_name" >&2
        fail=1
    fi
done

if command -v ffmpeg >/dev/null 2>&1; then
    echo "OK   ffmpeg (optional for diagnostics/video conversion)"
else
    echo "WARN ffmpeg missing; direct OpenCV UVC and snapshot/MJPEG do not require it" >&2
fi

if command -v gst-launch-1.0 >/dev/null 2>&1; then
    echo "OK   gst-launch-1.0 (optional)"
else
    echo "WARN gst-launch-1.0 missing; snapshot/MJPEG baseline does not require it" >&2
fi

python3 - "$RUNTIME_MODE" "$SNAPSHOT_BACKEND" <<'PY' || fail=1
import importlib
import platform
import sys

print(f"ARCH {platform.machine()}")
print(f"PYTHON {sys.version.split()[0]}")
runtime_mode = sys.argv[1]
snapshot_backend = sys.argv[2]
required = ["dbus", "gi"]
if runtime_mode == "legacy_dual_vision":
    required += ["cv2", "numpy", "torch", "ultralytics", "lap"]
elif runtime_mode == "radar_primary_visual_classification":
    required += ["cv2", "numpy"]
    if snapshot_backend == "ultralytics":
        required += ["torch", "ultralytics"]
missing = []
for name in required:
    try:
        module = importlib.import_module(name)
        version = getattr(module, "__version__", "present")
        print(f"OK   python:{name} {version}")
    except Exception as exc:
        print(f"MISS python:{name} ({exc})", file=sys.stderr)
        missing.append(name)
if missing:
    raise SystemExit(1)
PY

[ "$fail" -eq 0 ] || exit 1
