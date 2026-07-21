#!/bin/sh
set -eu

usage() {
    echo "Usage: $0 INPUT.onnx IMAGE_REF_LIST.txt [OUTPUT_PREFIX]" >&2
    exit 2
}

[ "$#" -ge 2 ] && [ "$#" -le 3 ] || usage

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
MODEL=$(realpath "$1")
IMAGE_LIST=$(realpath "$2")
OUTPUT_PREFIX=${3:-"$(dirname "$MODEL")/yolo11n_ss928"}
OUTPUT_PREFIX=$(realpath -m "$OUTPUT_PREFIX")
OUTPUT_DIR=$(dirname "$OUTPUT_PREFIX")
CONFIG="$SCRIPT_DIR/insert_op_rgb_planar.cfg"

[ "$(uname -s)" = "Linux" ] || {
    echo "ATC conversion must run on Linux x86_64." >&2
    exit 1
}
[ "$(uname -m)" = "x86_64" ] || {
    echo "The official SVP NNN PC toolkit requires Linux x86_64." >&2
    exit 1
}
[ -f "$MODEL" ] || { echo "ONNX model not found: $MODEL" >&2; exit 1; }
[ -f "$IMAGE_LIST" ] || { echo "calibration image list not found: $IMAGE_LIST" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 1; }
command -v atc >/dev/null 2>&1 || {
    echo "atc was not found; source the CANN SVP toolkit setenv.sh first." >&2
    exit 1
}

python3 "$SCRIPT_DIR/inspect_onnx_contract.py" "$MODEL"
mkdir -p "$OUTPUT_DIR"

ATC_LOG="${OUTPUT_PREFIX}.atc.log"
if ! atc \
    --framework=5 \
    --model="$MODEL" \
    --input_shape="images:1,3,640,640" \
    --insert_op_conf="$CONFIG" \
    --output="$OUTPUT_PREFIX" \
    --image_list="$IMAGE_LIST" \
    --soc_version=SS928V100 \
    --compile_mode=6 \
    >"$ATC_LOG" 2>&1; then
    cat "$ATC_LOG" >&2
    exit 1
fi
cat "$ATC_LOG"

OM_FILE="${OUTPUT_PREFIX}.om"
[ -s "$OM_FILE" ] || { echo "ATC did not create a non-empty OM file" >&2; exit 1; }
sha256sum "$OM_FILE" | tee "${OUTPUT_PREFIX}.sha256"
echo "SS928 OM created: $OM_FILE"
