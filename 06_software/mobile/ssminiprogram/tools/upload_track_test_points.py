#!/usr/bin/env python3
"""Upload generated GNSS history points for testing the SmartBag Mini Program.

Set SMARTBAG_UPLOAD_TOKEN before running.  UPLOAD_TOKEN is also accepted for
compatibility with simulate_device_upload.py.  The token is never printed.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


DEFAULT_UPLOAD_URL = (
    "https://cloud1-d7gdmg27139f4fbf2.service.tcloudbase.com/"
    "smartbag-device-ingest/v1/device/telemetry"
)
DEVICE_ID = "bag001"
LOCAL_CREDENTIAL_FILE = Path(__file__).resolve().parents[3] / ".local" / "device-access.md"


def get_upload_token():
    token = os.environ.get("SMARTBAG_UPLOAD_TOKEN", "") or os.environ.get("UPLOAD_TOKEN", "")
    if token:
        return token
    try:
        content = LOCAL_CREDENTIAL_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(
        r"(?:SMARTBAG_UPLOAD_TOKEN|UPLOAD_TOKEN|上传令牌)\s*[:：=]\s*[`\"']?([^`\"'\s]+)",
        content,
    )
    if match:
        return match.group(1)
    return ""


def validate_arguments(args):
    if args.count < 1 or args.count > 100:
        raise ValueError("--count must be between 1 and 100")
    if args.interval_seconds <= 0:
        raise ValueError("--interval-seconds must be greater than 0")
    if not -90 <= args.latitude <= 90:
        raise ValueError("--latitude must be between -90 and 90")
    if not -180 <= args.longitude <= 180:
        raise ValueError("--longitude must be between -180 and 180")
    last_latitude = args.latitude + (args.count - 1) * args.step
    last_longitude = args.longitude + (args.count - 1) * args.step
    if not -90 <= last_latitude <= 90 or not -180 <= last_longitude <= 180:
        raise ValueError("--step moves the generated route outside valid coordinates")


def build_payload(args, now_ms):
    interval_ms = int(args.interval_seconds * 1000)
    start_ms = now_ms - (args.count - 1) * interval_ms
    track_points = []
    for index in range(args.count):
        latitude = args.latitude + index * args.step
        longitude = args.longitude + index * args.step
        track_points.append({
            "requestId": "track-point-{}-{}".format(now_ms, index),
            "reportedAt": start_ms + index * interval_ms,
            "location": {
                "latitude": round(latitude, 7),
                "longitude": round(longitude, 7),
                "accuracyM": args.accuracy,
                "valid": True,
            },
            "speed": args.speed,
            "heading": args.heading,
        })

    latest = track_points[-1]
    return {
        "version": 1,
        "deviceId": DEVICE_ID,
        "requestId": "track-test-{}-{}".format(now_ms, uuid.uuid4().hex[:8]),
        "reportedAt": now_ms,
        "status": {
            "reportedAt": now_ms,
            "location": latest["location"],
            "network": {"type": "local-test", "online": True},
        },
        "trackPoints": track_points,
        "alarms": [],
    }


def upload(upload_url, upload_token, payload):
    raw_body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(upload_url, data=raw_body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("X-Upload-Token", upload_token)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            print("HTTP {}".format(response.status))
            print(response.read().decode("utf-8"))
            return 0
    except urllib.error.HTTPError as error:
        print("HTTP {}".format(error.code), file=sys.stderr)
        print(error.read().decode("utf-8"), file=sys.stderr)
        return 1
    except urllib.error.URLError as error:
        print("Request failed: {}".format(error.reason), file=sys.stderr)
        return 1


def parse_arguments():
    parser = argparse.ArgumentParser(description="Upload generated CloudBase GNSS history points for bag001.")
    parser.add_argument("--count", type=int, default=5, help="Number of history points to upload (1-100).")
    parser.add_argument("--latitude", type=float, default=30.65736, help="Latitude of the first point.")
    parser.add_argument("--longitude", type=float, default=104.0832, help="Longitude of the first point.")
    parser.add_argument("--step", type=float, default=0.0001, help="Coordinate increment per point.")
    parser.add_argument("--interval-seconds", type=float, default=10, help="Time interval between points.")
    parser.add_argument("--accuracy", type=float, default=8, help="GNSS accuracy in meters.")
    parser.add_argument("--speed", type=float, default=1.2, help="Speed in meters per second.")
    parser.add_argument("--heading", type=float, default=92, help="Heading in degrees.")
    parser.add_argument("--dry-run", action="store_true", help="Print the payload without uploading it.")
    return parser.parse_args()


def main():
    args = parse_arguments()
    try:
        validate_arguments(args)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    payload = build_payload(args, int(time.time() * 1000))
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    upload_token = get_upload_token()
    if not upload_token:
        print("Missing SMARTBAG_UPLOAD_TOKEN, UPLOAD_TOKEN, or a token in .local/device-access.md.", file=sys.stderr)
        return 2
    upload_url = os.environ.get("SMARTBAG_UPLOAD_URL", "") or os.environ.get("UPLOAD_URL", "") or DEFAULT_UPLOAD_URL
    print("Uploading {} track points for {}.".format(args.count, DEVICE_ID))
    return upload(upload_url, upload_token, payload)


if __name__ == "__main__":
    sys.exit(main())
