#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
WHEELHOUSE=${1:-}

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
apt-get update
apt-get install -y \
    python3 python3-pip python3-numpy python3-opencv python3-scipy \
    v4l-utils ffmpeg bluez python3-dbus python3-gi curl usbutils

if [ -n "$WHEELHOUSE" ]; then
    "$SCRIPT_DIR/install-board-deps-offline.sh" "$WHEELHOUSE"
else
    echo "System OpenCV/NumPy installed; this is sufficient for the ss928_om Python path."
    echo "Only the optional ultralytics CPU backend needs verified aarch64 torch/Ultralytics/lap wheels."
fi

"$SCRIPT_DIR/check-runtime-deps.sh" || true
