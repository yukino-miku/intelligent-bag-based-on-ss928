#!/bin/sh
set -eu

if [ "$#" -ne 6 ]; then
    echo "Usage: validate-board-model.sh MODEL IMAGE WIDTH HEIGHT PC_REFERENCE_JSON OUTPUT_DIR" >&2
    exit 2
fi
MODEL=$1
IMAGE=$2
WIDTH=$3
HEIGHT=$4
REFERENCE=$5
OUTPUT_DIR=$6
RUNNER=/root/smartbag/vision/ss928_backend/bin/ss928_detection_runner
INSPECTOR=/root/smartbag/vision/ss928_backend/bin/om_inspect
MANIFEST=/root/smartbag/models/vehicle-detector.manifest.json
COMPARE=/root/smartbag/vision/ss928_backend/diagnostics/compare_detection_json.py
mkdir -p "$OUTPUT_DIR"

python3 /root/smartbag/deploy/verify_release_assets.py \
    --model "$MODEL" --model-manifest "$MANIFEST" --allow-unvalidated-model
"$INSPECTOR" "$MODEL" --json "$OUTPUT_DIR/model-descriptor.json" \
    >"$OUTPUT_DIR/om-inspect.stdout.log" 2>"$OUTPUT_DIR/om-inspect.stderr.log"

python3 - "$IMAGE" "$WIDTH" "$HEIGHT" "$OUTPUT_DIR/frame.bgr" <<'PY'
import cv2, sys
image = cv2.imread(sys.argv[1])
if image is None:
    raise SystemExit("cannot decode validation image")
width, height = map(int, sys.argv[2:4])
image = cv2.resize(image, (width, height))
open(sys.argv[4], "wb").write(image.tobytes())
PY

"$RUNNER" --model "$MODEL" --input "$OUTPUT_DIR/frame.bgr" --input-format bgr24 \
    --source-width "$WIDTH" --source-height "$HEIGHT" --repeat 1 \
    >"$OUTPUT_DIR/om-detections.jsonl" 2>"$OUTPUT_DIR/runner.stderr.log"
python3 "$COMPARE" "$REFERENCE" "$OUTPUT_DIR/om-detections.jsonl" --require-match \
    >"$OUTPUT_DIR/parity-result.json"
echo "Board model validation artifacts written to $OUTPUT_DIR. A match is evidence for this image only, not full acceptance."
