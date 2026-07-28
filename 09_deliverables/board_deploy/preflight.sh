#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CONFIG=${1:-/etc/smartbag/config.json}
fail=0

check_path() {
    if [ -e "$1" ]; then
        printf 'OK   %s\n' "$1"
    else
        printf 'MISS %s\n' "$1" >&2
        fail=1
    fi
}

config_value() {
    python3 - "$CONFIG" "$1" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
value = data
for part in sys.argv[2].split("."):
    value = value[part]
print(value)
PY
}

check_path "$CONFIG"
RUNTIME_MODE=$(config_value runtime_mode)
LEFT_DEVICE=""
RIGHT_DEVICE=""
LEFT_CALIBRATION=""
RIGHT_CALIBRATION=""
MODEL=""
OM_RUNNER=""
LEFT_FUSION_CALIBRATION=""
RIGHT_FUSION_CALIBRATION=""
VIDEO_PORT=""
FUSION_DEBUG_PORT=""
FUSION_DEBUG_ENABLED="False"
LEFT_STREAM_PORT=""
RIGHT_STREAM_PORT=""
if [ "$RUNTIME_MODE" = "radar_primary_visual_classification" ]; then
    LEFT_DEVICE=$(config_value snapshot_classifier.left_device)
    RIGHT_DEVICE=$(config_value snapshot_classifier.right_device)
    MODEL=$(config_value snapshot_classifier.model)
    OM_RUNNER=$(config_value snapshot_classifier.runner)
    LEFT_FUSION_CALIBRATION=$(config_value fusion.left_calibration)
    RIGHT_FUSION_CALIBRATION=$(config_value fusion.right_calibration)
    FUSION_DEBUG_PORT=$(config_value fusion.debug_port)
    FUSION_DEBUG_ENABLED=$(config_value fusion.debug_http_enabled)
elif [ "$RUNTIME_MODE" = "legacy_dual_vision" ]; then
    LEFT_DEVICE=$(config_value cameras.left.camera_device)
    RIGHT_DEVICE=$(config_value cameras.right.camera_device)
    LEFT_CALIBRATION=$(config_value cameras.left.calibration_file)
    RIGHT_CALIBRATION=$(config_value cameras.right.calibration_file)
    MODEL=$(config_value paths.model)
    VIDEO_PORT=$(config_value stream_gateway.port)
    LEFT_STREAM_PORT=$(config_value cameras.left.stream_port)
    RIGHT_STREAM_PORT=$(config_value cameras.right.stream_port)
fi
GNSS_ENABLED=$(config_value modules.gnss.enabled)
IMU_ENABLED=$(config_value modules.imu.enabled)
RADAR_ENABLED=$(config_value radar.enabled)
HAPTICS_BACKEND=$(config_value outputs.haptics_backend)
LIGHTS_ENABLED=$(config_value outputs.lights_enabled)

if [ -n "$LEFT_DEVICE" ] && [ -n "$RIGHT_DEVICE" ]; then
    LEFT_REAL=$(readlink -f "$LEFT_DEVICE" 2>/dev/null || printf '%s' "$LEFT_DEVICE")
    RIGHT_REAL=$(readlink -f "$RIGHT_DEVICE" 2>/dev/null || printf '%s' "$RIGHT_DEVICE")
    if [ "$LEFT_REAL" = "$RIGHT_REAL" ]; then
        echo "FAIL left and right camera devices are identical: $LEFT_DEVICE" >&2
        fail=1
    fi
fi
if [ "$RUNTIME_MODE" = "legacy_dual_vision" ] && [ "$LEFT_STREAM_PORT" = "$RIGHT_STREAM_PORT" ]; then
    echo "FAIL left and right detector stream ports are identical" >&2
    fail=1
fi

if [ "$RUNTIME_MODE" = "radar_primary_visual_classification" ]; then
    for path in "$LEFT_DEVICE" "$RIGHT_DEVICE" "$MODEL"; do
        check_path "$path"
    done
    check_path "$OM_RUNNER"
    MODEL_MANIFEST=/root/smartbag/models/vehicle-detector.manifest.json
    check_path "$MODEL_MANIFEST"
    if [ -f "$MODEL" ] && [ -f "$MODEL_MANIFEST" ]; then
        if python3 - "$MODEL" "$MODEL_MANIFEST" <<'PY'
import hashlib
import json
import sys

model_path, manifest_path = sys.argv[1:]
manifest = json.load(open(manifest_path, encoding="utf-8"))
expected = str(manifest.get("sha256", "")).lower()
actual = hashlib.sha256(open(model_path, "rb").read()).hexdigest()
if not expected or actual != expected:
    raise SystemExit(f"model SHA256 mismatch: expected={expected or 'missing'} actual={actual}")
