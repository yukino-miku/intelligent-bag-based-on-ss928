#!/bin/sh
set -eu

CONFIG=${1:-/etc/smartbag/config.json}
/usr/bin/python3 - "$CONFIG" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    config = json.load(handle)
mode = config.get("vision_runtime", {}).get("mode", "fixed_dual_process")
enabled = bool(config.get("alternating_camera", {}).get("enabled", False))
if mode != "alternating_single_model" or not enabled:
    raise SystemExit(
        "refusing to start: set vision_runtime.mode=alternating_single_model "
        "and alternating_camera.enabled=true"
    )
PY
systemctl start smartbag-alternating-vision.service
systemctl --no-pager --full status smartbag-alternating-vision.service
