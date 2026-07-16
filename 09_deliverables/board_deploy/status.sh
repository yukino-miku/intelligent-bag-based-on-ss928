#!/bin/sh
set -eu
systemctl --no-pager --full status smartbag.target smartbag-alert.service smartbag-video.service
if command -v curl >/dev/null 2>&1; then
    curl --silent --show-error http://127.0.0.1:8080/api/v1/status || true
    printf '\n'
fi
