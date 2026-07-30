#!/bin/sh
set -eu

CONFIG=/etc/smartbag/config.json
MODE=full
while [ "$#" -gt 0 ]; do
    case "$1" in
        --config) CONFIG=$2; shift 2 ;;
        --mode) MODE=$2; shift 2 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done
case "$MODE" in full|radar-only) ;; *) echo "mode must be full or radar-only" >&2; exit 2 ;; esac

fail=0
ok() { printf 'OK   %s\n' "$1"; }
miss() { printf 'MISS %s\n' "$1" >&2; fail=1; }
warn() { printf 'WARN %s\n' "$1" >&2; }
has_command() { command -v "$1" >/dev/null 2>&1 && ok "command $1" || miss "command $1"; }

case "$(uname -m)" in aarch64|arm64) ok "architecture $(uname -m)" ;; *) miss "architecture $(uname -m), expected aarch64" ;; esac
if [ -r /etc/os-release ]; then
    . /etc/os-release
    ok "OS ${PRETTY_NAME:-unknown}"
else
    miss "/etc/os-release"
fi
ok "kernel $(uname -r)"

MEM_MIB=$(awk '/MemTotal:/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
[ "$MEM_MIB" -ge 768 ] && ok "memory ${MEM_MIB} MiB" || miss "memory ${MEM_MIB} MiB, minimum 768 MiB"
FREE_MIB=$(df -Pm /root 2>/dev/null | awk 'NR==2 {print $4}' || echo 0)
[ "$FREE_MIB" -ge 2048 ] && ok "free disk ${FREE_MIB} MiB" || miss "free disk ${FREE_MIB} MiB, minimum 2048 MiB"

for command_name in python3 systemctl ip ldconfig; do has_command "$command_name"; done
[ -f "$CONFIG" ] && ok "$CONFIG" || miss "$CONFIG"
[ -e /dev/i2c-0 ] && ok "/dev/i2c-0" || miss "/dev/i2c-0"
[ -d /sys/class/pwm/pwmchip0 ] && ok "pwmchip0" || miss "pwmchip0"
[ -r /proc/Tsensor ] && ok "/proc/Tsensor" || warn "/proc/Tsensor unavailable; temperature is optional"
if systemctl is-active --quiet bluetooth.service 2>/dev/null || command -v bluetoothctl >/dev/null 2>&1; then
    ok "Bluetooth userspace"
else
    warn "Bluetooth unavailable; local risk/haptics can run but phone BLE cannot"
fi

if [ "$MODE" = full ]; then
    has_command v4l2-ctl
    [ -e /dev/smartbag-camera-left ] && ok "left stable camera" || miss "/dev/smartbag-camera-left"
    [ -e /dev/smartbag-camera-right ] && ok "right stable camera" || miss "/dev/smartbag-camera-right"
    if [ -e /dev/smartbag-camera-left ] && [ -e /dev/smartbag-camera-right ]; then
        [ "$(readlink -f /dev/smartbag-camera-left)" != "$(readlink -f /dev/smartbag-camera-right)" ] \
            && ok "camera devices are distinct" || miss "camera devices resolve to the same node"
    fi
    if ldconfig -p 2>/dev/null | grep -q 'libascendcl\.so'; then
        ok "libascendcl.so"
    else
        miss "libascendcl.so from matching SS928 board image"
    fi
    [ -x /root/smartbag/vision/ss928_backend/bin/ss928_detection_runner ] \
        && ok "AArch64 detection runner" || miss "detection runner"
    [ -f /root/smartbag/models/vehicle-detector.om ] && ok "vehicle detector OM" || miss "vehicle detector OM"
    [ -f /etc/smartbag/fusion-left.json ] && ok "left fusion config" || miss "left fusion config"
    [ -f /etc/smartbag/fusion-right.json ] && ok "right fusion config" || miss "right fusion config"
fi

[ -f /etc/smartbag/mr20.json ] && ok "MR20 config" || miss "/etc/smartbag/mr20.json"
if [ -f /etc/smartbag/mr20.json ]; then
    python3 - /etc/smartbag/mr20.json <<'PY' || fail=1
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
radars = data.get("radars", [])
if len([item for item in radars if item.get("enabled", True)]) != 2:
    raise SystemExit("MISS MR20 config must contain two enabled radars")
ports = [int(item["port"]) for item in radars]
if len(set(ports)) != len(ports):
    raise SystemExit("MISS MR20 UDP ports must be distinct")
print("OK   two distinct MR20 radar configurations")
PY
fi

[ "$fail" -eq 0 ] || exit 1
echo "Board runtime dependency check passed for mode=$MODE. Hardware behavior is not proven by this static check."
