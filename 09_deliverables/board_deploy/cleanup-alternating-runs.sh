#!/bin/sh
set -eu

ROOT=${1:-/var/log/smartbag/alternating-camera-runs}
MAX_COUNT=${MAX_SESSION_COUNT:-10}
MAX_SIZE_MB=${MAX_SESSION_SIZE_MB:-100}
[ -d "$ROOT" ] || exit 0

active_newest=""
if systemctl is-active --quiet smartbag-alternating-vision.service; then
    active_newest=$(find "$ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)
fi

find "$ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | awk -v keep="$MAX_COUNT" 'NR>keep {sub(/^[^ ]+ /, ""); print}' |
while IFS= read -r directory; do
    [ -n "$directory" ] || continue
    [ "$directory" = "$active_newest" ] && continue
    rm -rf -- "$directory"
done

find "$ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -n |
while IFS= read -r entry; do
    directory=${entry#* }
    [ "$directory" = "$active_newest" ] && continue
    used_mb=$(du -sm "$ROOT" | awk '{print $1}')
    [ "$used_mb" -le "$MAX_SIZE_MB" ] && break
    rm -rf -- "$directory"
done
