#!/bin/sh
set -eu
systemctl stop smartbag-alternating-vision.service
for device in /dev/video0 /dev/video2; do
    [ -e "$device" ] && fuser "$device" 2>/dev/null || true
done
