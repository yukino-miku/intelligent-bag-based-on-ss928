#!/bin/sh
set -eu

fail=0
PYTHON=${SMARTBAG_PYTHON:-/root/smartbag/venv/bin/python}
[ -x "$PYTHON" ] || PYTHON=python3
for command_name in python3 curl v4l2-ctl bluetoothctl; do
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

"$PYTHON" - <<'PY' || fail=1
import importlib
import platform
import sys

print(f"ARCH {platform.machine()}")
print(f"PYTHON {sys.version.split()[0]}")
missing = []
for name in ("cv2", "numpy", "torch", "torchvision", "ultralytics", "lap", "dbus", "gi"):
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

if [ -f /opt/lib/npu/libascendcl.so ]; then
    echo "OK   SS928 ACL runtime /opt/lib/npu/libascendcl.so"
    echo "INFO NPU samples require LD_LIBRARY_PATH=/opt/lib/npu:/opt/lib"
else
    echo "WARN SS928 ACL runtime not found; CPU mode can still be checked" >&2
fi

[ "$fail" -eq 0 ] || exit 1
