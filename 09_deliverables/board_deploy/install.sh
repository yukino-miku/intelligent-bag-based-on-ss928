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

install -d "$DEST/vision" "$DEST/controller" "$DEST/gnss" "$DEST/imu" "$DEST/audio" "$DEST/models" "$DEST/board-deploy"
install -d /etc/smartbag /run/smartbag /var/lib/smartbag/tracks /var/lib/smartbag/calibration /var/log/smartbag
install -d /etc/systemd/journald.conf.d

cp -a "$REPO_ROOT/06_software/vision_obstacle_tracker/." "$DEST/vision/"
cp -a "$REPO_ROOT/06_software/board_runtime/smartbag_alert_controller/." "$DEST/controller/"
cp -a "$REPO_ROOT/06_software/board_runtime/common" "$DEST/"
cp -a "$REPO_ROOT/06_software/board_runtime/dx_gp21_tracker/." "$DEST/gnss/"
cp -a "$REPO_ROOT/06_software/board_runtime/bmi270_backpack/." "$DEST/imu/"
cp -a "$REPO_ROOT/06_software/board_runtime/imu_fall_detector" "$DEST/"
cp -a "$SCRIPT_DIR/assets/audio/." "$DEST/audio/"
install -m 0755 "$SCRIPT_DIR"/alternating-*.sh "$DEST/board-deploy/"
install -m 0755 "$SCRIPT_DIR"/cleanup-alternating-runs.sh "$DEST/board-deploy/"
install -m 0755 "$SCRIPT_DIR"/check-runtime-deps.sh "$SCRIPT_DIR"/install-board-*.sh "$DEST/board-deploy/"
install -m 0755 "$REPO_ROOT/05_firmware/ss928/pinmux/apply-smartbag-pinmux.sh" "$DEST/apply-smartbag-pinmux.sh"

find "$DEST" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$DEST" -type f \( -name '*.pyc' -o -name 'risk_log*.csv' \) -delete
find "$DEST/vision" -type d \( -name build -o -name dist -o -name dist_onefile -o -name third_party -o -name '*_openvino_model' -o -name .venv \) -prune -exec rm -rf {} +
find "$DEST/vision" -type f \( -name 'yolo*.pt' -o -name 'yolo*.onnx' -o -name '*.om' \) -delete

[ -f /etc/smartbag/config.json ] || cp "$SCRIPT_DIR/config.example.json" /etc/smartbag/config.json
[ -f /etc/smartbag/calibration-left.json ] || cp "$SCRIPT_DIR/calibration-left.example.json" /etc/smartbag/calibration-left.json
[ -f /etc/smartbag/calibration-right.json ] || cp "$SCRIPT_DIR/calibration-right.example.json" /etc/smartbag/calibration-right.json
cp "$SCRIPT_DIR/systemd/"*.service "$SCRIPT_DIR/systemd/"*.timer "$SCRIPT_DIR/systemd/smartbag.target" /etc/systemd/system/
install -m 0644 "$SCRIPT_DIR/journald-smartbag.conf" /etc/systemd/journald.conf.d/smartbag.conf
systemctl daemon-reload
systemctl try-restart systemd-journald.service || true
systemctl enable smartbag.target
systemctl enable smartbag-alternating-cleanup.timer

echo "Installed under $DEST. Place the model at $DEST/models/yolo11n.pt before starting."
echo "Review /etc/smartbag/config.json and both calibration files before starting."
echo "Then run: $SCRIPT_DIR/check-runtime-deps.sh && $SCRIPT_DIR/preflight.sh && systemctl start smartbag.target"
