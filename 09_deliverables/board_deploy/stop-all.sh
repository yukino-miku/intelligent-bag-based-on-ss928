#!/bin/sh
set -eu
systemctl stop smartbag.target
systemctl stop smartbag-cloud-uploader.service 2>/dev/null || true
/root/smartbag/venv/bin/python /root/smartbag/board-deploy/safe_off.py --hardware /etc/smartbag/hardware.json
