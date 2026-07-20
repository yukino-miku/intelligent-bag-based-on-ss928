#!/bin/sh
set -eu

SIDE=${1:-}
LEVEL=${2:-}
CONFIRM=${3:-}
[ "$SIDE" = left ] || [ "$SIDE" = right ] || { echo "usage: $0 left|right 1|2|3|4 --confirm-live-output" >&2; exit 2; }
case "$LEVEL" in 1|2|3|4) ;; *) echo "level must be 1, 2, 3 or 4" >&2; exit 2;; esac
[ "$CONFIRM" = --confirm-live-output ] || { echo "refusing physical output without --confirm-live-output" >&2; exit 2; }

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=${SMARTBAG_PYTHON:-/root/smartbag/venv/bin/python}
[ -x "$PYTHON" ] || PYTHON=python3
"$PYTHON" - "$SIDE" "$LEVEL" "$SCRIPT_DIR" <<'PY'
import json
import sys
import time
from pathlib import Path

side, level, script_dir = sys.argv[1], int(sys.argv[2]), Path(sys.argv[3])
for controller in (
    Path("/root/smartbag/controller"),
    script_dir.parents[1] / "06_software/board_runtime/smartbag_alert_controller",
):
    if (controller / "lights.py").exists():
        sys.path.insert(0, str(controller))
        common = controller.parent / "common"
        if common.exists():
            sys.path.insert(0, str(common))
        break
from lights import LinuxSysfsPwm, PwmChannelSpec, PwmLightBackend

hardware_path = Path("/etc/smartbag/hardware.json")
if hardware_path.exists():
    lights = json.loads(hardware_path.read_text(encoding="utf-8"))["lights"]
else:
    lights = {
        "period_ns": 1_000_000,
        "left": {"chip": 0, "channel": 10, "pin": 7},
        "right": {"chip": 0, "channel": 1, "pin": 32},
        "level_patterns": {
            "0": {"duty_percent": 0, "on_ms": 0, "off_ms": 0, "repeat": False, "mode": "off"},
            "1": {"duty_percent": 0, "on_ms": 0, "off_ms": 0, "repeat": False, "mode": "off"},
            "2": {"duty_percent": 0, "on_ms": 0, "off_ms": 0, "repeat": False, "mode": "off"},
            "3": {"duty_percent": 50, "on_ms": 1000, "off_ms": 1000, "repeat": True, "mode": "slow_blink"},
            "4": {"duty_percent": 80, "on_ms": 200, "off_ms": 200, "repeat": True, "mode": "fast_blink"},
        },
    }
channels = {
    name: PwmChannelSpec(name, int(lights[name]["channel"]), int(lights[name]["pin"]), lights[name].get("chip", "auto"))
    for name in ("left", "right")
}
backend = PwmLightBackend(
    LinuxSysfsPwm(), channels, lights["level_patterns"], period_ns=int(lights["period_ns"])
)
try:
    backend.setup()
    levels = {"left": 0, "right": 0}
    levels[side] = level
    backend.apply_levels(levels)
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        backend.tick()
        time.sleep(0.02)
    print(json.dumps(backend.status(), sort_keys=True))
finally:
    backend.stop_all()
PY
