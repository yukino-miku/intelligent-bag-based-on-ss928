#!/bin/sh
set -eu

SDK_ROOT=${1:?usage: build.sh SDK_ROOT TOOLCHAIN_FILE [BUILD_DIR]}
TOOLCHAIN_FILE=${2:?usage: build.sh SDK_ROOT TOOLCHAIN_FILE [BUILD_DIR]}
BUILD_DIR=${3:-build}
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INCLUDE_DIR="$SDK_ROOT/include/hisilicon/npu"
ACL_LIBRARY="$SDK_ROOT/lib/linux/hisilicon/npu/libascendcl.so"

[ -f "$INCLUDE_DIR/acl.h" ] || { echo "missing $INCLUDE_DIR/acl.h" >&2; exit 1; }
[ -f "$ACL_LIBRARY" ] || { echo "missing $ACL_LIBRARY" >&2; exit 1; }

cmake -S "$SOURCE_DIR" -B "$BUILD_DIR" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE" \
    -DSS928_NPU_INCLUDE_DIR="$INCLUDE_DIR" \
    -DSS928_NPU_LIBRARY="$ACL_LIBRARY"
cmake --build "$BUILD_DIR" --config Release
