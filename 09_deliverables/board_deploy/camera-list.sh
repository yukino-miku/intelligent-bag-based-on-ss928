#!/bin/sh
set -eu

echo "== V4L2 devices =="
if command -v v4l2-ctl >/dev/null 2>&1; then
    v4l2-ctl --list-devices
else
    echo "v4l2-ctl is not installed" >&2
fi

echo "== Stable by-id paths =="
if [ -d /dev/v4l/by-id ]; then
    ls -l /dev/v4l/by-id/
else
    echo "/dev/v4l/by-id is unavailable" >&2
fi

echo "== Stable by-path paths =="
if [ -d /dev/v4l/by-path ]; then
    ls -l /dev/v4l/by-path/
else
    echo "/dev/v4l/by-path is unavailable" >&2
fi

echo "== USB topology =="
if command -v lsusb >/dev/null 2>&1; then
    lsusb -t
else
    echo "lsusb is not installed" >&2
    for device in /sys/class/video4linux/video*; do
        [ -e "$device" ] || continue
        printf '%s name=' "${device##*/}"
        cat "$device/name" 2>/dev/null || true
        printf '  device='
        readlink -f "$device/device" 2>/dev/null || true
    done
fi
