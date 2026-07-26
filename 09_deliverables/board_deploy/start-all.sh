#!/bin/sh
set -eu
systemctl start smartbag.target
systemctl --no-pager --full status smartbag-ws73.service smartbag-alert.service smartbag-video.service smartbag-connectivity.service smartbag-temperature.service
