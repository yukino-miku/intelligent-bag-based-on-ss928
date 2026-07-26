#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SDK_ARCHIVE=${SDK_ARCHIVE:?set SDK_ARCHIVE to SS928V100_SDK_V2.0.2.2.tar.gz}
SOURCE_DIR=${SOURCE_DIR:-$SCRIPT_DIR/Tsensor}
OUTPUT_DIR=${OUTPUT_DIR:-$SCRIPT_DIR/build}
SDK_ROOT_NAME=${SDK_ROOT_NAME:-SS928V100_SDK_V2.0.2.2}
TOOLCHAIN_BIN=${TOOLCHAIN_BIN:-/opt/linux/x86-arm/aarch64-mix210-linux/bin}

WORK_DIR=$(mktemp -d /tmp/tsensor-build.XXXXXX)
KERNEL_DIR=$WORK_DIR/$SDK_ROOT_NAME/open_source/linux/linux-4.19.y
MODULE_DIR=$WORK_DIR/Tsensor
LOG_FILE=$WORK_DIR/build.log

cleanup() {
  printf 'Build workspace retained for inspection: %s\n' "$WORK_DIR"
}
trap cleanup EXIT

test -r "$SDK_ARCHIVE"
test -d "$SOURCE_DIR"
test -x "$TOOLCHAIN_BIN/aarch64-mix210-linux-gcc"

tar -xf "$SDK_ARCHIVE" -C "$WORK_DIR" "$SDK_ROOT_NAME/open_source/linux/linux-4.19.y"
cp -a "$SOURCE_DIR" "$MODULE_DIR"
export PATH="$TOOLCHAIN_BIN:$PATH"

make -C "$KERNEL_DIR" ARCH=arm64 CROSS_COMPILE=aarch64-mix210-linux- ss928v100_emmc_defconfig >"$LOG_FILE" 2>&1
make -C "$KERNEL_DIR" ARCH=arm64 CROSS_COMPILE=aarch64-mix210-linux- modules_prepare >>"$LOG_FILE" 2>&1
env PWD="$MODULE_DIR" make -C "$KERNEL_DIR" M="$MODULE_DIR" ARCH=arm64 CROSS_COMPILE=aarch64-mix210-linux- modules >>"$LOG_FILE" 2>&1

mkdir -p "$OUTPUT_DIR"
cp "$MODULE_DIR/hi_tsensor.ko" "$OUTPUT_DIR/hi_tsensor.ko"
file "$OUTPUT_DIR/hi_tsensor.ko"
sha256sum "$OUTPUT_DIR/hi_tsensor.ko"
modinfo "$OUTPUT_DIR/hi_tsensor.ko" | grep -E '^(filename|vermagic|name|depends):' || true
tail -30 "$LOG_FILE"
