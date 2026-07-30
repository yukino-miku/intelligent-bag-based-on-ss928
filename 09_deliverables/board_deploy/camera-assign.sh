#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
LEFT=""
RIGHT=""
YES=0
INTERACTIVE=0
REUSE=0
RESET=0
DISCOVERY=/etc/smartbag/hardware-discovery.json

while [ "$#" -gt 0 ]; do
    case "$1" in
        --left) LEFT=$2; shift 2 ;;
        --right) RIGHT=$2; shift 2 ;;
        --interactive) INTERACTIVE=1; shift ;;
        --reuse-existing) REUSE=1; shift ;;
        --discovery) DISCOVERY=$2; shift 2 ;;
        --reset) RESET=1; shift ;;
        --yes) YES=1; shift ;;
        *) echo "unknown camera assignment option: $1" >&2; exit 2 ;;
    esac
done

if [ "$RESET" -eq 1 ]; then
    rm -f "$DISCOVERY" /etc/udev/rules.d/99-smartbag-cameras.rules
    echo "camera assignment reset"
fi

if [ "$REUSE" -eq 1 ] || { [ "$YES" -eq 1 ] && [ -z "$LEFT" ] && [ -z "$RIGHT" ]; }; then
    [ -f "$DISCOVERY" ] || { echo "--yes can only reuse an existing validated discovery file" >&2; exit 1; }
    python3 "$SCRIPT_DIR/camera_discovery.py" validate --discovery "$DISCOVERY"
    "$SCRIPT_DIR/camera-udev-install.sh" "$DISCOVERY"
    exit 0
fi

if [ "$INTERACTIVE" -eq 1 ] || { [ -z "$LEFT" ] && [ -z "$RIGHT" ]; }; then
    [ "$YES" -eq 0 ] || { echo "interactive camera assignment is unavailable with --yes" >&2; exit 1; }
    DISCOVERED=$(python3 "$SCRIPT_DIR/camera_discovery.py" discover)
    COUNT=$(printf '%s' "$DISCOVERED" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["cameras"]))')
    [ "$COUNT" -eq 2 ] || { echo "interactive assignment requires exactly two physical capture devices; found $COUNT" >&2; exit 1; }
    FIRST=$(printf '%s' "$DISCOVERED" | python3 -c 'import json,sys; print(json.load(sys.stdin)["cameras"][0]["by_path"])')
    SECOND=$(printf '%s' "$DISCOVERED" | python3 -c 'import json,sys; print(json.load(sys.stdin)["cameras"][1]["by_path"])')
    echo "Testing candidate A only: $FIRST"
    "$SCRIPT_DIR/camera-test.sh" "$FIRST"
    printf 'Candidate A is mounted on which side? [left/right] '
    read side
    case "$side" in
        left|LEFT|l|L) LEFT=$FIRST; RIGHT=$SECOND ;;
        right|RIGHT|r|R) LEFT=$SECOND; RIGHT=$FIRST ;;
        *) echo "invalid side; assignment cancelled" >&2; exit 1 ;;
    esac
    echo "Testing candidate B only: $SECOND"
    "$SCRIPT_DIR/camera-test.sh" "$SECOND"
fi

[ -n "$LEFT" ] && [ -n "$RIGHT" ] || { echo "specify --left/--right or use --interactive" >&2; exit 1; }
if [ "$YES" -eq 0 ]; then
    printf 'Open LEFT then RIGHT camera sequentially and assign physical ports? [y/N] '
    read answer
    case "$answer" in y|Y|yes|YES) ;; *) echo "cancelled"; exit 1 ;; esac
fi

python3 "$SCRIPT_DIR/camera_discovery.py" assign --left "$LEFT" --right "$RIGHT" --output "$DISCOVERY"
"$SCRIPT_DIR/camera-udev-install.sh" "$DISCOVERY"
