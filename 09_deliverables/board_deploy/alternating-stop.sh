#!/bin/sh
set -eu
systemctl stop smartbag-alternating-vision.service
systemctl is-active --quiet smartbag-alternating-vision.service && {
    echo "FAIL service is still active" >&2
    exit 1
}
for device in /dev/video0 /dev/video2; do
    if [ -e "$device" ] && fuser "$device" >/dev/null 2>&1; then
        echo "FAIL camera remains occupied: $device" >&2
        exit 1
    fi
done
for channel in 1 10 14 15; do
    duty=/sys/class/pwm/pwmchip0/pwm${channel}/duty_cycle
    [ ! -r "$duty" ] || [ "$(cat "$duty")" = 0 ] || {
        echo "FAIL pwm${channel} duty_cycle is not zero" >&2
        exit 1
    }
done
echo "Stopped: service inactive, cameras released, exported PWM duty cycles are zero."
