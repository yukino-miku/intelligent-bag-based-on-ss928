#!/bin/sh
set -eu
systemctl stop smartbag.target
/root/smartbag/safe-off.sh 2>/dev/null || true
