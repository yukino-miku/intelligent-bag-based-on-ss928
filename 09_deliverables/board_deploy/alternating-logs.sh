#!/bin/sh
set -eu
journalctl -u smartbag-alternating-vision.service --no-pager -n "${LINES:-200}" "$@"
