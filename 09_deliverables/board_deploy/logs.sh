#!/bin/sh
set -eu
journalctl -u smartbag-controller.service -u smartbag-safe-off.service -u smartbag-boot-selftest.service -u smartbag-cloud-uploader.service "$@"
