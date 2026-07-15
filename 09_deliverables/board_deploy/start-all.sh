#!/bin/sh
set -eu
systemctl start smartbag.target
systemctl --no-pager --full status smartbag-alert.service
