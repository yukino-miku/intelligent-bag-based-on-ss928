import json
import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from imu_fall_detector import (  # noqa: E402
    DetectorConfig,
    FallImpactDetector,
    ImuSample,
    State,
    event_to_json,
)


def sample(t, ax=0.0, ay=0.0, az=1.0, gx=0.0, gy=0.0, gz=0.0):
    return ImuSample(t=t, ax=ax, ay=ay, az=az, gx=gx, gy=gy, gz=gz)


class FallImpactDetectorTests(unittest.TestCase):
    def test_freefall_impact_posture_and_stillness_confirm_a_fall(self):
        cfg = DetectorConfig(
            filter_window_samples=3,
            low_g_min_s=0.06,
            impact_window_s=0.8,
            posture_hold_s=0.18,
            stationary_hold_s=0.22,
            terminal_hold_s=10.0,
        )
        detector = FallImpactDetector(cfg)
        events = []
        t = 0.0
        dt = 1.0 / cfg.sample_hz

        for _ in range(20):
            events.extend(detector.update(sample(t)))
            t += dt
        for _ in range(8):
            events.extend(detector.update(sample(t, az=0.18, gx=280.0)))
            t += dt
        for _ in range(2):
            events.extend(detector.update(sample(t, az=3.4, gx=420.0)))
            t += dt
        for _ in range(30):
            events.extend(detector.update(sample(t, ay=1.0, az=0.0)))
            t += dt

        states = [event["state"] for event in events]
        self.assertEqual(
            states,
            [
                State.POSSIBLE_FALL.value,
                State.IMPACT.value,
                State.POSTURE_CHANGED.value,
                State.FALL_CONFIRMED.value,
            ],
        )
        self.assertEqual(events[-1]["event"], "fall_confirmed")
        self.assertGreaterEqual(events[-1]["metrics"]["posture_delta_deg"], 70.0)
        self.assertIs(events[-1]["metrics"]["stationary"], True)
        self.assertIs(detector.state, State.FALL_CONFIRMED)

    def test_direct_impact_without_posture_change_becomes_impact_only(self):
        cfg = DetectorConfig(
            filter_window_samples=1,
            impact_only_timeout_s=0.35,
            terminal_hold_s=10.0,
        )
        detector = FallImpactDetector(cfg)
        events = []
        t = 0.0
        dt = 1.0 / cfg.sample_hz

        for _ in range(10):
            events.extend(detector.update(sample(t)))
            t += dt
        events.extend(detector.update(sample(t, az=3.3, gx=40.0)))
        t += dt
        for _ in range(24):
            events.extend(detector.update(sample(t)))
            t += dt

        states = [event["state"] for event in events]
        self.assertEqual(states, [State.IMPACT.value, State.IMPACT_ONLY.value])
        self.assertEqual(events[-1]["event"], "impact_only")
        self.assertIs(detector.state, State.IMPACT_ONLY)

    def test_sliding_window_metrics_include_jerk_stationary_and_posture(self):
        cfg = DetectorConfig(
            filter_window_samples=5,
            stationary_hold_s=0.18,
        )
        detector = FallImpactDetector(cfg)
        t = 0.0
        dt = 1.0 / cfg.sample_hz

        for i in range(18):
            az = 1.0 + (0.02 if i % 2 == 0 else -0.02)
            detector.update(sample(t, ax=0.01, ay=-0.01, az=az, gx=0.5, gy=-0.5))
            t += dt

        features = detector.last_features
        self.assertLess(abs(features["accel_g"] - 1.0), 0.03)
        self.assertLess(features["gyro_dps"], 2.0)
        self.assertGreaterEqual(features["jerk_gps"], 0.0)
        self.assertIs(features["stationary"], True)
        self.assertLess(abs(features["roll_deg"]), 2.0)
        self.assertLess(abs(features["pitch_deg"]), 2.0)

    def test_event_to_json_is_compact_and_parseable_for_linux_integration(self):
        detector = FallImpactDetector(
            DetectorConfig(filter_window_samples=1, impact_only_timeout_s=0.1)
        )
        events = []
        t = 0.0
        dt = 1.0 / detector.config.sample_hz

        detector.update(sample(t))
        t += dt
        events.extend(detector.update(sample(t, az=3.5)))

        payload = event_to_json(events[0])
        decoded = json.loads(payload)
        self.assertNotIn("\n", payload)
        self.assertEqual(decoded["type"], "imu_fall_event")
        self.assertEqual(decoded["state"], State.IMPACT.value)
        self.assertEqual(decoded["sample_hz"], 50.0)
        self.assertEqual(decoded["sample"]["accel_unit"], "g")
        self.assertEqual(decoded["sample"]["gyro_unit"], "deg/s")
        self.assertIn("metrics", decoded)


if __name__ == "__main__":
    unittest.main()
