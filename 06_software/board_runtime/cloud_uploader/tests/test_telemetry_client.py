from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from cloud_uploader.telemetry_client import (  # noqa: E402
    TelemetryClient,
    build_fall_payload,
    build_posture_payload,
    build_track_payload,
    read_fresh_location,
    write_latest_location,
)


class PayloadBuilderTests(unittest.TestCase):
    def test_track_payload_maps_dx_gp21_point_and_uses_per_point_request_id(self):
        point = {
            "typ": "loc",
            "t": 1719981296.25,
            "lat": 31.23042,
            "lon": 121.4737,
            "acc": 4.5,
            "alt": 42.0,
            "spd": 0.8,
            "course": 92.0,
            "fix": 1,
            "src": "dx_gp21",
            "cs": "wgs84",
        }

        payload = build_track_payload(point, request_id="track-test-1")

        self.assertEqual(payload["deviceId"], "bag001")
        self.assertEqual(payload["requestId"], "track-test-1")
        self.assertEqual(payload["reportedAt"], 1719981296250)
        self.assertEqual(payload["status"]["location"]["latitude"], 31.23042)
        self.assertEqual(payload["trackPoints"][0]["requestId"], "track-test-1")
        self.assertEqual(payload["trackPoints"][0]["coordinateSystem"], "wgs84")
        self.assertEqual(payload["alarms"], [])

    def test_posture_payload_contains_processed_state_and_no_raw_imu_arrays(self):
        snapshot = {
            "reportedAt": 1719981296250,
            "posture_status": "bad",
            "is_wearing": True,
            "reminder_active": True,
            "rollDeg": 1.2,
            "pitchDeg": -18.4,
            "yawDeg": 92.1,
            "a": [0.0, 0.0, 1.0],
            "w": [1.0, 2.0, 3.0],
        }
        daily = {
            "date": "2026-07-20",
            "wearing_seconds": 20.0,
            "good_seconds": 15.0,
            "bad_seconds": 5.0,
            "updated_at": 1719981296250,
        }

        payload = build_posture_payload(snapshot, daily, request_id="posture-test-1")

        status = payload["status"]
        self.assertEqual(status["posture_status"], "bad")
        self.assertTrue(status["is_wearing"])
        self.assertTrue(status["reminder_active"])
        self.assertEqual(status["attitude"]["pitchDeg"], -18.4)
        self.assertNotIn("a", status)
        self.assertNotIn("w", status)
        self.assertEqual(payload["postureDaily"]["device_id"], "bag001")

    def test_fall_payload_rejects_non_final_warning_and_accepts_final_alarm(self):
        with self.assertRaises(ValueError):
            build_fall_payload(
                {"signal": "HIGH_WARNING", "deviceTimestampMs": 1719981296250},
                None,
                request_id="warning-test",
            )

        payload = build_fall_payload(
            {
                "signal": "FALL_ALARM",
                "alarmType": "fall_detected",
                "deviceTimestampMs": 1719981296250,
                "conditions": {"imu_fall_confirmed": True},
            },
            {"latitude": 31.23042, "longitude": 121.4737, "valid": True},
            request_id="fall-test-1",
        )

        alarm = payload["alarms"][0]
        self.assertEqual(alarm["requestId"], "fall-test-1")
        self.assertEqual(alarm["alarmType"], "fall_detected")
        self.assertEqual(alarm["riskLevel"], 3)
        self.assertEqual(alarm["details"]["signal"], "FALL_ALARM")
        self.assertEqual(payload["trackPoints"], [])


class LocationCacheTests(unittest.TestCase):
    def test_location_cache_is_atomic_and_stale_or_invalid_data_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "latest-location.json"
            location = {
                "latitude": 31.23042,
                "longitude": 121.4737,
                "accuracyM": 4.5,
                "valid": True,
            }
            write_latest_location(path, location, reported_at_ms=10_000)

            self.assertEqual(
                read_fresh_location(path, now_ms=12_000, max_age_ms=5_000),
                location,
            )
            self.assertIsNone(read_fresh_location(path, now_ms=20_000, max_age_ms=5_000))
            path.write_text("not-json", encoding="utf-8")
            self.assertIsNone(read_fresh_location(path, now_ms=12_000, max_age_ms=5_000))


class TelemetryClientTests(unittest.TestCase):
    def test_upload_event_now_returns_only_after_transport_completes(self):
        order = []

        def transport(payload, token, timeout_s):
            order.append((payload["requestId"], token, timeout_s))

        client = TelemetryClient(token="test-token", transport=transport, timeout_s=0.5)
        try:
            self.assertTrue(client.upload_event_now({"requestId": "fall-1"}))
        finally:
            client.close()

        self.assertEqual(order, [("fall-1", "test-token", 0.5)])

    def test_network_failure_does_not_raise_to_submitter_and_worker_continues(self):
        sent = []
        attempts = [RuntimeError("offline"), None]

        def transport(payload, token, timeout_s):
            outcome = attempts.pop(0)
            if outcome is not None:
                raise outcome
            sent.append((payload, token, timeout_s))

        client = TelemetryClient(
            token="test-token",
            transport=transport,
            timeout_s=0.1,
            event_queue_size=2,
        )
        try:
            self.assertTrue(client.submit_event({"requestId": "first"}))
            self.assertTrue(client.submit_event({"requestId": "second"}))
            deadline = time.time() + 2.0
            while time.time() < deadline and not sent:
                time.sleep(0.01)
        finally:
            client.close()

        self.assertEqual(sent[0][0]["requestId"], "second")
        self.assertEqual(client.failed_count, 1)


if __name__ == "__main__":
    unittest.main()
