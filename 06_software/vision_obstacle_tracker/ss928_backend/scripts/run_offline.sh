#!/bin/sh
set -eu

PROJECT_DIR=${PROJECT_DIR:-/root/smartbag/vision/ss928_backend}
INPUT=${1:?usage: run_offline.sh FRAME.nv12 [repeat]}
REPEAT=${2:-1}
. "$PROJECT_DIR/config/detector.env"

export LD_LIBRARY_PATH="/opt/lib:/opt/lib/npu:${LD_LIBRARY_PATH:-}"
exec "$PROJECT_DIR/bin/ss928_detection_runner" \
  --model "$MODEL_PATH" \
  --input "$INPUT" \
  --source-width "$MODEL_WIDTH" \
  --source-height "$MODEL_HEIGHT" \
  --repeat "$REPEAT" \
  --conf "$CONFIDENCE" \
  --nms "$NMS" \
  --max-det "$MAX_DETECTIONS" \
  --target-classes "$TARGET_CLASSES"
