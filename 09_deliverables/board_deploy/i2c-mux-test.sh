#!/bin/sh
set -eu

BUS=${BUS:-0}
MUX=${MUX:-0x70}
LOCK=${LOCK:-/run/lock/smartbag-i2c0-mux.lock}
command -v i2cset >/dev/null 2>&1 || { echo "i2cset missing" >&2; exit 1; }
command -v i2cdetect >/dev/null 2>&1 || { echo "i2cdetect missing" >&2; exit 1; }
command -v flock >/dev/null 2>&1 || { echo "flock missing" >&2; exit 1; }
install -d "$(dirname "$LOCK")"
touch "$LOCK"

probe_channel() {
    channel=$1
    expected=$2
    mask=$((1 << channel))
    flock "$LOCK" sh -c "i2cset -y '$BUS' '$MUX' '$mask'; i2cdetect -y '$BUS'" | tee "/tmp/smartbag-i2c-ch${channel}.txt"
    grep -qi "$(printf '%02x' "$expected")" "/tmp/smartbag-i2c-ch${channel}.txt" || {
        echo "expected address 0x$(printf '%02x' "$expected") missing on CH$channel" >&2
        return 1
    }
}

probe_channel 0 104
probe_channel 1 45
probe_channel 2 45
echo "I2C mux probe passed: CH0=0x68 CH1=0x2d CH2=0x2d"
