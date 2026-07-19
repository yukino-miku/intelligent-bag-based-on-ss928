#!/bin/sh
set -eu
systemctl --no-pager --full status smartbag-alternating-vision.service || true
printf '\nCamera users:\n'
for device in /dev/video0 /dev/video2; do
    [ -e "$device" ] && { printf '%s: ' "$device"; fuser "$device" 2>/dev/null || true; printf '\n'; }
done
