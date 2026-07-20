#!/bin/sh
set -eu

PROFILE=${1:-/etc/smartbag/hardware.json}
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -f /root/smartbag/common/hardware_profile.py ]; then
    COMMON=/root/smartbag/common
else
    COMMON=$(CDPATH= cd -- "$SCRIPT_DIR/../../06_software/board_runtime/common" && pwd)
fi
PYTHONPATH="$COMMON" python3 - "$PROFILE" <<'PY'
import json, sys
from hardware_profile import validate_hardware_profile
validate_hardware_profile(json.load(open(sys.argv[1], encoding="utf-8")))
print("profile_schema=valid")
PY
python3 - "$PROFILE" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
print("profile=" + cfg["profile"])
print("mux=" + str(cfg.get("i2c_mux", {})))
print("haptics=" + str(cfg.get("haptics", {}).get("backend")))
print("lights=" + str(cfg.get("lights", {}).get("enabled")))
PY

for path in /dev/i2c-0 /sys/class/pwm /run/lock; do
    [ -e "$path" ] && echo "OK $path" || { echo "MISS $path" >&2; exit 1; }
done
command -v bspmm >/dev/null 2>&1 && echo "OK bspmm" || { echo "MISS bspmm" >&2; exit 1; }
"$(dirname "$0")/pwm-list.sh"
echo "Read-only hardware preflight passed; this does not verify physical LRA/light response."
