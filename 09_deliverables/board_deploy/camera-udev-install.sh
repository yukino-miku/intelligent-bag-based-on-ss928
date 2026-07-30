#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
python3 "$SCRIPT_DIR/camera_discovery.py" rules
udevadm control --reload-rules
udevadm trigger --subsystem-match=video4linux
sleep 1
[ -e /dev/smartbag-camera-left ] || { echo "left camera symlink was not created" >&2; exit 1; }
[ -e /dev/smartbag-camera-right ] || { echo "right camera symlink was not created" >&2; exit 1; }
[ "$(readlink -f /dev/smartbag-camera-left)" != "$(readlink -f /dev/smartbag-camera-right)" ] || {
    echo "camera symlinks resolve to the same device" >&2
    exit 1
}
echo "Installed stable camera links: /dev/smartbag-camera-left and /dev/smartbag-camera-right"
