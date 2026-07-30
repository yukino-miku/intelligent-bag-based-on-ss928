#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FUSION_DIR=${SMARTBAG_FUSION_SOURCE_DIR:-/root/smartbag/radar_vision_fusion}

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
