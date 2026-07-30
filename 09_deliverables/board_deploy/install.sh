#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=${1:-$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)}
ROOT_PREFIX=${SMARTBAG_ROOT_PREFIX:-}
DEST="$ROOT_PREFIX/root/smartbag"
ETC="$ROOT_PREFIX/etc/smartbag"
STATE="$ROOT_PREFIX/var/lib/smartbag"
LOG="$ROOT_PREFIX/var/log/smartbag"
SYSTEMD_DIR="$ROOT_PREFIX/etc/systemd/system"
RUNTIME_MODE=${SMARTBAG_RUNTIME_MODE:-radar_primary_visual_classification}

if [ -z "$ROOT_PREFIX" ]; then
    [ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
fi
[ -f "$REPO_ROOT/06_software/vision_obstacle_tracker/vision_obstacle_tracker.py" ] || {
    echo "invalid repository root: $REPO_ROOT" >&2
    exit 1
}

install -d "$DEST/vision" "$DEST/controller" "$DEST/gnss" "$DEST/imu" "$DEST/audio" "$DEST/models" "$DEST/deploy"
install -d "$DEST/cloud_uploader" "$DEST/connectivity" "$DEST/mr20_radar" "$DEST/radar_vision_fusion" "$DEST/temperature"
install -d "$ETC" "$ROOT_PREFIX/run/smartbag" "$STATE/tracks" "$STATE/calibration"
install -d "$STATE/alarm-events/images" "$LOG" "$LOG/fusion" "$SYSTEMD_DIR"

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
cp -a "$SCRIPT_DIR/." "$DEST/deploy/"
cp -a "$SCRIPT_DIR/assets/audio/." "$DEST/audio/"
install -m 0755 "$REPO_ROOT/05_firmware/ss928/pinmux/apply-smartbag-pinmux.sh" "$DEST/apply-smartbag-pinmux.sh"
install -m 0755 "$REPO_ROOT/05_firmware/ss928/deployment_scripts/ws73-bluetooth-module-start.sh" "$DEST/ws73-bluetooth-module-start.sh"
install -m 0755 "$SCRIPT_DIR/safe-off.sh" "$DEST/safe-off.sh"
install -m 0755 "$SCRIPT_DIR/safe_off.py" "$DEST/safe_off.py"

find "$DEST" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$DEST" -type f \( -name '*.pyc' -o -name 'risk_log*.csv' \) -delete
find "$DEST/vision" -type d \( -name build -o -name dist -o -name dist_onefile -o -name third_party -o -name '*_openvino_model' -o -name .venv \) -prune -exec rm -rf {} +
find "$DEST/vision" -type f \( -name 'yolo*.pt' -o -name 'yolo*.onnx' -o -name '*.om' \) -delete

RUNNER_SOURCE=${SMARTBAG_RUNNER_SOURCE:-$SCRIPT_DIR/bin/aarch64/ss928_detection_runner}
RUNNER_MANIFEST="$SCRIPT_DIR/bin/aarch64/runner-manifest.json"
python3 "$SCRIPT_DIR/verify_release_assets.py" \
    --runner "$RUNNER_SOURCE" --runner-manifest "$RUNNER_MANIFEST"
install -d "$DEST/vision/ss928_backend/bin"
install -m 0755 "$RUNNER_SOURCE" "$DEST/vision/ss928_backend/bin/ss928_detection_runner"
install -m 0755 "$SCRIPT_DIR/bin/aarch64/om_inspect" "$DEST/vision/ss928_backend/bin/om_inspect"
install -m 0644 "$RUNNER_MANIFEST" "$DEST/vision/ss928_backend/bin/runner-manifest.json"

MODEL_DEST="$DEST/models/vehicle-detector.om"
MODEL_SOURCE=${SMARTBAG_MODEL_SOURCE:-$SCRIPT_DIR/models/vehicle-detector.om}
if [ -n "$MODEL_SOURCE" ]; then
    [ -f "$MODEL_SOURCE" ] || { echo "model source does not exist: $MODEL_SOURCE" >&2; exit 1; }
    python3 "$SCRIPT_DIR/verify_release_assets.py" \
        --runner "$RUNNER_SOURCE" --runner-manifest "$RUNNER_MANIFEST" \
        --model "$MODEL_SOURCE" --model-manifest "$SCRIPT_DIR/models/vehicle-detector.manifest.json"
    install -m 0644 "$MODEL_SOURCE" "$MODEL_DEST"
    install -m 0644 "$SCRIPT_DIR/models/vehicle-detector.manifest.json" "$DEST/models/vehicle-detector.manifest.json"
    echo "Installed explicit model source $MODEL_SOURCE -> $MODEL_DEST"
elif [ -f "$MODEL_DEST" ]; then
    echo "Keeping existing model: $MODEL_DEST"
else
    echo "WARN no vehicle model installed; full visual classification preflight will fail" >&2
fi

if [ ! -f "$ETC/config.json" ]; then
    cp "$SCRIPT_DIR/config.example.json" "$ETC/config.json"
    if [ -n "${SMARTBAG_HARDWARE_PROFILE:-}" ]; then
        python3 "$SCRIPT_DIR/apply_hardware_profile.py" "$ETC/config.json" "$SMARTBAG_HARDWARE_PROFILE"
    fi
fi
python3 "$SCRIPT_DIR/migrate_config.py" "$ETC/config.json" "$SCRIPT_DIR/config.example.json"
python3 - "$ETC/config.json" "$RUNTIME_MODE" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
data["runtime_mode"] = sys.argv[2]
if sys.argv[2] == "radar_only":
    data.setdefault("snapshot_classifier", {})["enabled"] = False
temporary = path.with_suffix(path.suffix + ".tmp")
temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(temporary, path)
PY

[ -f "$ETC/calibration-left.json" ] || cp "$SCRIPT_DIR/calibration-left.example.json" "$ETC/calibration-left.json"
[ -f "$ETC/calibration-right.json" ] || cp "$SCRIPT_DIR/calibration-right.example.json" "$ETC/calibration-right.json"
[ -f "$ETC/fusion-left.json" ] || cp "$SCRIPT_DIR/fusion-left.example.json" "$ETC/fusion-left.json"
[ -f "$ETC/fusion-right.json" ] || cp "$SCRIPT_DIR/fusion-right.example.json" "$ETC/fusion-right.json"
[ -f "$ETC/bmi270.json" ] || cp "$REPO_ROOT/06_software/board_runtime/bmi270_backpack/config.example.json" "$ETC/bmi270.json"
[ -f "$ETC/mr20.json" ] || cp "$REPO_ROOT/06_software/board_runtime/mr20_radar/config.example.json" "$ETC/mr20.json"
if [ ! -f "$ETC/smartbag.env" ]; then
    install -m 0600 "$SCRIPT_DIR/smartbag.env.example" "$ETC/smartbag.env"
fi
python3 - "$ETC/smartbag.env" <<'PY'
import os
import secrets
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
required = ("SMARTBAG_API_TOKEN", "SMARTBAG_API_READONLY_TOKEN")
values = {}
for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
for key in required:
    if not values.get(key):
        replacement = secrets.token_urlsafe(32)
        prefix = key + "="
        for index, line in enumerate(lines):
            if line.startswith(prefix):
                lines[index] = prefix + replacement
                break
        else:
            lines.append(prefix + replacement)
temporary = path.with_suffix(path.suffix + ".tmp")
temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
os.chmod(temporary, 0o600)
os.replace(temporary, path)
os.chmod(path, 0o600)
PY
cp "$SCRIPT_DIR/systemd/"*.service "$SCRIPT_DIR/systemd/smartbag.target" "$SYSTEMD_DIR/"

if [ -z "$ROOT_PREFIX" ] && [ "${SMARTBAG_SKIP_SYSTEMD:-0}" != "1" ]; then
    systemctl daemon-reload
    systemctl disable smartbag-video.service 2>/dev/null || true
    systemctl enable smartbag.target
fi

echo "Installed under $DEST. Runtime mode: $RUNTIME_MODE."
echo "Configuration and user data under $ETC and $STATE were preserved."
