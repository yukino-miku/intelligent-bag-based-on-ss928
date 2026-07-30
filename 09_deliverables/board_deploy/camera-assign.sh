#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROFILE="$SCRIPT_DIR/profiles/euler-pi-ss928-smartbag.json"
LEFT=""
RIGHT=""
YES=0
AUTO=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --left) LEFT=$2; shift 2 ;;
        --right) RIGHT=$2; shift 2 ;;
        --profile) PROFILE=$2; shift 2 ;;
        --auto-known-topology) AUTO=1; shift ;;
        --yes) YES=1; shift ;;
        *) echo "unknown camera assignment option: $1" >&2; exit 2 ;;
    esac
done

if [ "$AUTO" -eq 1 ]; then
    LEFT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["cameras"]["known_topology"]["left_by_path"])' "$PROFILE")
    RIGHT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["cameras"]["known_topology"]["right_by_path"])' "$PROFILE")
fi
[ -n "$LEFT" ] && [ -n "$RIGHT" ] || {
    echo "specify --left and --right, or use --auto-known-topology" >&2
    "$SCRIPT_DIR/camera-discover.sh" >&2 || true
    exit 1
}
if [ "$YES" -eq 0 ]; then
    printf 'Open LEFT then RIGHT camera sequentially and assign physical ports? [y/N] '
    read answer
    case "$answer" in y|Y|yes|YES) ;; *) echo "cancelled"; exit 1 ;; esac
fi

python3 "$SCRIPT_DIR/camera_discovery.py" assign --left "$LEFT" --right "$RIGHT"
"$SCRIPT_DIR/camera-udev-install.sh"
