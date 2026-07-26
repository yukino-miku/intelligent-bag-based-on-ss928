from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
IMU_PROJECT_DIR = PROJECT_DIR.parent / "imu_fall_detector"
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(IMU_PROJECT_DIR))

from fall_fusion import FallFusionConfig, write_high_warning_marker  # noqa: E402
from fall_fusion_runtime import FallFusionRuntime, to_detector_sample  # noqa: E402
from imu_fall_detector import DetectorConfig, FallImpactDetector  # noqa: E402


G = 9.80665


class ImmediateThread:
    def __init__(self, *, target, **kwargs):
        del kwargs
        self.target = target

    def start(self):
        self.target()


@dataclass
class BoardSample:
    t: float
    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float


def board_sample(t, ax=0.0, ay=0.0, az=1.0, gx=0.0, gy=0.0, gz=0.0):
    return BoardSample(t, ax * G, ay * G, az * G, gx, gy, gz)


class FallFusionRuntimeTests(unittest.TestCase):
    def test_manual_ble_trigger_uses_the_final_fall_alarm_sinks_once(self):
        with tempfile.TemporaryDirectory() as temp:
            trigger = Path(temp) / "manual-fall.json"
            events = []
            cloud_events = []
            call_events = []
            runtime = FallFusionRuntime(
                warning_marker=Path(temp) / "warning.json",
                alarm_sink=events.append,
                cloud_alarm_sink=cloud_events.append,
                call_alarm_sink=call_events.append,
                remote_thread_factory=ImmediateThread,
                manual_trigger_path=trigger,
                wall_clock=lambda: 1000.0,
            )
            trigger.write_text('{"type":"manual_fall_trigger","requestId":"ble-1"}', encoding="utf-8")

            alarm = runtime.consume_manual_trigger()

            self.assertEqual(alarm["signal"], "FALL_ALARM")
            self.assertEqual(alarm["alarmType"], "fall_detected")
            self.assertTrue(alarm["conditions"]["manual_ble_trigger"])
            self.assertEqual(len(events), 1)
            self.assertEqual(len(cloud_events), 1)
            self.assertEqual(len(call_events), 1)
            self.assertFalse(trigger.exists())
            self.assertIsNone(runtime.consume_manual_trigger())

    def test_call_failure_does_not_break_local_or_cloud_alarm_delivery(self):
        with tempfile.TemporaryDirectory() as temp:
            trigger = Path(temp) / "manual-fall.json"
            events = []
            cloud_events = []

            def fail_call(event):
                del event
                raise RuntimeError("modem unavailable")

            runtime = FallFusionRuntime(
                warning_marker=Path(temp) / "warning.json",
                alarm_sink=events.append,
                cloud_alarm_sink=cloud_events.append,
                call_alarm_sink=fail_call,
                remote_thread_factory=ImmediateThread,
                manual_trigger_path=trigger,
                wall_clock=lambda: 1000.0,
            )
            trigger.write_text('{"type":"manual_fall_trigger"}', encoding="utf-8")

            alarm = runtime.consume_manual_trigger()

            self.assertEqual(alarm["signal"], "FALL_ALARM")
            self.assertEqual(len(events), 1)
            self.assertEqual(len(cloud_events), 1)
    def test_board_units_are_converted_to_detector_units(self):
        converted = to_detector_sample(
            board_sample(2.0, ax=0.5, ay=-0.25, az=1.0, gx=1.0, gy=-0.5)
        )

        self.assertAlmostEqual(converted.ax, 0.5)
        self.assertAlmostEqual(converted.ay, -0.25)
        self.assertAlmostEqual(converted.az, 1.0)
        self.assertAlmostEqual(converted.gx, 57.2958, places=3)
        self.assertAlmostEqual(converted.gy, -28.6479, places=3)

    def test_real_imu_fall_plus_recent_warning_and_seven_seconds_still_outputs_alarm(self):
        detector_cfg = DetectorConfig(
            filter_window_samples=3,
            low_g_min_s=0.06,
            impact_window_s=0.8,
            posture_hold_s=0.18,
            stationary_hold_s=0.22,
            terminal_hold_s=9.0,
        )
        detector = FallImpactDetector(detector_cfg)
        alarms = []
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
                detector=detector,
                alarm_sink=alarms.append,
                wall_clock=lambda: clock[0],
            )

            t = 0.0
            dt = 1.0 / detector_cfg.sample_hz

            def feed(sample):
                nonlocal t
                clock[0] = 1000.0 + sample.t
                runtime.update(sample)
                t += dt

            for _ in range(20):
                feed(board_sample(t))
            for _ in range(8):
                feed(board_sample(t, az=0.18, gx=4.9))
            for _ in range(2):
                feed(board_sample(t, az=3.4, gx=7.4))
            for _ in range(420):
                feed(board_sample(t, ay=1.0, az=0.0))

        self.assertEqual(len(alarms), 1)
        self.assertEqual(alarms[0]["signal"], "FALL_ALARM")
        self.assertEqual(alarms[0]["conditions"]["no_standing_recovery_7s"], True)


if __name__ == "__main__":
    unittest.main()
