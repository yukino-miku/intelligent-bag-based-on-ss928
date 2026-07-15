#!/bin/sh
set -eu

fail=0
check_path() {
    if [ -e "$1" ]; then
        printf 'OK   %s\n' "$1"
    else
        printf 'MISS %s\n' "$1" >&2
        fail=1
    fi
}

command -v python3 >/dev/null 2>&1 || { echo "MISS python3" >&2; fail=1; }
command -v bspmm >/dev/null 2>&1 || { echo "MISS bspmm" >&2; fail=1; }
check_path /dev/video0
check_path /dev/i2c-0
check_path /dev/ttyAMA4
check_path /sys/class/pwm/pwmchip0

if [ -r /sys/class/pwm/pwmchip0/npwm ]; then
    npwm=$(cat /sys/class/pwm/pwmchip0/npwm)
    [ "$npwm" -ge 16 ] || { echo "MISS pwmchip0 needs at least 16 channels, got $npwm" >&2; fail=1; }
fi

[ "$fail" -eq 0 ] || exit 1
echo "Preflight passed. Camera frame, sensor data, BLE and NPU still require functional tests."
