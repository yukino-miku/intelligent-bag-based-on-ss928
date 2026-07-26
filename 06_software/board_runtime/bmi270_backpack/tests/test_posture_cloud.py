from __future__ import annotations

import copy
import contextlib
import io
import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
WORK_DIR = PROJECT_DIR.parent
IMU_PROJECT_DIR = WORK_DIR / "imu_fall_detector"
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(WORK_DIR))
sys.path.insert(0, str(IMU_PROJECT_DIR))

import bmi270_backpack as bmi  # noqa: E402
from fall_fusion import FallFusionConfig, write_high_warning_marker  # noqa: E402
from fall_fusion_runtime import FallFusionRuntime  # noqa: E402
from posture_cloud import PostureCloudReporter, PostureDailyAccumulator  # noqa: E402
from cloud_uploader import write_latest_location  # noqa: E402


def posture_state(t_mono, pitch=-18.0, accel_g=1.0, gyro_dps=2.0):
    return {
        "t_mono": float(t_mono),
        "pitch_deg": float(pitch),
        "roll_deg": 1.2,
        "yaw_deg": 92.1,
        "accel_g": float(accel_g),
        "gyro_dps": float(gyro_dps),
        "speed_mps": 0.0,
    }


class HunchStateTests(unittest.TestCase):
    def test_hunch_state_requires_existing_hold_and_motion_gates_then_clears(self):
        cfg = copy.deepcopy(bmi.DEFAULT_CONFIG)
        cfg["thresholds"].update({
            "tilt_enabled": False,
            "hunch_enabled": True,
            "hunch_pitch_deg": -15.5,
            "hunch_hold_s": 1.0,
            "hunch_max_gyro_dps": 30.0,
            "hunch_accel_min_g": 0.75,
            "hunch_accel_max_g": 1.25,
            "impact_g": 99.0,
            "freefall_g": 0.0,
            "speed_warn_mps": 99.0,
        })
        detector = bmi.AnomalyDetector(cfg)

        detector.update(posture_state(0.0))
        detector.update(posture_state(0.5))
        self.assertFalse(detector.is_condition_active("HUNCH"))

        alerts = detector.update(posture_state(1.0))
        self.assertTrue(detector.is_condition_active("HUNCH"))
        self.assertEqual([item["code"] for item in alerts], ["HUNCH"])

        detector.update(posture_state(1.1, pitch=-5.0))
        self.assertFalse(detector.is_condition_active("HUNCH"))


class CallAlertConfigTests(unittest.TestCase):
    def test_call_sink_uses_root_only_environment_phone_and_ring_duration(self):
        cfg = copy.deepcopy(bmi.DEFAULT_CONFIG)
        self.assertIsNone(bmi.make_call_alarm_sink(cfg, environ={}))

        cfg["call_alert"].update(
            {
                "enabled": True,
                "phone_env": "SMARTBAG_ALERT_PHONE",
                "ring_seconds": 12.0,
            }
        )
        sink = bmi.make_call_alarm_sink(
            cfg,
            environ={"SMARTBAG_ALERT_PHONE": "15500001111"},
        )

        self.assertEqual(sink.phone, "15500001111")
        self.assertEqual(sink.ring_seconds, 12.0)

    def test_enabled_call_sink_skips_missing_phone_without_stopping_service(self):
        cfg = copy.deepcopy(bmi.DEFAULT_CONFIG)
        cfg["call_alert"]["enabled"] = True

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            sink = bmi.make_call_alarm_sink(cfg, environ={})

        self.assertIsNone(sink)
        self.assertIn("SMARTBAG_ALERT_PHONE is not set", stderr.getvalue())

    def test_enabled_call_sink_skips_invalid_phone_without_logging_it(self):
        cfg = copy.deepcopy(bmi.DEFAULT_CONFIG)
        cfg["call_alert"]["enabled"] = True
        invalid_phone = "123;AT+CMGS=1"

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            sink = bmi.make_call_alarm_sink(
                cfg,
                environ={"SMARTBAG_ALERT_PHONE": invalid_phone},
            )

        self.assertIsNone(sink)
        self.assertIn("SMARTBAG_ALERT_PHONE is invalid", stderr.getvalue())
        self.assertNotIn(invalid_phone, stderr.getvalue())


