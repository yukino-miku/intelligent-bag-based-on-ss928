#!/bin/sh
set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY="$REPO_ROOT/09_deliverables/board_deploy"
PROFILE="$DEPLOY/profiles/euler-pi-ss928-smartbag.json"
MODEL_SOURCE="$DEPLOY/models/vehicle-detector.om"
RUNNER_SOURCE="$DEPLOY/bin/aarch64/ss928_detection_runner"
NO_START=0
RADAR_ONLY=0
SKIP_OPTIONAL=0
OFFLINE=0
ASSUME_YES=0
INTERACTIVE=0
FULL=0
RESET_HARDWARE_DISCOVERY=0
RESET_CALIBRATION=0
ROOT_PREFIX=${SMARTBAG_ROOT_PREFIX:-}

usage() {
    cat <<'EOF'
Usage: sudo ./install-on-ss928.sh [options]
  --profile PATH       hardware profile JSON
  --interactive        guide camera assignment and calibration; safely fall back to radar-only
  --full               require measured fusion calibration and enable visual classification
  --model-source PATH  alternate accepted vehicle-detector.om
  --runner-source PATH alternate AArch64 runner
  --no-start           install and enable, but do not start services
  --radar-only         disable visual classification while keeping the shared risk runtime
  --skip-optional      skip optional package installation
  --offline            do not use apt or network
  --yes                do not prompt for confirmation
  --reset-hardware-discovery  discard saved camera identities before assignment
  --reset-calibration  discard saved fusion calibration before setup
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --profile) PROFILE=$2; shift 2 ;;
        --interactive) INTERACTIVE=1; shift ;;
        --full) FULL=1; shift ;;
        --model-source) MODEL_SOURCE=$2; shift 2 ;;
        --runner-source) RUNNER_SOURCE=$2; shift 2 ;;
        --no-start) NO_START=1; shift ;;
        --radar-only) RADAR_ONLY=1; shift ;;
        --skip-optional) SKIP_OPTIONAL=1; shift ;;
        --offline) OFFLINE=1; shift ;;
        --yes) ASSUME_YES=1; shift ;;
        --reset-hardware-discovery) RESET_HARDWARE_DISCOVERY=1; shift ;;
        --reset-calibration) RESET_CALIBRATION=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

[ "$RADAR_ONLY" -eq 0 ] || [ "$FULL" -eq 0 ] || { echo "--radar-only and --full are mutually exclusive" >&2; exit 2; }
[ "$INTERACTIVE" -eq 0 ] || [ "$ASSUME_YES" -eq 0 ] || { echo "--interactive cannot be combined with --yes" >&2; exit 2; }

if [ -z "$ROOT_PREFIX" ]; then
    [ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
    case "$(uname -m)" in
        aarch64|arm64) ;;
        *) echo "unsupported architecture: $(uname -m); SS928 installer requires aarch64" >&2; exit 1 ;;
    esac
    BOARD_ID=$(cat /proc/device-tree/model /proc/device-tree/compatible 2>/dev/null | tr '\000' ' ' || true)
    printf '%s' "$BOARD_ID" | grep -Eiq 'ss928|hi3403|sd3403|hisi|euler' || {
        echo "unsupported board identity: ${BOARD_ID:-device-tree identity unavailable}" >&2
        exit 1
    }
    MEM_MIB=$(awk '/MemTotal:/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
    [ "$MEM_MIB" -ge 768 ] || { echo "at least 768 MiB memory is required; found $MEM_MIB MiB" >&2; exit 1; }
    FREE_MIB=$(df -Pm /root 2>/dev/null | awk 'NR==2 {print $4}' || echo 0)
    [ "$FREE_MIB" -ge 2048 ] || { echo "at least 2048 MiB free disk is required; found $FREE_MIB MiB" >&2; exit 1; }
fi
[ -f "$PROFILE" ] || { echo "hardware profile not found: $PROFILE" >&2; exit 1; }

cleanup_on_failure() {
    status=$?
    if [ "$status" -ne 0 ] && [ -z "$ROOT_PREFIX" ]; then
        "$DEPLOY/safe-off.sh" >/dev/null 2>&1 || true
        echo "Installation failed; safe-off was requested." >&2
    fi
    exit "$status"
}
trap cleanup_on_failure EXIT INT TERM

python3 "$DEPLOY/verify_release_assets.py" \
    --runner "$RUNNER_SOURCE" --runner-manifest "$DEPLOY/bin/aarch64/runner-manifest.json"

[ -f "$MODEL_SOURCE" ] || { echo "formal vehicle model not found: $MODEL_SOURCE" >&2; exit 1; }
python3 "$DEPLOY/verify_release_assets.py" \
    --runner "$RUNNER_SOURCE" --runner-manifest "$DEPLOY/bin/aarch64/runner-manifest.json" \
    --model "$MODEL_SOURCE" --model-manifest "$DEPLOY/models/vehicle-detector.manifest.json"

if [ "$ASSUME_YES" -eq 0 ] && [ -z "$ROOT_PREFIX" ]; then
    printf 'Install SmartBag runtime using profile %s? [y/N] ' "$PROFILE"
    read answer
    case "$answer" in y|Y|yes|YES) ;; *) echo "cancelled"; exit 1 ;; esac
