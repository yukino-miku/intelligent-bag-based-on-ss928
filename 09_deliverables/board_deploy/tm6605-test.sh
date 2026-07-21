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
script_dir = Path(sys.argv[3])
candidates = [
    (Path("/root/smartbag/controller"), Path("/root/smartbag/common")),
    (
        script_dir.parents[1] / "06_software/board_runtime/smartbag_alert_controller",
        script_dir.parents[1] / "06_software/board_runtime/common",
    ),
]
for controller, common in candidates:
    if (controller / "haptics.py").exists():
        sys.path[:0] = [str(controller), str(common)]
        break
from haptics import Tm6605HapticBackend
from i2c_mux import I2cMuxTransaction

side, level = sys.argv[1], int(sys.argv[2])
channel = 1 if side == "left" else 2
hardware_path = Path("/etc/smartbag/hardware.json")
if hardware_path.exists():
    patterns = json.loads(hardware_path.read_text(encoding="utf-8"))["haptics"]["level_effects"]
else:
    patterns = {
        0: {"effect": 0, "repeat_interval_ms": 0},
        1: {"effect": 15, "repeat_interval_ms": 1800},
        2: {"effect": 15, "repeat_interval_ms": 1000},
        3: {"effect": 15, "repeat_interval_ms": 600},
        4: {"effect": 14, "repeat_interval_ms": 300},
    }
backend = Tm6605HapticBackend({side: I2cMuxTransaction("/dev/i2c-0", 0x2D, mux_address=0x70, mux_channel=channel)}, patterns)
try:
    backend.preflight()
    backend.setup()
    backend.apply_levels({side: level})
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        backend.tick()
        time.sleep(0.02)
    print(backend.status())
finally:
    backend.stop_all()
PY