if manifest.get("current_runner_compatible") is not True:
    raise SystemExit("model manifest blocks deployment: current SS928 runner input contract is incompatible")
print(f"OK   vehicle detector SHA256 {actual}")
PY
        then
            :
        else
            fail=1
        fi
    fi
    check_path "$LEFT_FUSION_CALIBRATION"
    check_path "$RIGHT_FUSION_CALIBRATION"
elif [ "$RUNTIME_MODE" = "legacy_dual_vision" ]; then
    for path in "$LEFT_DEVICE" "$RIGHT_DEVICE" "$LEFT_CALIBRATION" "$RIGHT_CALIBRATION" "$MODEL"; do
        check_path "$path"
    done
fi
if [ "$IMU_ENABLED" = "True" ] || [ "$HAPTICS_BACKEND" = "tm6605" ]; then
    check_path /dev/i2c-0
fi
if [ "$GNSS_ENABLED" = "True" ]; then
    check_path /dev/ttyAMA4
fi
if [ "$LIGHTS_ENABLED" = "True" ] || [ "$HAPTICS_BACKEND" = "pwm_legacy" ]; then
    check_path /sys/class/pwm/pwmchip0
fi
if [ "$RADAR_ENABLED" = "True" ]; then
    check_path /etc/smartbag/mr20.json
fi

if [ -r /sys/class/pwm/pwmchip0/npwm ] && { [ "$LIGHTS_ENABLED" = "True" ] || [ "$HAPTICS_BACKEND" = "pwm_legacy" ]; }; then
    npwm=$(cat /sys/class/pwm/pwmchip0/npwm)
    [ "$npwm" -ge 16 ] || { echo "MISS pwmchip0 needs at least 16 channels, got $npwm" >&2; fail=1; }
fi

PORTS=""
if [ "$RUNTIME_MODE" = "radar_primary_visual_classification" ] && [ "$FUSION_DEBUG_ENABLED" = "True" ]; then
    PORTS="$FUSION_DEBUG_PORT"
elif [ "$RUNTIME_MODE" = "legacy_dual_vision" ]; then
    PORTS="$VIDEO_PORT $LEFT_STREAM_PORT $RIGHT_STREAM_PORT"
fi
for port in $PORTS; do
    if python3 - "$port" <<'PY'
import socket
import sys

sock = socket.socket()
try:
    sock.bind(("127.0.0.1", int(sys.argv[1])))
finally:
    sock.close()
PY
    then
        echo "OK   port $port available"
    else
        echo "MISS port $port is occupied" >&2
        fail=1
    fi
done

if [ -z "$LEFT_DEVICE" ] && [ -z "$RIGHT_DEVICE" ]; then
    echo "OK   no camera is required by runtime mode $RUNTIME_MODE"
elif command -v v4l2-ctl >/dev/null 2>&1; then
    v4l2-ctl --device "$LEFT_DEVICE" --list-formats-ext || fail=1
    v4l2-ctl --device "$RIGHT_DEVICE" --list-formats-ext || fail=1
else
    echo "MISS v4l2-ctl" >&2
    fail=1
fi

if [ -n "$LEFT_DEVICE" ] && [ -n "$RIGHT_DEVICE" ]; then
    if "$SCRIPT_DIR/camera-test.sh" "$LEFT_DEVICE"; then
        echo "OK   left camera snapshot"
    else
        fail=1
    fi
    if "$SCRIPT_DIR/camera-test.sh" "$RIGHT_DEVICE"; then
        echo "OK   right camera snapshot"
    else
        fail=1
    fi
fi
"$SCRIPT_DIR/check-runtime-deps.sh" "$CONFIG" || fail=1

systemctl is-active --quiet bluetooth.service || { echo "MISS bluetooth.service is not active" >&2; fail=1; }

if [ "$HAPTICS_BACKEND" = "tm6605" ] && command -v i2cdetect >/dev/null 2>&1; then
    i2cdetect -y 0 0x70 0x70 | grep -q '70' || { echo "MISS TCA9548A at I2C0 address 0x70" >&2; fail=1; }
fi

if [ -r /proc/Tsensor ]; then
    echo "OK   /proc/Tsensor"
else
    echo "WARN /proc/Tsensor unavailable; temperature service will report unavailable" >&2
fi

[ "$fail" -eq 0 ] || exit 1
echo "Preflight passed. This does not prove OM accuracy, radar-camera association, long-run stability, temperature, or phone playback."
