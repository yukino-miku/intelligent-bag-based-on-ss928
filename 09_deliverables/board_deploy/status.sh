#!/bin/sh
set -eu

CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1
ENV_FILE=/etc/smartbag/smartbag.env
TOKEN=$(sed -n 's/^SMARTBAG_API_TOKEN=//p' "$ENV_FILE" 2>/dev/null | tail -n 1)

if [ "$CHECK" -eq 0 ]; then
    systemctl --no-pager --full status smartbag.target smartbag-ws73.service smartbag-alert.service smartbag-connectivity.service smartbag-temperature.service >&2 || true
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required for runtime status" >&2
    exit 1
fi
[ -n "$TOKEN" ] || { echo "SMARTBAG_API_TOKEN is missing" >&2; exit 1; }
STATUS=$(curl --fail --silent --show-error -H "X-SmartBag-Token: $TOKEN" http://127.0.0.1:8080/api/v1/fusion/status)
if [ "$CHECK" -eq 1 ]; then
    printf '%s' "$STATUS" | python3 -c '
import json, sys
data = json.load(sys.stdin)
radars = data.get("radars", {})
if not radars or not all(item.get("worker_alive") and item.get("online") for item in radars.values()):
    raise SystemExit("one or more MR20 workers are offline")
'
else
    printf '%s\n' "$STATUS"
fi
