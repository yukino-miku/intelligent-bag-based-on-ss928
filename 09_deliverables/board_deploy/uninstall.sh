#!/bin/sh
set -eu

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
systemctl stop smartbag.target 2>/dev/null || true
systemctl disable smartbag.target 2>/dev/null || true
rm -f /etc/systemd/system/smartbag-vision.service \
      /etc/systemd/system/smartbag-alert.service \
      /etc/systemd/system/smartbag-gnss.service \
      /etc/systemd/system/smartbag-imu.service \
      /etc/systemd/system/smartbag.target
systemctl daemon-reload
rm -rf /root/smartbag
echo "Runtime removed. /etc/smartbag and /var/lib/smartbag were retained."
