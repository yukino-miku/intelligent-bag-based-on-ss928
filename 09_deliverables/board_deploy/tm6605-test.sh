#!/bin/sh
set -eu

SIDE=${1:-}
LEVEL=${2:-}
CONFIRM=${3:-}
[ "$SIDE" = left ] || [ "$SIDE" = right ] || { echo "usage: $0 left|right 3|4 --confirm-live-output" >&2; exit 2; }
[ "$LEVEL" = 3 ] || [ "$LEVEL" = 4 ] || { echo "level must be 3 or 4" >&2; exit 2; }
[ "$CONFIRM" = --confirm-live-output ] || { echo "refusing physical output without --confirm-live-output" >&2; exit 2; }

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python3 - "$SIDE" "$LEVEL" "$SCRIPT_DIR" <<'PY'
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
patterns = {
    0: {"effect": 0, "count": 0, "interval_ms": 0},
    1: {"effect": 0, "count": 0, "interval_ms": 0},
    2: {"effect": 0, "count": 0, "interval_ms": 0},
    3: {"effect": 15, "count": 3, "interval_ms": 750},
    4: {"effect": 14, "count": 3, "interval_ms": 300},
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
