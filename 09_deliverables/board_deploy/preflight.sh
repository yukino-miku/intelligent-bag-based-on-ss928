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
FUSION_DEBUG_BIND="127.0.0.1"
CONFIG_API_TOKEN=""
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
    FUSION_DEBUG_BIND=$(config_value fusion.debug_bind)
    CONFIG_API_TOKEN=$(config_value fusion.debug_access_token)
elif [ "$RUNTIME_MODE" = "radar_only" ]; then
    FUSION_DEBUG_PORT=$(config_value fusion.debug_port)
    FUSION_DEBUG_ENABLED=$(config_value fusion.debug_http_enabled)
    FUSION_DEBUG_BIND=$(config_value fusion.debug_bind)
    CONFIG_API_TOKEN=$(config_value fusion.debug_access_token)
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
    RUNNER_MANIFEST=/root/smartbag/vision/ss928_backend/bin/runner-manifest.json
    check_path "$MODEL_MANIFEST"
    check_path "$RUNNER_MANIFEST"
    if [ -f "$MODEL" ] && [ -f "$MODEL_MANIFEST" ] && [ -f "$OM_RUNNER" ] && [ -f "$RUNNER_MANIFEST" ]; then
        if python3 "$SCRIPT_DIR/verify_release_assets.py" \
            --model "$MODEL" --model-manifest "$MODEL_MANIFEST" \
            --runner "$OM_RUNNER" --runner-manifest "$RUNNER_MANIFEST"
        then
            :
        else
            fail=1
        fi
        EXPECTED_RUNNER_VERSION=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["runner"]["contract_version"])' "$RUNNER_MANIFEST")
        ACTUAL_RUNNER_VERSION=$($OM_RUNNER --version 2>/dev/null || true)
        if [ "$ACTUAL_RUNNER_VERSION" = "$EXPECTED_RUNNER_VERSION" ]; then
            echo "OK   runner contract version $ACTUAL_RUNNER_VERSION"
        else
            echo "FAIL runner --version mismatch: expected $EXPECTED_RUNNER_VERSION got ${ACTUAL_RUNNER_VERSION:-unavailable}" >&2
            fail=1
        fi
    fi
    check_path "$LEFT_FUSION_CALIBRATION"
    check_path "$RIGHT_FUSION_CALIBRATION"
    if [ -f "$LEFT_FUSION_CALIBRATION" ]; then
        python3 /root/smartbag/radar_vision_fusion/validate_radar_camera_calibration.py \
            "$LEFT_FUSION_CALIBRATION" --require-measured \
            --hardware-discovery /etc/smartbag/hardware-discovery.json \
            --radar-config /etc/smartbag/mr20.json || fail=1
    fi
    if [ -f "$RIGHT_FUSION_CALIBRATION" ]; then
        python3 /root/smartbag/radar_vision_fusion/validate_radar_camera_calibration.py \
            "$RIGHT_FUSION_CALIBRATION" --require-measured \
            --hardware-discovery /etc/smartbag/hardware-discovery.json \
            --radar-config /etc/smartbag/mr20.json || fail=1
    fi
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
    if [ -f /etc/smartbag/mr20.json ]; then
        python3 "$SCRIPT_DIR/mr20-live-check.py" --config /etc/smartbag/mr20.json --duration 5 || fail=1
    fi
fi

if [ -r /sys/class/pwm/pwmchip0/npwm ] && { [ "$LIGHTS_ENABLED" = "True" ] || [ "$HAPTICS_BACKEND" = "pwm_legacy" ]; }; then
    npwm=$(cat /sys/class/pwm/pwmchip0/npwm)
    [ "$npwm" -ge 16 ] || { echo "MISS pwmchip0 needs at least 16 channels, got $npwm" >&2; fail=1; }
fi

PORTS=""
if { [ "$RUNTIME_MODE" = "radar_primary_visual_classification" ] || [ "$RUNTIME_MODE" = "radar_only" ]; } && [ "$FUSION_DEBUG_ENABLED" = "True" ]; then
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

if [ "$FUSION_DEBUG_ENABLED" = "True" ]; then
    ENV_FILE=$(dirname "$CONFIG")/smartbag.env
    ADMIN_TOKEN=""
    READONLY_TOKEN=""
    if [ -f "$ENV_FILE" ]; then
        ADMIN_TOKEN=$(sed -n 's/^SMARTBAG_API_TOKEN=//p' "$ENV_FILE" | tail -n 1)
        READONLY_TOKEN=$(sed -n 's/^SMARTBAG_API_READONLY_TOKEN=//p' "$ENV_FILE" | tail -n 1)
    fi
    [ -n "$ADMIN_TOKEN" ] || ADMIN_TOKEN=$CONFIG_API_TOKEN
    if [ ${#ADMIN_TOKEN} -lt 32 ]; then
        echo "FAIL fusion API admin token is missing or shorter than 32 characters" >&2
        fail=1
    else
        echo "OK   fusion API admin token configured"
    fi
    case "$FUSION_DEBUG_BIND" in
        127.0.0.1|::1|localhost) ;;
        *)
            if [ -z "$ADMIN_TOKEN" ] && [ -z "$READONLY_TOKEN" ]; then
                echo "FAIL non-loopback fusion API bind requires authentication" >&2
                fail=1
            fi
            ;;
    esac
fi

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
