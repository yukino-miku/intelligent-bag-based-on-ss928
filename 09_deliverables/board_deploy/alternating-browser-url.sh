#!/bin/sh
set -eu
CONFIG=${1:-/etc/smartbag/config.json}
PORT=$(python3 - "$CONFIG" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get("alternating_camera", {}).get("serve_port", 8080))
PY
)
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -n "$IP" ] || IP='<BOARD_IP>'
echo "http://$IP:$PORT/"
echo "SSH tunnel: ssh -L $PORT:127.0.0.1:$PORT root@$IP"
