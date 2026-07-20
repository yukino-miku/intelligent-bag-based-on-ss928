#!/bin/sh
set -eu

DEVICE=${1:?usage: camera-test.sh /dev/videoX [width] [height]}
WIDTH=${2:-640}
HEIGHT=${3:-480}
PYTHON=${SMARTBAG_PYTHON:-/root/smartbag/venv/bin/python}
[ -x "$PYTHON" ] || PYTHON=python3

"$PYTHON" - "$DEVICE" "$WIDTH" "$HEIGHT" <<'PY'
import sys
import time

import cv2

device = sys.argv[1]
capture = cv2.VideoCapture(device, cv2.CAP_ANY)
try:
    capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, int(sys.argv[2]))
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, int(sys.argv[3]))
    deadline = time.monotonic() + 5.0
    frame = None
    while time.monotonic() < deadline:
        ok, candidate = capture.read()
        if ok and candidate is not None:
            frame = candidate
            break
        time.sleep(0.05)
    if frame is None:
        raise SystemExit(f"FAIL no frame from {device}")
    print(f"OK   {device} frame={frame.shape[1]}x{frame.shape[0]}")
finally:
    capture.release()
PY
