#!/bin/sh
set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY="$REPO_ROOT/09_deliverables/board_deploy"
PROFILE="$DEPLOY/profiles/euler-pi-ss928-smartbag.json"
MODEL_SOURCE=""
RUNNER_SOURCE="$DEPLOY/bin/aarch64/ss928_detection_runner"
NO_START=0
RADAR_ONLY=0
SKIP_OPTIONAL=0
OFFLINE=0
ASSUME_YES=0
ROOT_PREFIX=${SMARTBAG_ROOT_PREFIX:-}

usage() {
    cat <<'EOF'
Usage: sudo ./install-on-ss928.sh [options]
  --profile PATH       hardware profile JSON
  --model-source PATH  accepted vehicle-detector.om
  --runner-source PATH alternate AArch64 runner
  --no-start           install and enable, but do not start services
  --radar-only         disable visual classification; model is not required
  --skip-optional      skip optional package installation
  --offline            do not use apt or network
  --yes                do not prompt for confirmation
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --profile) PROFILE=$2; shift 2 ;;
        --model-source) MODEL_SOURCE=$2; shift 2 ;;
        --runner-source) RUNNER_SOURCE=$2; shift 2 ;;
        --no-start) NO_START=1; shift ;;
        --radar-only) RADAR_ONLY=1; shift ;;
        --skip-optional) SKIP_OPTIONAL=1; shift ;;
        --offline) OFFLINE=1; shift ;;
        --yes) ASSUME_YES=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [ -z "$ROOT_PREFIX" ]; then
    [ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
    case "$(uname -m)" in
        aarch64|arm64) ;;
        *) echo "unsupported architecture: $(uname -m); SS928 installer requires aarch64" >&2; exit 1 ;;
    esac
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

if [ "$RADAR_ONLY" -eq 0 ]; then
    [ -n "$MODEL_SOURCE" ] || {
        echo "full mode requires --model-source; the candidate OM is not distributed because license and board validation are unresolved" >&2
        exit 1
    }
    python3 "$DEPLOY/verify_release_assets.py" \
        --model "$MODEL_SOURCE" --model-manifest "$DEPLOY/models/vehicle-detector.manifest.json"
fi

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
if [ "$RADAR_ONLY" -eq 1 ]; then
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

if [ "$RADAR_ONLY" -eq 0 ]; then
    "$DEPLOY/camera-assign.sh" --auto-known-topology --yes
fi
"$DEPLOY/check-board-runtime.sh" --config /etc/smartbag/config.json --mode "$([ "$RADAR_ONLY" -eq 1 ] && echo radar-only || echo full)"
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
