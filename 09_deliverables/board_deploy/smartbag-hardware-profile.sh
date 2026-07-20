#!/bin/sh
set -eu

ACTION=${1:-show}
PROFILE=${2:-}
CONFIG=/etc/smartbag/hardware.json
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROFILE_DIR="$SCRIPT_DIR/hardware-profiles"
PYTHON=${SMARTBAG_PYTHON:-/root/smartbag/venv/bin/python}
[ -x "$PYTHON" ] || PYTHON=python3

show() {
    [ -f "$CONFIG" ] || { echo "missing $CONFIG" >&2; exit 1; }
    "$PYTHON" -m json.tool "$CONFIG"
}

set_profile() {
    case "$PROFILE" in
        rev2_tm6605_mr20|legacy_pwm_haptics) ;;
        *) echo "profile must be rev2_tm6605_mr20 or legacy_pwm_haptics" >&2; exit 2 ;;
    esac
    [ "$(id -u)" -eq 0 ] || { echo "set requires root" >&2; exit 1; }
    source_file="$PROFILE_DIR/$PROFILE.json"
    [ -f "$source_file" ] || { echo "missing profile $source_file" >&2; exit 1; }
    backup="$CONFIG.bak.$(date -u +%Y%m%dT%H%M%SZ)"
    was_active=0
    systemctl is-active --quiet smartbag.target && was_active=1 || true
    systemctl stop smartbag.target smartbag-controller.service smartbag-alert.service 2>/dev/null || true
    "$PYTHON" "$SCRIPT_DIR/safe_off.py" --hardware "$CONFIG" 2>/dev/null || true
    [ -f "$CONFIG" ] && cp "$CONFIG" "$backup" || backup=""
    cp "$source_file" "$CONFIG"
    if ! PYTHONPATH=/root/smartbag/common "$PYTHON" - "$CONFIG" <<'PY'
import json, sys
from hardware_profile import validate_hardware_profile
validate_hardware_profile(json.load(open(sys.argv[1], encoding="utf-8")))
PY
    then
        [ -n "$backup" ] && cp "$backup" "$CONFIG"
        [ "$was_active" -eq 1 ] && systemctl start smartbag.target || true
        echo "profile validation failed; restored $backup" >&2
        exit 1
    fi
    if [ "$was_active" -eq 1 ] && ! systemctl start smartbag.target; then
        [ -n "$backup" ] && cp "$backup" "$CONFIG"
        systemctl start smartbag.target || true
        echo "new profile startup failed; restored $backup" >&2
        exit 1
    fi
    echo "profile=$PROFILE backup=${backup:-none}"
    echo "confirm wiring against 04_hardware/ss928/40pin-usage.md before physical output tests"
}

case "$ACTION" in
    show) show ;;
    set) set_profile ;;
    *) echo "usage: $0 show | set <profile>" >&2; exit 2 ;;
esac
