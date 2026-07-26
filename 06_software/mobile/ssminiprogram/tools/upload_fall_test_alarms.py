#!/usr/bin/env python3
"""Upload generated fall alarms for checking the SmartBag Mini Program history page.

The upload token is read from SMARTBAG_UPLOAD_TOKEN, UPLOAD_TOKEN, or the
Git-ignored .local/device-access.md file. It is never printed.
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
    return match.group(1) if match else ""


def validate_arguments(args):
    if args.count < 1 or args.count > 100:
        raise ValueError("--count must be between 1 and 100")
    if args.interval_seconds <= 0:
        raise ValueError("--interval-seconds must be greater than 0")
    if not -90 <= args.latitude <= 90:
        raise ValueError("--latitude must be between -90 and 90")
    if not -180 <= args.longitude <= 180:
        raise ValueError("--longitude must be between -180 and 180")


def build_payload(args, now_ms):
    interval_ms = int(args.interval_seconds * 1000)
    alarms = []
    for index in range(args.count):
        reported_at = now_ms - (args.count - 1 - index) * interval_ms
        latitude = round(args.latitude + index * args.step, 7)
        longitude = round(args.longitude + index * args.step, 7)
        alarms.append({
            "alarmId": "fall-test-{}-{}".format(now_ms, index),
            "requestId": "fall-alarm-{}-{}".format(now_ms, index),
            "reportedAt": reported_at,
            "alarmType": "fall_detected",
            "riskLevel": 3,
            "message": args.message_prefix + " #{}".format(index + 1),
            "location": {
                "latitude": latitude,
                "longitude": longitude,
                "accuracyM": args.accuracy,
                "valid": True,
            },
        })

    latest = alarms[-1]
    return {
        "version": 1,
        "deviceId": DEVICE_ID,
        "requestId": "fall-test-request-{}-{}".format(now_ms, uuid.uuid4().hex[:8]),
        "reportedAt": now_ms,
        "status": {
            "reportedAt": now_ms,
            "location": latest["location"],
            "network": {"type": "local-test", "online": True},
        },
        "trackPoints": [],
        "alarms": alarms,
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
    parser = argparse.ArgumentParser(description="Upload generated fall alarms for bag001.")
    parser.add_argument("--count", type=int, default=3, help="Number of fall alarms to upload (1-100).")
    parser.add_argument("--latitude", type=float, default=30.65736, help="Latitude of the first alarm.")
    parser.add_argument("--longitude", type=float, default=104.0832, help="Longitude of the first alarm.")
    parser.add_argument("--step", type=float, default=0.0001, help="Coordinate increment per alarm.")
    parser.add_argument("--interval-seconds", type=float, default=10, help="Time interval between alarms.")
    parser.add_argument("--accuracy", type=float, default=8, help="GNSS accuracy in meters.")
    parser.add_argument("--message-prefix", default="检测到用户摔倒（本地测试）", help="Message prefix for each alarm.")
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
    print("Uploading {} fall alarms for {}.".format(args.count, DEVICE_ID))
    return upload(upload_url, upload_token, payload)


if __name__ == "__main__":
    sys.exit(main())
