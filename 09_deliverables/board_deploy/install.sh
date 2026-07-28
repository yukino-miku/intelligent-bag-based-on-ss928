#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=${1:-$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)}
DEST=/root/smartbag

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ -f "$REPO_ROOT/06_software/vision_obstacle_tracker/vision_obstacle_tracker.py" ] || {
    echo "invalid repository root: $REPO_ROOT" >&2
    exit 1
}

install -d "$DEST/vision" "$DEST/controller" "$DEST/gnss" "$DEST/imu" "$DEST/audio" "$DEST/models"
install -d "$DEST/cloud_uploader" "$DEST/connectivity" "$DEST/mr20_radar" "$DEST/radar_vision_fusion" "$DEST/temperature"
install -d /etc/smartbag /run/smartbag /var/lib/smartbag/tracks /var/lib/smartbag/calibration /var/log/smartbag

cp -a "$REPO_ROOT/06_software/vision_obstacle_tracker/." "$DEST/vision/"
cp -a "$REPO_ROOT/06_software/board_runtime/smartbag_alert_controller/." "$DEST/controller/"
cp -a "$REPO_ROOT/06_software/board_runtime/common" "$DEST/"
cp -a "$REPO_ROOT/06_software/board_runtime/dx_gp21_tracker/." "$DEST/gnss/"
cp -a "$REPO_ROOT/06_software/board_runtime/bmi270_backpack/." "$DEST/imu/"
cp -a "$REPO_ROOT/06_software/board_runtime/imu_fall_detector" "$DEST/"
cp -a "$REPO_ROOT/06_software/board_runtime/cloud_uploader/." "$DEST/cloud_uploader/"
cp -a "$REPO_ROOT/06_software/board_runtime/mt5710_connectivity/." "$DEST/connectivity/"
cp -a "$REPO_ROOT/06_software/board_runtime/mr20_radar/." "$DEST/mr20_radar/"
cp -a "$REPO_ROOT/06_software/board_runtime/radar_vision_fusion/." "$DEST/radar_vision_fusion/"
cp -a "$REPO_ROOT/06_software/board_runtime/temperature/." "$DEST/temperature/"
cp -a "$SCRIPT_DIR/assets/audio/." "$DEST/audio/"
install -m 0755 "$REPO_ROOT/05_firmware/ss928/pinmux/apply-smartbag-pinmux.sh" "$DEST/apply-smartbag-pinmux.sh"
install -m 0755 "$REPO_ROOT/05_firmware/ss928/deployment_scripts/ws73-bluetooth-module-start.sh" "$DEST/ws73-bluetooth-module-start.sh"
install -m 0755 "$SCRIPT_DIR/safe-off.sh" "$DEST/safe-off.sh"
install -m 0755 "$SCRIPT_DIR/safe_off.py" "$DEST/safe_off.py"

find "$DEST" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$DEST" -type f \( -name '*.pyc' -o -name 'risk_log*.csv' \) -delete
find "$DEST/vision" -type d \( -name build -o -name dist -o -name dist_onefile -o -name third_party -o -name '*_openvino_model' -o -name .venv \) -prune -exec rm -rf {} +
find "$DEST/vision" -type f \( -name 'yolo*.pt' -o -name 'yolo*.onnx' -o -name '*.om' \) -delete

if [ ! -f /etc/smartbag/config.json ]; then
    cp "$SCRIPT_DIR/config.example.json" /etc/smartbag/config.json
    if [ -n "${SMARTBAG_HARDWARE_PROFILE:-}" ]; then
        python3 "$SCRIPT_DIR/apply_hardware_profile.py" /etc/smartbag/config.json "$SMARTBAG_HARDWARE_PROFILE"
    fi
fi
python3 "$SCRIPT_DIR/migrate_config.py" /etc/smartbag/config.json "$SCRIPT_DIR/config.example.json"
[ -f /etc/smartbag/calibration-left.json ] || cp "$SCRIPT_DIR/calibration-left.example.json" /etc/smartbag/calibration-left.json
[ -f /etc/smartbag/calibration-right.json ] || cp "$SCRIPT_DIR/calibration-right.example.json" /etc/smartbag/calibration-right.json
[ -f /etc/smartbag/fusion-left.json ] || cp "$SCRIPT_DIR/fusion-left.example.json" /etc/smartbag/fusion-left.json
[ -f /etc/smartbag/fusion-right.json ] || cp "$SCRIPT_DIR/fusion-right.example.json" /etc/smartbag/fusion-right.json
[ -f /etc/smartbag/bmi270.json ] || cp "$REPO_ROOT/06_software/board_runtime/bmi270_backpack/config.example.json" /etc/smartbag/bmi270.json
[ -f /etc/smartbag/mr20.json ] || cp "$REPO_ROOT/06_software/board_runtime/mr20_radar/config.example.json" /etc/smartbag/mr20.json
if [ ! -f /etc/smartbag/smartbag.env ]; then
    install -m 0600 "$SCRIPT_DIR/smartbag.env.example" /etc/smartbag/smartbag.env
fi
cp "$SCRIPT_DIR/systemd/"*.service "$SCRIPT_DIR/systemd/smartbag.target" /etc/systemd/system/
systemctl daemon-reload
# Remove an enable link left by older dual-detector deployments. The gateway is
# still available for manual regression, but fusion owns both cameras formally.
systemctl disable smartbag-video.service 2>/dev/null || true
systemctl enable smartbag.target

echo "Installed under $DEST. Place the accepted OM model at $DEST/models/vehicle-classifier.om before starting."
echo "Review /etc/smartbag/config.json, /etc/smartbag/smartbag.env and all visual/fusion calibration files before starting."
echo "Then run: $SCRIPT_DIR/check-runtime-deps.sh && $SCRIPT_DIR/preflight.sh && systemctl start smartbag.target"
