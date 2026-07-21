#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=${1:-$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)}
MODEL_SOURCE=${2:-}
WHEELHOUSE=${3:-}
NPU_ADAPTER_SOURCE=${4:-}
DEST=/root/smartbag

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ -f "$REPO_ROOT/06_software/vision_obstacle_tracker/vision_obstacle_tracker.py" ] || {
    echo "invalid repository root: $REPO_ROOT" >&2
    exit 1
}
if grep -Il "$(printf '\r')" "$SCRIPT_DIR"/*.sh >/dev/null 2>&1; then
    echo "CRLF detected in deployment shell scripts; checkout must honor .gitattributes" >&2
    exit 1
fi

install -d "$DEST/vision" "$DEST/controller" "$DEST/gnss" "$DEST/imu" "$DEST/audio" "$DEST/models" "$DEST/board-deploy" "$DEST/mr20_radar" "$DEST/cloud-uploader"
install -d /etc/smartbag /run/smartbag /run/lock /var/lib/smartbag/tracks /var/lib/smartbag/calibration /var/log/smartbag
install -d /var/log/smartbag/boot-selftest /var/log/smartbag/rev2-validation
install -d /etc/systemd/journald.conf.d

if [ ! -x "$DEST/venv/bin/python" ]; then
    python3 -m venv --system-site-packages "$DEST/venv"
fi
[ -x "$DEST/venv/bin/python" ] || { echo "failed to create $DEST/venv" >&2; exit 1; }

cp -a "$REPO_ROOT/06_software/vision_obstacle_tracker/." "$DEST/vision/"
cp -a "$REPO_ROOT/06_software/board_runtime/smartbag_alert_controller/." "$DEST/controller/"
cp -a "$REPO_ROOT/06_software/board_runtime/common" "$DEST/"
cp -a "$REPO_ROOT/06_software/board_runtime/dx_gp21_tracker/." "$DEST/gnss/"
cp -a "$REPO_ROOT/06_software/board_runtime/bmi270_backpack/." "$DEST/imu/"
cp -a "$REPO_ROOT/06_software/board_runtime/imu_fall_detector" "$DEST/"
cp -a "$REPO_ROOT/06_software/board_runtime/mr20_radar/." "$DEST/mr20_radar/"
cp -a "$REPO_ROOT/06_software/board_runtime/cloud_uploader/." "$DEST/cloud-uploader/"
cp -a "$SCRIPT_DIR/assets/audio/." "$DEST/audio/"
install -m 0755 "$SCRIPT_DIR"/alternating-*.sh "$DEST/board-deploy/"
install -m 0755 "$SCRIPT_DIR"/cleanup-alternating-runs.sh "$DEST/board-deploy/"
install -m 0755 "$SCRIPT_DIR"/check-runtime-deps.sh "$SCRIPT_DIR"/install-board-*.sh "$DEST/board-deploy/"
install -m 0755 "$SCRIPT_DIR"/hardware-preflight.sh "$SCRIPT_DIR"/i2c-mux-test.sh "$SCRIPT_DIR"/tm6605-test.sh "$SCRIPT_DIR"/light-test.sh "$SCRIPT_DIR"/pwm-list.sh "$SCRIPT_DIR"/mr20-network-preflight.sh "$SCRIPT_DIR"/mr20-network-install.sh "$SCRIPT_DIR"/mr20-status.sh "$SCRIPT_DIR"/mr20-capture.sh "$SCRIPT_DIR"/full-hardware-test.sh "$SCRIPT_DIR"/smartbag-hardware-profile.sh "$DEST/board-deploy/"
install -m 0755 "$SCRIPT_DIR"/pwm-probe.py "$SCRIPT_DIR"/mr20-capture.py "$SCRIPT_DIR"/migrate-config.py "$DEST/board-deploy/"
install -m 0755 "$SCRIPT_DIR"/safe_off.py "$SCRIPT_DIR"/wait_for_hardware.py "$SCRIPT_DIR"/boot_selftest.py "$SCRIPT_DIR"/rev2-board-validation.py "$SCRIPT_DIR"/upgrade_rev2_runtime_config.py "$DEST/board-deploy/"
cp -a "$SCRIPT_DIR/hardware-profiles" "$SCRIPT_DIR/systemd-networkd" "$DEST/board-deploy/"
install -m 0755 "$REPO_ROOT/05_firmware/ss928/pinmux/apply-smartbag-pinmux.sh" "$DEST/apply-smartbag-pinmux.sh"

find "$DEST" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$DEST" -type f \( -name '*.pyc' -o -name 'risk_log*.csv' \) -delete
find "$DEST/vision" -type d \( -name build -o -name dist -o -name dist_onefile -o -name third_party -o -name '*_openvino_model' -o -name .venv \) -prune -exec rm -rf {} +
find "$DEST/vision" -type f \( -name 'yolo*.pt' -o -name 'yolo*.onnx' -o -name '*.om' \) -delete

MODEL_DEST=
if [ -n "$MODEL_SOURCE" ]; then
    [ -f "$MODEL_SOURCE" ] || { echo "model source not found: $MODEL_SOURCE" >&2; exit 1; }
    case "$MODEL_SOURCE" in
        *.om) MODEL_DEST="$DEST/models/yolov8n.om" ;;
        *) MODEL_DEST="$DEST/models/yolo11n.pt" ;;
    esac
    install -m 0644 "$MODEL_SOURCE" "$MODEL_DEST"
fi
[ -f "$DEST/models/yolo11n.pt" ] || [ -f "$DEST/models/yolov8n.om" ] || {
    echo "required model missing; pass it as install.sh REPO_ROOT MODEL_PATH [WHEELHOUSE] [NPU_ADAPTER]" >&2
    exit 1
}
if [ -n "$NPU_ADAPTER_SOURCE" ]; then
    [ -f "$NPU_ADAPTER_SOURCE" ] || {
        echo "SS928 NPU adapter not found: $NPU_ADAPTER_SOURCE" >&2
        exit 1
    }
    install -d "$DEST/vision/ss928_backend/lib"
    install -m 0755 "$NPU_ADAPTER_SOURCE" \
        "$DEST/vision/ss928_backend/lib/libsmartbag_ss928_acl.so"
fi
CONFIG_CREATED=0
if [ -f /etc/smartbag/config.json ]; then
    "$DEST/venv/bin/python" "$DEST/board-deploy/upgrade_rev2_runtime_config.py" /etc/smartbag/config.json
else
    cp "$SCRIPT_DIR/config.example.json" /etc/smartbag/config.json
    CONFIG_CREATED=1
fi
if [ "$CONFIG_CREATED" -eq 1 ]; then
    if [ -z "$MODEL_DEST" ]; then
        if [ -f "$DEST/models/yolov8n.om" ]; then
            MODEL_DEST="$DEST/models/yolov8n.om"
        else
            MODEL_DEST="$DEST/models/yolo11n.pt"
        fi
    fi
    "$DEST/venv/bin/python" - /etc/smartbag/config.json "$MODEL_DEST" <<'PY'
import json
import sys

path, model_path = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    config = json.load(handle)
config.setdefault("paths", {})["model"] = model_path
alternating = config.setdefault("alternating_camera", {})
alternating["detector_backend"] = "ss928_om" if model_path.endswith(".om") else "ultralytics"
alternating["imgsz"] = 640 if model_path.endswith(".om") else alternating.get("imgsz", 416)
with open(path, "w", encoding="utf-8") as handle:
    json.dump(config, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
PY
fi
SELECTED_MODEL=$("$DEST/venv/bin/python" - /etc/smartbag/config.json <<'PY'
import json, sys
try:
    print(json.load(open(sys.argv[1], encoding="utf-8")).get("paths", {}).get("model", ""))
except (OSError, ValueError):
    print("")
PY
)
[ -f "$SELECTED_MODEL" ] || {
    echo "configured model missing: $SELECTED_MODEL" >&2
    exit 1
}
if [ "${SELECTED_MODEL##*.}" = om ] && \
   [ ! -f "$DEST/vision/ss928_backend/lib/libsmartbag_ss928_acl.so" ]; then
    echo "SS928 .om selected but native adapter is missing; pass it as install.sh argument 4" >&2
    exit 1
fi
if [ -n "$WHEELHOUSE" ]; then
    if [ "${SELECTED_MODEL##*.}" = om ]; then
        RUNTIME_REQUIREMENTS="$DEST/vision/requirements-board-npu.txt"
    else
        RUNTIME_REQUIREMENTS="$DEST/vision/requirements-board-cpu.txt"
    fi
    "$SCRIPT_DIR/install-board-deps-offline.sh" "$WHEELHOUSE" "$RUNTIME_REQUIREMENTS"
fi
if [ -f /etc/smartbag/hardware.json ]; then
    cp /etc/smartbag/hardware.json "/etc/smartbag/hardware.json.bak.$(date -u +%Y%m%dT%H%M%SZ)"
fi
cp "$SCRIPT_DIR/hardware-profiles/rev2_tm6605_mr20.json" /etc/smartbag/hardware.json
[ -f /etc/smartbag/mr20-radar.json ] || cp "$REPO_ROOT/06_software/board_runtime/mr20_radar/config.example.json" /etc/smartbag/mr20-radar.json
[ -f /etc/smartbag/cloud-uploader.json ] || cp "$REPO_ROOT/06_software/board_runtime/cloud_uploader/config.example.json" /etc/smartbag/cloud-uploader.json
[ -f /etc/smartbag/calibration-left.json ] || cp "$SCRIPT_DIR/calibration-left.example.json" /etc/smartbag/calibration-left.json
[ -f /etc/smartbag/calibration-right.json ] || cp "$SCRIPT_DIR/calibration-right.example.json" /etc/smartbag/calibration-right.json
[ -f /etc/smartbag/smartbag.env ] || cp "$SCRIPT_DIR/smartbag.env.example" /etc/smartbag/smartbag.env
cp "$SCRIPT_DIR/systemd/"*.service "$SCRIPT_DIR/systemd/"*.timer "$SCRIPT_DIR/systemd/smartbag.target" /etc/systemd/system/
git -C "$REPO_ROOT" rev-parse HEAD >"$DEST/REVISION" 2>/dev/null || printf 'unknown\n' >"$DEST/REVISION"
install -m 0644 "$SCRIPT_DIR/journald-smartbag.conf" /etc/systemd/journald.conf.d/smartbag.conf
systemctl daemon-reload
systemctl try-restart systemd-journald.service || true
systemctl disable smartbag-alert.service smartbag-video.service smartbag-alternating-vision.service 2>/dev/null || true
systemctl enable smartbag.target
systemctl enable smartbag-alternating-cleanup.timer

echo "Installed under $DEST with model and fixed Python at $DEST/venv/bin/python."
echo "Review /etc/smartbag/config.json and both calibration files before first power-only start."
echo "Review /etc/smartbag/hardware.json and /etc/smartbag/mr20-radar.json; Cloud uploader remains disabled by default."
echo "Then run validation before enabling physical output: $DEST/board-deploy/rev2-board-validation.py --phase preflight"
