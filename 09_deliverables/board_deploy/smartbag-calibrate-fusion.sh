#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FUSION_DIR=${SMARTBAG_FUSION_SOURCE_DIR:-/root/smartbag/radar_vision_fusion}

if [ "${1:-}" = "--interactive" ]; then
    DISCOVERY=/etc/smartbag/hardware-discovery.json
    [ -f "$DISCOVERY" ] || { echo "camera hardware discovery is required first" >&2; exit 1; }
    mkdir -p /var/lib/smartbag/calibration
    for SIDE in left right; do
        echo "=== $SIDE radar-camera horizontal calibration ==="
        printf 'Image width [640]: '; read IMAGE_WIDTH; IMAGE_WIDTH=${IMAGE_WIDTH:-640}
        printf 'Image height [480]: '; read IMAGE_HEIGHT; IMAGE_HEIGHT=${IMAGE_HEIGHT:-480}
        printf 'Camera height m [1.20]: '; read CAMERA_HEIGHT; CAMERA_HEIGHT=${CAMERA_HEIGHT:-1.20}
        printf 'Radar height m [1.00]: '; read RADAR_HEIGHT; RADAR_HEIGHT=${RADAR_HEIGHT:-1.00}
        DEFAULT_X=$([ "$SIDE" = left ] && echo -0.18 || echo 0.18)
        printf 'Camera lateral x m [%s]: ' "$DEFAULT_X"; read CAMERA_X; CAMERA_X=${CAMERA_X:-$DEFAULT_X}
        printf 'Radar lateral x m [%s]: ' "$DEFAULT_X"; read RADAR_X; RADAR_X=${RADAR_X:-$DEFAULT_X}
        printf 'Camera pitch deg [0]: '; read CAMERA_PITCH; CAMERA_PITCH=${CAMERA_PITCH:-0}
        OBSERVATIONS=/var/lib/smartbag/calibration/fusion-$SIDE.jsonl
        : >"$OBSERVATIONS"
        SAMPLE=1
        while [ "$SAMPLE" -le 4 ]; do
            echo "Place one vehicle/reflector at a known position, inspect the $SIDE snapshot, then enter sample $SAMPLE/4."
            printf 'Radar/target x m: '; read RADAR_SAMPLE_X
            printf 'Radar/target z m: '; read RADAR_SAMPLE_Z
            printf 'Target pixel u: '; read PIXEL_U
            printf 'Target pixel v: '; read PIXEL_V
            python3 "$FUSION_DIR/capture_fusion_calibration.py" \
                --side "$SIDE" --output "$OBSERVATIONS" \
                --radar-x "$RADAR_SAMPLE_X" --radar-z "$RADAR_SAMPLE_Z" \
                --pixel-u "$PIXEL_U" --pixel-v "$PIXEL_V" \
                --image-width "$IMAGE_WIDTH" --image-height "$IMAGE_HEIGHT"
            SAMPLE=$((SAMPLE + 1))
        done
        "$0" "$SIDE" "$OBSERVATIONS" "/etc/smartbag/fusion-$SIDE.json" \
            "$IMAGE_WIDTH" "$IMAGE_HEIGHT" "$CAMERA_HEIGHT" "$RADAR_HEIGHT" \
            "$CAMERA_X" "$RADAR_X" "$CAMERA_PITCH"
        python3 - "/etc/smartbag/fusion-$SIDE.json" "$DISCOVERY" "$SIDE" /etc/smartbag/mr20.json <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
discovery = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
side = sys.argv[3]
data = json.loads(path.read_text(encoding="utf-8"))
camera = discovery[side]
radar_config = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
radars = [item for item in radar_config.get("radars", []) if item.get("side") == side and item.get("enabled", True)]
if len(radars) != 1:
    raise SystemExit(f"expected exactly one enabled {side} radar, found {len(radars)}")
data["hardware_id"] = camera["id_path"]
data["camera_by_path"] = camera["by_path"]
data["radar_name"] = radars[0]["name"]
data["calibration_time"] = datetime.now(timezone.utc).isoformat()
data["sample_count"] = data.get("fit_evidence", {}).get("observation_count", 0)
temporary = path.with_suffix(".json.tmp")
temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(temporary, path)
PY
        python3 "$FUSION_DIR/validate_radar_camera_calibration.py" \
            "/etc/smartbag/fusion-$SIDE.json" --require-measured \
            --hardware-discovery "$DISCOVERY" --radar-config /etc/smartbag/mr20.json
    done
    echo "Both side calibrations passed numeric and hardware-identity validation."
    exit 0
fi

if [ "$#" -lt 10 ]; then
    cat >&2 <<'EOF'
Usage: smartbag-calibrate-fusion.sh SIDE OBSERVATIONS.jsonl OUTPUT.json \
  IMAGE_WIDTH IMAGE_HEIGHT CAMERA_HEIGHT RADAR_HEIGHT CAMERA_X RADAR_X CAMERA_PITCH

Collect at least four known-position samples first with:
  python3 /root/smartbag/radar_vision_fusion/capture_fusion_calibration.py \
    --side left --output /var/lib/smartbag/calibration/fusion-left.jsonl \
    --radar-x X --radar-z Z --pixel-u U --pixel-v V --image-width W --image-height H
EOF
    exit 2
fi

SIDE=$1
OBSERVATIONS=$2
OUTPUT=$3
IMAGE_WIDTH=$4
IMAGE_HEIGHT=$5
CAMERA_HEIGHT=$6
RADAR_HEIGHT=$7
CAMERA_X=$8
RADAR_X=$9
CAMERA_PITCH=${10}
BASE="$SCRIPT_DIR/fusion-$SIDE.example.json"

python3 "$FUSION_DIR/fit_fusion_calibration.py" \
    --side "$SIDE" --base "$BASE" --observations "$OBSERVATIONS" --output "$OUTPUT" \
    --image-width "$IMAGE_WIDTH" --image-height "$IMAGE_HEIGHT" \
    --camera-height "$CAMERA_HEIGHT" --radar-height "$RADAR_HEIGHT" \
    --camera-x "$CAMERA_X" --radar-x "$RADAR_X" --camera-pitch "$CAMERA_PITCH"
python3 "$FUSION_DIR/validate_radar_camera_calibration.py" "$OUTPUT" --require-measured
echo "Horizontal calibration written to $OUTPUT. Validate vertical projection and real association before full acceptance."