fi

if [ "$OFFLINE" -eq 0 ] && [ "$SKIP_OPTIONAL" -eq 0 ] && [ -z "$ROOT_PREFIX" ]; then
    "$DEPLOY/install-deps.sh" --install-system
fi

export SMARTBAG_ROOT_PREFIX="$ROOT_PREFIX"
export SMARTBAG_HARDWARE_PROFILE="$PROFILE"
export SMARTBAG_RUNNER_SOURCE="$RUNNER_SOURCE"
export SMARTBAG_MODEL_SOURCE="$MODEL_SOURCE"
if [ "$RADAR_ONLY" -eq 1 ] || [ "$INTERACTIVE" -eq 1 ]; then
    export SMARTBAG_RUNTIME_MODE=radar_only
else
    export SMARTBAG_RUNTIME_MODE=radar_primary_visual_classification
fi
"$DEPLOY/install.sh" "$REPO_ROOT"

if [ -n "$ROOT_PREFIX" ]; then
    echo "Mock-root installation completed under $ROOT_PREFIX; hardware preflight and systemd were not executed."
    trap - EXIT INT TERM
    exit 0
fi

if [ "$RESET_HARDWARE_DISCOVERY" -eq 1 ]; then
    rm -f /etc/smartbag/hardware-discovery.json /etc/udev/rules.d/99-smartbag-cameras.rules
fi
if [ "$RESET_CALIBRATION" -eq 1 ]; then
    rm -f /etc/smartbag/fusion-left.json /etc/smartbag/fusion-right.json
    cp "$DEPLOY/fusion-left.example.json" /etc/smartbag/fusion-left.json
    cp "$DEPLOY/fusion-right.example.json" /etc/smartbag/fusion-right.json
fi

ACTIVE_FULL=0
if [ "$RADAR_ONLY" -eq 0 ]; then
    if [ "$ASSUME_YES" -eq 1 ]; then
        "$DEPLOY/camera-assign.sh" --reuse-existing --yes
    else
        "$DEPLOY/camera-assign.sh" --interactive
    fi
    if python3 /root/smartbag/radar_vision_fusion/validate_radar_camera_calibration.py \
        /etc/smartbag/fusion-left.json --require-measured \
        --hardware-discovery /etc/smartbag/hardware-discovery.json \
        --radar-config /etc/smartbag/mr20.json >/dev/null 2>&1 \
       && python3 /root/smartbag/radar_vision_fusion/validate_radar_camera_calibration.py \
        /etc/smartbag/fusion-right.json --require-measured \
        --hardware-discovery /etc/smartbag/hardware-discovery.json \
        --radar-config /etc/smartbag/mr20.json >/dev/null 2>&1; then
        ACTIVE_FULL=1
    elif [ "$INTERACTIVE" -eq 1 ]; then
        printf 'Fusion calibration is not measured. Run the guided calibration now? [y/N] '
        read answer
        case "$answer" in
            y|Y|yes|YES) "$DEPLOY/smartbag-calibrate-fusion.sh" --interactive ;;
            *) echo "Keeping safe radar-only mode until calibration is complete." ;;
        esac
        if python3 /root/smartbag/radar_vision_fusion/validate_radar_camera_calibration.py \
            /etc/smartbag/fusion-left.json --require-measured \
            --hardware-discovery /etc/smartbag/hardware-discovery.json \
            --radar-config /etc/smartbag/mr20.json >/dev/null 2>&1 \
           && python3 /root/smartbag/radar_vision_fusion/validate_radar_camera_calibration.py \
            /etc/smartbag/fusion-right.json --require-measured \
            --hardware-discovery /etc/smartbag/hardware-discovery.json \
            --radar-config /etc/smartbag/mr20.json >/dev/null 2>&1; then
            ACTIVE_FULL=1
        fi
    else
        echo "full mode requires measured left/right fusion calibration; run smartbag-calibrate-fusion.sh --interactive" >&2
        exit 1
    fi
fi

python3 - /etc/smartbag/config.json "$ACTIVE_FULL" <<'PY'
import json
import os
import sys
from pathlib import Path
path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
full = sys.argv[2] == "1"
data["runtime_mode"] = "radar_primary_visual_classification" if full else "radar_only"
data.setdefault("snapshot_classifier", {})["enabled"] = full
temporary = path.with_suffix(".json.tmp")
temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
os.replace(temporary, path)
PY

"$DEPLOY/check-board-runtime.sh" --config /etc/smartbag/config.json --mode "$([ "$ACTIVE_FULL" -eq 1 ] && echo full || echo radar-only)"
"$DEPLOY/preflight.sh" /etc/smartbag/config.json
systemctl daemon-reload
systemctl enable smartbag.target
if [ "$NO_START" -eq 0 ]; then
    systemctl restart smartbag.target
    systemctl is-active --quiet smartbag.target
fi

trap - EXIT INT TERM
echo "SmartBag installation completed. Status: systemctl status smartbag.target"
echo "Logs: journalctl -u 'smartbag-*' -f and /var/log/smartbag"
