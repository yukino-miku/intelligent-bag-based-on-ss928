#!/usr/bin/env python3
"""Build or upload deterministic SmartBag board telemetry samples."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


WORK_DIR = Path(__file__).resolve().parents[2]
if str(WORK_DIR) not in sys.path:
    sys.path.insert(0, str(WORK_DIR))

from smartbag_cloud_uploader.telemetry_client import (  # noqa: E402
    UPLOAD_URL,
    build_fall_payload,
    build_posture_payload,
    build_track_payload,
)


LOCAL_CREDENTIAL_FILE = Path(__file__).resolve().parents[3] / ".local" / "device-access.md"


def read_token() -> str:
    token = os.environ.get("SMARTBAG_UPLOAD_TOKEN", "") or os.environ.get("UPLOAD_TOKEN", "")
    if token or not LOCAL_CREDENTIAL_FILE.exists():
        return token
    text = LOCAL_CREDENTIAL_FILE.read_text(encoding="utf-8")
    match = re.search(
        r"(?:SMARTBAG_UPLOAD_TOKEN|UPLOAD_TOKEN|上传令牌)\s*[:：=]\s*[`\"']?([^`\"'\s]+)",
        text,
    )
    return match.group(1) if match else ""


def build_payloads(kind: str, reported_at_ms: int) -> list[dict]:
    timestamp_s = reported_at_ms / 1000.0
    location = {"latitude": 30.65736, "longitude": 104.0832, "accuracyM": 8.0}
    payloads = {
        "track": build_track_payload(
            {
                "t": timestamp_s,
                "lat": location["latitude"],
                "lon": location["longitude"],
                "acc": location["accuracyM"],
                "fix": 1,
                "spd": 1.2,
                "course": 92.0,
                "alt": 510.0,
            },
            request_id=f"sim-track-{reported_at_ms}",
        ),
        "posture": build_posture_payload(
            {
                "reportedAt": reported_at_ms,
                "posture_status": "bad",
                "is_wearing": True,
                "reminder_active": True,
                "rollDeg": 1.2,
                "pitchDeg": -18.4,
                "yawDeg": 92.1,
            },
            daily={
                "date": time.strftime("%Y-%m-%d", time.localtime(timestamp_s)),
                "wearing_seconds": 20,
                "good_seconds": 15,
                "bad_seconds": 5,
                "updated_at": reported_at_ms,
            },
            request_id=f"sim-posture-{reported_at_ms}",
        ),
        "fall": build_fall_payload(
            {
                "signal": "FALL_ALARM",
                "alarmType": "fall_detected",
                "deviceTimestampMs": reported_at_ms,
                "conditions": {"impact": True, "posture": True, "stillness": True},
            },
            location=location,
            request_id=f"sim-fall-{reported_at_ms}",
        ),
    }
    return [payloads[kind]] if kind != "all" else [payloads[name] for name in ("track", "posture", "fall")]


def upload(payload: dict, token: str, url: str) -> bool:
    raw_body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=raw_body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("X-Upload-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            print("HTTP " + str(response.status) + " " + response.read().decode("utf-8"))
            return response.status == 200
    except urllib.error.HTTPError as error:
        print("HTTP " + str(error.code) + " " + error.read().decode("utf-8"))
        return False
    except urllib.error.URLError as error:
        print("Request failed: " + type(error.reason).__name__, file=sys.stderr)
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("all", "track", "posture", "fall"), default="all")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads without sending them")
    parser.add_argument("--reported-at", type=int, help="Fixed Unix timestamp in milliseconds")
    parser.add_argument("--url", default=UPLOAD_URL, help="CloudBase HTTP access URL")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reported_at_ms = args.reported_at or int(time.time() * 1000)
    payloads = build_payloads(args.kind, reported_at_ms)
    if args.dry_run:
        print(json.dumps(payloads, indent=2, ensure_ascii=False))
        return 0
    token = read_token()
    if not token:
        print(
            "Missing SMARTBAG_UPLOAD_TOKEN, UPLOAD_TOKEN, or a token in .local/device-access.md.",
            file=sys.stderr,
        )
        return 2
    return 0 if all(upload(payload, token, args.url) for payload in payloads) else 1


if __name__ == "__main__":
    sys.exit(main())
