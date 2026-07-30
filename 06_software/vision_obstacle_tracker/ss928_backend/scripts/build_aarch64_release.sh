#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BACKEND_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
VISION_DIR=$(CDPATH= cd -- "$BACKEND_DIR/.." && pwd)
SDK_ROOT=${SDK_ROOT:?set SDK_ROOT to an SS928 MPP sample tree containing include/hisilicon/npu/acl.h and the ACL stub library}
ZIG=${ZIG:-zig}
OUTPUT_DIR=${OUTPUT_DIR:-$BACKEND_DIR/bin}
ACL_STUB_DIR=${ACL_STUB_DIR:-$SDK_ROOT/lib/linux/hisilicon/npu/stub}

[ -f "$SDK_ROOT/include/hisilicon/npu/acl.h" ] || {
    echo "missing ACL header: $SDK_ROOT/include/hisilicon/npu/acl.h" >&2
    exit 1
}
[ -f "$ACL_STUB_DIR/libascendcl.so" ] || {
    echo "missing ACL link stub: $ACL_STUB_DIR/libascendcl.so" >&2
    exit 1
}
command -v "$ZIG" >/dev/null 2>&1 || { echo "Zig compiler not found: $ZIG" >&2; exit 1; }
mkdir -p "$OUTPUT_DIR"

COMMON_FLAGS="-target aarch64-linux-gnu -std=c++14 -O2 -Wall -Wextra -Werror -Wno-nullability-completeness -fPIE"
INCLUDES="-I$BACKEND_DIR/include -I$VISION_DIR/c_port/include -I$SDK_ROOT/include/hisilicon -I$SDK_ROOT/include/hisilicon/npu"
LIBS="-L$ACL_STUB_DIR -lascendcl -lpthread -lm -ldl -pie -Wl,-s"

# shellcheck disable=SC2086
"$ZIG" c++ $COMMON_FLAGS $INCLUDES \
    "$BACKEND_DIR/src/detection_runner.cpp" \
    "$BACKEND_DIR/src/model_tensor_info.cpp" \
    "$BACKEND_DIR/src/ss928_acl_detector.cpp" \
    "$BACKEND_DIR/src/frame_preprocess.cpp" \
    "$BACKEND_DIR/src/yolov8_postprocess.cpp" \
    "$VISION_DIR/c_port/src/vot_backend.cpp" \
    $LIBS -o "$OUTPUT_DIR/ss928_detection_runner"

# shellcheck disable=SC2086
"$ZIG" c++ $COMMON_FLAGS $INCLUDES \
    "$BACKEND_DIR/tools/om_inspect.cpp" \
    "$BACKEND_DIR/src/model_tensor_info.cpp" \
    $LIBS -o "$OUTPUT_DIR/om_inspect"

echo "Built AArch64 release binaries in $OUTPUT_DIR"
echo "Runtime dependency libascendcl.so must come from the matching SS928 board image."
