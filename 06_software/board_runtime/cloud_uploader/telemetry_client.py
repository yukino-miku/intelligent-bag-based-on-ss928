from __future__ import annotations

import json
import math
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping


DEVICE_ID = "bag001"
UPLOAD_URL = (
    "https://cloud1-d7gdmg27139f4fbf2.service.tcloudbase.com/"
    "smartbag-device-ingest/v1/device/telemetry"
)


def _request_id(prefix: str, reported_at_ms: int) -> str:
    return f"{prefix}-{reported_at_ms}-{uuid.uuid4().hex[:8]}"


def _finite(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _coordinate(latitude: Any, longitude: Any, accuracy: Any = None) -> dict[str, Any]:
    lat = _finite(latitude, "latitude")
    lon = _finite(longitude, "longitude")
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise ValueError("coordinate out of range")
    result: dict[str, Any] = {"latitude": lat, "longitude": lon, "valid": True}
    if accuracy is not None:
        result["accuracyM"] = max(0.0, _finite(accuracy, "accuracy"))
    return result


def _base_payload(request_id: str, reported_at_ms: int) -> dict[str, Any]:
    return {
        "version": 1,
        "deviceId": DEVICE_ID,
        "requestId": request_id,
        "reportedAt": int(reported_at_ms),
        "status": {},
        "trackPoints": [],
        "alarms": [],
    }


def build_track_payload(
    point: Mapping[str, Any],
    request_id: str | None = None,
) -> dict[str, Any]:
    if int(point.get("fix") or 0) <= 0:
        raise ValueError("track point requires a valid fix")
    reported_at_ms = int(round(_finite(point.get("t"), "track time") * 1000.0))
    point_request_id = request_id or _request_id("track-dxgp21", reported_at_ms)
    location = _coordinate(point.get("lat"), point.get("lon"), point.get("acc"))
    track_point: dict[str, Any] = {
        "requestId": point_request_id,
        "reportedAt": reported_at_ms,
        "location": location,
        "source": "dx_gp21",
        "coordinateSystem": "wgs84",
    }
    optional_fields = {
        "speed": point.get("spd"),
        "heading": point.get("course"),
        "altitudeM": point.get("alt"),
    }
    for name, value in optional_fields.items():
        if value is not None:
            track_point[name] = _finite(value, name)
    payload = _base_payload(point_request_id, reported_at_ms)
    payload["status"] = {"reportedAt": reported_at_ms, "location": location}
    payload["trackPoints"] = [track_point]
    return payload


def build_posture_payload(
    snapshot: Mapping[str, Any],
    daily: Mapping[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    reported_at_ms = int(snapshot["reportedAt"])
    posture_status = str(snapshot.get("posture_status", ""))
    if posture_status not in ("good", "bad"):
        raise ValueError("posture_status must be good or bad")
    posture_request_id = request_id or _request_id("posture", reported_at_ms)
    status = {
        "reportedAt": reported_at_ms,
        "posture_status": posture_status,
        "is_wearing": bool(snapshot.get("is_wearing")),
        "reminder_active": bool(snapshot.get("reminder_active")),
        **({"reminder_type": str(snapshot["reminder_type"])} if snapshot.get("reminder_type") else {}),
        **({"reminder_reported_at": int(snapshot["reminder_reported_at"])} if snapshot.get("reminder_reported_at") else {}),
        "attitude": {
            "rollDeg": _finite(snapshot.get("rollDeg"), "rollDeg"),
            "pitchDeg": _finite(snapshot.get("pitchDeg"), "pitchDeg"),
            "yawDeg": _finite(snapshot.get("yawDeg"), "yawDeg"),
        },
    }
    if snapshot.get("chip_temperature_c") is not None:
        temperatures = snapshot["chip_temperature_c"]
        status["chip_temperature_c"] = {
            "tsensor0": _finite(temperatures["tsensor0"], "tsensor0"),
            "tsensor1": _finite(temperatures["tsensor1"], "tsensor1"),
            "tsensor2": _finite(temperatures["tsensor2"], "tsensor2"),
        }
    payload = _base_payload(posture_request_id, reported_at_ms)
    payload["status"] = status
    if daily is not None:
        payload["postureDaily"] = {
            "device_id": DEVICE_ID,
            "date": str(daily["date"]),
            "wearing_seconds": _finite(daily.get("wearing_seconds", 0), "wearing_seconds"),
            "good_seconds": _finite(daily.get("good_seconds", 0), "good_seconds"),
            "bad_seconds": _finite(daily.get("bad_seconds", 0), "bad_seconds"),
            "updated_at": int(daily.get("updated_at", reported_at_ms)),
        }
    return payload


def build_fall_payload(
    event: Mapping[str, Any],
    location: Mapping[str, Any] | None,
    request_id: str | None = None,
) -> dict[str, Any]:
    if event.get("signal") != "FALL_ALARM" or event.get("alarmType") != "fall_detected":
        raise ValueError("only final FALL_ALARM events may be uploaded")
    reported_at_ms = int(event.get("deviceTimestampMs") or round(float(event["ts"]) * 1000.0))
    alarm_request_id = request_id or _request_id("fall", reported_at_ms)
    alarm: dict[str, Any] = {
        "requestId": alarm_request_id,
        "alarmId": alarm_request_id,
        "alarmType": "fall_detected",
        "riskLevel": 3,
        "message": "检测到用户摔倒",
        "reportedAt": reported_at_ms,
        "details": {
            "signal": "FALL_ALARM",
            "conditions": dict(event.get("conditions") or {}),
        },
    }
    normalized_location = None
    if location:
        normalized_location = _coordinate(
            location.get("latitude"),
            location.get("longitude"),
            location.get("accuracyM"),
        )
        alarm["location"] = normalized_location
    payload = _base_payload(alarm_request_id, reported_at_ms)
    payload["status"] = {
        "reportedAt": reported_at_ms,
        "risk": {"level": 3, "type": "fall_detected"},
    }
    if normalized_location is not None:
        payload["status"]["location"] = normalized_location
    payload["alarms"] = [alarm]
    return payload


def build_hunch_reminder_payload(state: Mapping[str, Any], reminder: Mapping[str, Any]) -> dict[str, Any]:
    reported_at_ms = int(reminder["reportedAt"])
    request_id = str(reminder["requestId"])
    payload = _base_payload(request_id, reported_at_ms)
    payload["status"] = {
        "reportedAt": reported_at_ms,
        "posture_status": "bad",
        "is_wearing": True,
        "reminder_active": True,
        "reminder_type": "hunch_vibration_voice",
        "reminder_reported_at": reported_at_ms,
        "attitude": {
            "rollDeg": _finite(state["roll_deg"], "rollDeg"),
            "pitchDeg": _finite(state["pitch_deg"], "pitchDeg"),
            "yawDeg": _finite(state["yaw_deg"], "yawDeg"),
        },
    }
    payload["alarms"] = [{
        "requestId": request_id,
        "alarmId": request_id,
        "reportedAt": reported_at_ms,
        "alarmType": "posture_hunch_reminder",
        "riskLevel": 2,
        "message": "检测到持续驼背，已震动并播放语音提醒",
        "details": {"durationS": 5, "audioClip": "bad"},
    }]
    return payload


def write_latest_location(
    path: str | Path,
    location: Mapping[str, Any],
    reported_at_ms: int,
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "reportedAt": int(reported_at_ms),
        "location": _coordinate(
            location.get("latitude"),
            location.get("longitude"),
            location.get("accuracyM"),
        ),
    }
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(record, separators=(",", ":")), encoding="utf-8")
    temporary.replace(target)


def read_fresh_location(
    path: str | Path,
    now_ms: int,
    max_age_ms: int,
) -> dict[str, Any] | None:
    try:
        record = json.loads(Path(path).read_text(encoding="utf-8"))
        reported_at_ms = int(record["reportedAt"])
        age_ms = int(now_ms) - reported_at_ms
        if age_ms < 0 or age_ms > int(max_age_ms):
            return None
        location = record["location"]
        return _coordinate(
            location.get("latitude"),
            location.get("longitude"),
            location.get("accuracyM"),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


Transport = Callable[[Mapping[str, Any], str, float], None]


def _https_transport(payload: Mapping[str, Any], token: str, timeout_s: float) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(UPLOAD_URL, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("X-Upload-Token", token)
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")


class TelemetryClient:
    def __init__(
        self,
        token: str | None = None,
        transport: Transport | None = None,
        timeout_s: float = 5.0,
        event_queue_size: int = 32,
    ) -> None:
        self.token = token if token is not None else os.environ.get("SMARTBAG_UPLOAD_TOKEN", "")
        self.transport = transport or _https_transport
        self.timeout_s = max(0.1, float(timeout_s))
        self.events: queue.Queue[Mapping[str, Any]] = queue.Queue(maxsize=max(1, int(event_queue_size)))
        self.condition = threading.Condition()
        self.latest_status: Mapping[str, Any] | None = None
        self.stop_requested = False
        self.failed_count = 0
        self.dropped_count = 0
        self._missing_token_reported = False
        self.worker = threading.Thread(target=self._run, name="smartbag-cloud-upload", daemon=True)
        self.worker.start()

    def submit_latest_status(self, payload: Mapping[str, Any]) -> bool:
        with self.condition:
            self.latest_status = dict(payload)
            self.condition.notify()
        return bool(self.token)

    def submit_event(self, payload: Mapping[str, Any]) -> bool:
        try:
            self.events.put_nowait(dict(payload))
        except queue.Full:
            self.dropped_count += 1
            print("WARN cloud upload queue full; event dropped", file=sys.stderr, flush=True)
            return False
        with self.condition:
            self.condition.notify()
        return bool(self.token)

    def upload_event_now(self, payload: Mapping[str, Any]) -> bool:
        """Finish one event HTTP request before returning to its caller."""
        return self._upload_payload(payload)

    def close(self, timeout_s: float = 2.0) -> None:
        with self.condition:
            self.stop_requested = True
            self.condition.notify_all()
        self.worker.join(timeout=max(0.0, float(timeout_s)))

    def _next_payload(self) -> Mapping[str, Any] | None:
        try:
            return self.events.get_nowait()
        except queue.Empty:
            pass
        with self.condition:
            payload = self.latest_status
            self.latest_status = None
            return payload

    def _run(self) -> None:
        while True:
            payload = self._next_payload()
            if payload is None:
                with self.condition:
                    if self.stop_requested and self.events.empty() and self.latest_status is None:
                        return
                    self.condition.wait(timeout=0.1)
                continue
            self._upload_payload(payload)

    def _upload_payload(self, payload: Mapping[str, Any]) -> bool:
        if not self.token:
            if not self._missing_token_reported:
                print(
                    "Cloud upload skipped: SMARTBAG_UPLOAD_TOKEN is not set",
                    file=sys.stderr,
                    flush=True,
                )
                self._missing_token_reported = True
            return False
        try:
            self.transport(payload, self.token, self.timeout_s)
            return True
        except Exception as exc:
            self.failed_count += 1
            error_name = type(exc).__name__
            if isinstance(exc, urllib.error.HTTPError):
                error_name = f"HTTP_{exc.code}"
                try:
                    response = json.loads(exc.read().decode("utf-8", errors="replace"))
                    code = response.get("error", {}).get("code")
                    if isinstance(code, str) and code:
                        error_name = f"{error_name} {code}"
                except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
                    pass
            print(f"WARN cloud upload failed: {error_name}", file=sys.stderr, flush=True)
            return False
