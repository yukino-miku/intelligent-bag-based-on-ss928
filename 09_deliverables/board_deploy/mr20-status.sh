#!/bin/sh
set -eu
"$(dirname "$0")/mr20-network-preflight.sh"
journalctl -u smartbag-controller.service --since '-5 min' --no-pager | grep -E 'MR20|radar' || true
[ -r /run/smartbag/controller-status.json ] && python3 -m json.tool /run/smartbag/controller-status.json || true
