#!/bin/sh
set -eu
journalctl -u smartbag-ws73.service -u smartbag-alert.service -u smartbag-video.service -u smartbag-connectivity.service -u smartbag-temperature.service -u smartbag-vision.service -u smartbag-gnss.service -u smartbag-imu.service "$@"
