#!/bin/sh
set -eu
systemctl stop smartbag.target
systemctl stop smartbag-cloud-uploader.service 2>/dev/null || true
