#!/bin/sh
set -eu
systemctl --no-pager --full status smartbag.target smartbag-alert.service smartbag-video.service
systemctl --no-pager --full status smartbag-cloud-uploader.service 2>/dev/null || true
if command -v curl >/dev/null 2>&1; then
    curl --silent --show-error http://127.0.0.1:8080/api/v1/status || true
    printf '\n'
fi
"$(dirname "$0")/pwm-list.sh" || true
[ -r /run/smartbag/controller-status.json ] && python3 -m json.tool /run/smartbag/controller-status.json || true
