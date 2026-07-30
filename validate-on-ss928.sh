#!/bin/sh
set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEPLOY="$REPO_ROOT/09_deliverables/board_deploy"
MODE=radar-only
DURATION=30m

while [ "$#" -gt 0 ]; do
    case "$1" in
        --full) MODE=full; shift ;;
        --radar-only) MODE=radar-only; shift ;;
        --duration) DURATION=$2; shift 2 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

case "$DURATION" in
    *m) DURATION_S=$(( ${DURATION%m} * 60 )) ;;
    *h) DURATION_S=$(( ${DURATION%h} * 3600 )) ;;
    *s) DURATION_S=${DURATION%s} ;;
    *) DURATION_S=$DURATION ;;
esac

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
"$DEPLOY/check-board-runtime.sh" --config /etc/smartbag/config.json --mode "$MODE"
"$DEPLOY/preflight.sh" /etc/smartbag/config.json
/root/smartbag/vision/ss928_backend/bin/ss928_detection_runner --version
systemctl restart smartbag.target
systemctl is-active --quiet smartbag.target

START=$(date +%s)
END=$((START + DURATION_S))
while [ "$(date +%s)" -lt "$END" ]; do
    systemctl is-active --quiet smartbag-alert.service || {
        echo "FAIL smartbag-alert.service stopped during validation" >&2
        exit 1
    }
    /root/smartbag/deploy/status.sh --check >/dev/null
    sleep 10
done

OUTPUT=/var/lib/smartbag/validation/$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$OUTPUT"
uname -a >"$OUTPUT/uname.txt"
cat /etc/os-release >"$OUTPUT/os-release.txt"
systemctl --no-pager --full status smartbag.target smartbag-alert.service >"$OUTPUT/systemd-status.txt"
/root/smartbag/deploy/status.sh >"$OUTPUT/runtime-status.json"
journalctl -u smartbag-alert.service --since "@$START" --no-pager >"$OUTPUT/smartbag-alert.log"
echo "Long-run validation completed for mode=$MODE duration=${DURATION_S}s. Evidence: $OUTPUT"
echo "Reboot and independent-power autostart must still be checked separately before setting POWER_ONLY_AUTOSTART_READY=true."
