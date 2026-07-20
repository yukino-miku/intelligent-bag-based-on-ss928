#!/bin/sh
set -eu
journalctl -u smartbag-alert.service -u smartbag-video.service -u smartbag-vision.service -u smartbag-gnss.service -u smartbag-imu.service -u smartbag-cloud-uploader.service "$@"
