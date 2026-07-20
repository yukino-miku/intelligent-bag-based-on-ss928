#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
WHEELHOUSE=${1:?usage: install-board-deps-offline.sh /path/to/wheelhouse}
REQ=${2:-/root/smartbag/vision/requirements-board-cpu.txt}
PYTHON=${SMARTBAG_PYTHON:-/root/smartbag/venv/bin/python}

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ -d "$WHEELHOUSE" ] || { echo "wheelhouse not found: $WHEELHOUSE" >&2; exit 1; }
[ -f "$REQ" ] || { echo "requirements file not found: $REQ" >&2; exit 1; }
[ -x "$PYTHON" ] || { echo "runtime python not found: $PYTHON" >&2; exit 1; }

echo "Wheel inventory and SHA256:"
find "$WHEELHOUSE" -maxdepth 1 -type f -name '*.whl' -print0 | sort -z | xargs -0 -r sha256sum
"$PYTHON" -m pip install --no-index --find-links "$WHEELHOUSE" -r "$REQ"
"$SCRIPT_DIR/check-runtime-deps.sh"