class PostureDailyAccumulatorTests(unittest.TestCase):
    def test_uses_china_calendar_date_when_board_clock_is_utc(self):
        with tempfile.TemporaryDirectory() as temp:
            accumulator = PostureDailyAccumulator(Path(temp) / "daily.json")
            # 2026-07-21 20:00:00 UTC is 2026-07-22 04:00:00 in China.
            result = accumulator.update("bad", now_wall=1784664000.0)
            self.assertEqual(result["date"], "2026-07-22")

    def test_migrates_an_existing_utc_key_without_resetting_today_totals(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "daily.json"
            path.write_text(json.dumps({
                "device_id": "bag001", "date": "2026-07-21",
                "wearing_seconds": 30.0, "good_seconds": 10.0, "bad_seconds": 20.0,
                "updated_at": 1784664000000, "last_wall": 1784664000.0, "last_status": "bad",
            }), encoding="utf-8")
            result = PostureDailyAccumulator(path).update("bad", now_wall=1784664005.0)
            self.assertEqual(result["date"], "2026-07-22")
            self.assertEqual(result["wearing_seconds"], 35.0)
            self.assertEqual(result["bad_seconds"], 25.0)

    def test_accumulates_absolute_totals_persists_and_rolls_date(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "daily.json"
            accumulator = PostureDailyAccumulator(path, max_gap_s=10.0)

            first = accumulator.update("good", now_wall=1_721_430_000.0)
            second = accumulator.update("good", now_wall=1_721_430_005.0)
            third = accumulator.update("bad", now_wall=1_721_430_008.0)

            self.assertEqual(first["wearing_seconds"], 0.0)
            self.assertEqual(second["good_seconds"], 5.0)
            self.assertEqual(third["good_seconds"], 8.0)
            self.assertEqual(third["bad_seconds"], 0.0)
            self.assertLessEqual(
                third["good_seconds"] + third["bad_seconds"],
                third["wearing_seconds"],
            )

            restored = PostureDailyAccumulator(path, max_gap_s=10.0)
            resumed = restored.update("bad", now_wall=1_721_430_010.0)
            self.assertEqual(resumed["bad_seconds"], 2.0)

            next_day = restored.update("good", now_wall=1_721_516_410.0)
            self.assertNotEqual(next_day["date"], resumed["date"])
            self.assertEqual(next_day["wearing_seconds"], 0.0)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["date"], next_day["date"])

    def test_large_clock_gap_is_not_counted_as_continuous_wearing(self):
        with tempfile.TemporaryDirectory() as temp:
            accumulator = PostureDailyAccumulator(Path(temp) / "daily.json", max_gap_s=10.0)
            accumulator.update("good", now_wall=1000.0)
            result = accumulator.update("good", now_wall=1100.0)
            self.assertEqual(result["wearing_seconds"], 0.0)


class PostureCloudReporterTests(unittest.TestCase):
    def test_uploads_processed_snapshot_without_raw_imu(self):
        class FakeClient:
            def __init__(self):
                self.statuses = []

            def submit_latest_status(self, payload):
                self.statuses.append(payload)
                return True

        with tempfile.TemporaryDirectory() as temp:
            client = FakeClient()
            reporter = PostureCloudReporter(
                client,
                PostureDailyAccumulator(Path(temp) / "daily.json"),
                interval_s=5.0,
            )
            state = posture_state(10.0)
            state.update({"ax_g": 0.0, "ay_g": 0.0, "az_g": 1.0, "gx_dps": 1.0})

            reporter.tick(state, hunch_active=True, now_mono=10.0, now_wall=1000.0)

            payload = client.statuses[0]
            self.assertEqual(payload["status"]["posture_status"], "bad")
            self.assertTrue(payload["status"]["reminder_active"])
            self.assertEqual(payload["status"]["attitude"]["pitchDeg"], -18.0)
            serialized = json.dumps(payload)
            self.assertNotIn("ax_g", serialized)
            self.assertNotIn("gx_dps", serialized)

    def test_final_fall_omits_location_when_gnss_is_stale(self):
        class FakeClient:
            def __init__(self):
                self.events = []

            def upload_event_now(self, payload):
                self.events.append(payload)
                return True

        final_event = {
            "signal": "FALL_ALARM",
            "alarmType": "fall_detected",
            "deviceTimestampMs": 10_000,
            "conditions": {"imu_fall_confirmed": True},
        }
        with tempfile.TemporaryDirectory() as temp:
            location_path = Path(temp) / "latest-location.json"
            write_latest_location(
                location_path,
                {"latitude": 31.23, "longitude": 121.47, "valid": True},
                reported_at_ms=9_000,
            )
            client = FakeClient()
            reporter = PostureCloudReporter(
                client,
                PostureDailyAccumulator(Path(temp) / "daily.json"),
                latest_location_path=location_path,
                location_max_age_s=5.0,
            )

            self.assertFalse(reporter.report_fall({"signal": "HIGH_WARNING"}, now_ms=10_000))
            self.assertTrue(reporter.report_fall(final_event, now_ms=10_000))
            self.assertIn("location", client.events[0]["alarms"][0])

            client.events.clear()
            self.assertTrue(reporter.report_fall(final_event, now_ms=20_000))
            self.assertNotIn("location", client.events[0]["alarms"][0])
            self.assertNotIn("location", client.events[0]["status"])


class FinalFallSinkTests(unittest.TestCase):
    def test_runtime_calls_local_and_cloud_sinks_once_for_final_alarm(self):
        @dataclass
        class Sample:
            t: float
            ax: float = 0.0
            ay: float = 0.0
            az: float = 9.80665
            gx: float = 0.0
            gy: float = 0.0
            gz: float = 0.0

        class FakeDetector:
            def __init__(self):
                self.calls = 0
                self.last_features = {"posture_delta_deg": 30.0}

            def update(self, sample):
                self.calls += 1
                if self.calls == 1:
                    return [{"event": "fall_confirmed", "t": sample.t}]
                return []

        local_events = []
        remote_order = []

        class ImmediateThread:
            def __init__(self, *, target, **kwargs):
                del kwargs
                self.target = target

            def start(self):
                self.target()
        clock = [1000.0]
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "warning.json"
            write_high_warning_marker(
                marker,
                {"source": "vision", "side": "right", "level": 3, "ts": 995.0},
            )
            runtime = FallFusionRuntime(
                warning_marker=marker,
                fusion_config=FallFusionConfig(recovery_window_s=7.0),
                detector=FakeDetector(),
                alarm_sink=local_events.append,
                cloud_alarm_sink=lambda event: remote_order.append("cloud_upload_complete"),
                call_alarm_sink=lambda event: remote_order.append("call_started"),
                remote_thread_factory=ImmediateThread,
                wall_clock=lambda: clock[0],
            )

            runtime.update(Sample(t=0.0))
            clock[0] = 1008.0
            alarm = runtime.update(Sample(t=8.0))

        self.assertEqual(alarm["signal"], "FALL_ALARM")
        self.assertEqual(len(local_events), 1)
        self.assertEqual(remote_order, ["cloud_upload_complete", "call_started"])


if __name__ == "__main__":
    unittest.main()
