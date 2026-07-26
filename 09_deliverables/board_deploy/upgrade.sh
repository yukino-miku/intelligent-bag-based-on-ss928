#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=${1:-$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)}
systemctl stop smartbag.target 2>/dev/null || true
sh "$SCRIPT_DIR/install.sh" "$REPO_ROOT"
systemctl start smartbag.target
