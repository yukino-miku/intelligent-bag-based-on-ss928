#!/bin/sh
set -eu
systemctl start smartbag.target
systemctl --no-pager --full status smartbag-alert.service smartbag-video.service
systemctl is-enabled --quiet smartbag-cloud-uploader.service 2>/dev/null && systemctl start smartbag-cloud-uploader.service || true
