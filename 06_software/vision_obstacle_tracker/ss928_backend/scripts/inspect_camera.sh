#!/bin/sh
set -eu

echo "Read-only stage-J camera inventory; do not select a node by number alone."
for node in /dev/video*; do
  [ -e "$node" ] || continue
  echo "=== $node ==="
  udevadm info --query=property --name="$node" 2>/dev/null | \
    grep -E '^(ID_VENDOR_ID|ID_MODEL_ID|ID_SERIAL|ID_PATH|ID_V4L_PRODUCT)=' || true
  if command -v v4l2-ctl >/dev/null 2>&1; then
    v4l2-ctl --device="$node" --all 2>&1 || true
    v4l2-ctl --device="$node" --list-formats-ext 2>&1 || true
  fi
done
