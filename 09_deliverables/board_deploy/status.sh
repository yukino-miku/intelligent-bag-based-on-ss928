#!/bin/sh
set -eu
systemctl --no-pager --full status smartbag.target smartbag-alert.service
