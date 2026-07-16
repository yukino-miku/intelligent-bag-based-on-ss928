#!/bin/sh
set -eu

MODE=${1:-check}
ARCH=$(uname -m)
echo "Detected architecture: $ARCH"
case "$ARCH" in
    aarch64|arm64) ;;
    *) echo "WARN expected SS928 userspace architecture aarch64; got $ARCH" >&2 ;;
esac

if [ "$MODE" = "--install-system" ]; then
    [ "$(id -u)" -eq 0 ] || { echo "run as root for --install-system" >&2; exit 1; }
    apt-get update
    apt-get install -y python3 python3-pip python3-opencv v4l-utils ffmpeg gstreamer1.0-tools bluez python3-dbus python3-gi curl usbutils
    echo "System packages installed. Ultralytics, torch and lap were not installed automatically."
    echo "Use board-compatible ARM wheels or a verified local package source; do not assume PyPI wheels match this image."
fi

"$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/check-runtime-deps.sh"
