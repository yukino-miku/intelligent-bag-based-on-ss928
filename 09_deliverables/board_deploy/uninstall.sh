#!/bin/sh
set -eu

ROOT_PREFIX=${SMARTBAG_ROOT_PREFIX:-}
SYSTEMD_DIR="$ROOT_PREFIX/etc/systemd/system"
RUNTIME_DIR="$ROOT_PREFIX/root/smartbag"
if [ -z "$ROOT_PREFIX" ]; then
    [ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
    systemctl stop smartbag.target 2>/dev/null || true
    systemctl disable smartbag.target 2>/dev/null || true
fi
rm -f "$SYSTEMD_DIR/smartbag-vision.service" \
      "$SYSTEMD_DIR/smartbag-alert.service" \
      "$SYSTEMD_DIR/smartbag-video.service" \
      "$SYSTEMD_DIR/smartbag-gnss.service" \
      "$SYSTEMD_DIR/smartbag-imu.service" \
      "$SYSTEMD_DIR/smartbag-connectivity.service" \
      "$SYSTEMD_DIR/smartbag-temperature.service" \
      "$SYSTEMD_DIR/smartbag-ws73.service" \
      "$SYSTEMD_DIR/smartbag.target"
if [ -z "$ROOT_PREFIX" ]; then
    systemctl daemon-reload
fi
rm -rf "$RUNTIME_DIR"
echo "Runtime removed. /etc/smartbag, /var/lib/smartbag and /var/log/smartbag were retained."
