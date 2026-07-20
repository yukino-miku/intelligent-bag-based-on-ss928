#!/bin/sh
set -eu
systemctl start smartbag.target
systemctl --no-pager --full status smartbag.target smartbag-controller.service smartbag-safe-off.service
systemctl is-enabled --quiet smartbag-cloud-uploader.service 2>/dev/null && systemctl start smartbag-cloud-uploader.service || true
