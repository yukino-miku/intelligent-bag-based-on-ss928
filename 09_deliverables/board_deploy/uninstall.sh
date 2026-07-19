#!/bin/sh
set -eu

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
systemctl stop smartbag.target 2>/dev/null || true
systemctl stop smartbag-alternating-vision.service smartbag-alternating-cleanup.timer 2>/dev/null || true
systemctl disable smartbag.target 2>/dev/null || true
systemctl disable smartbag-alternating-cleanup.timer 2>/dev/null || true
rm -f /etc/systemd/system/smartbag-vision.service \
      /etc/systemd/system/smartbag-alert.service \
      /etc/systemd/system/smartbag-video.service \
      /etc/systemd/system/smartbag-gnss.service \
      /etc/systemd/system/smartbag-imu.service \
      /etc/systemd/system/smartbag-alternating-vision.service \
      /etc/systemd/system/smartbag-alternating-cleanup.service \
      /etc/systemd/system/smartbag-alternating-cleanup.timer \
      /etc/systemd/system/smartbag.target
rm -f /etc/systemd/journald.conf.d/smartbag.conf
systemctl daemon-reload
systemctl try-restart systemd-journald.service || true
rm -rf /root/smartbag
echo "Runtime removed. /etc/smartbag and /var/lib/smartbag were retained."
