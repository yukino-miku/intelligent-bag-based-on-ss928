#!/bin/sh
set -eu

ROOT=${1:-/sys/class/pwm}
for chip in "$ROOT"/pwmchip*; do
    [ -d "$chip" ] || continue
    printf '%s npwm=%s\n' "$chip" "$(cat "$chip/npwm" 2>/dev/null || echo unknown)"
    for channel in "$chip"/pwm*; do
        [ -d "$channel" ] || continue
        printf '  %s enable=%s period=%s duty=%s\n' \
            "$(basename "$channel")" \
            "$(cat "$channel/enable" 2>/dev/null || echo unknown)" \
            "$(cat "$channel/period" 2>/dev/null || echo unknown)" \
            "$(cat "$channel/duty_cycle" 2>/dev/null || echo unknown)"
    done
done
