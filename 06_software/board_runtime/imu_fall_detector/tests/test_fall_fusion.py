import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from fall_fusion import (  # noqa: E402
    FallFusionConfig,
    FallFusionGate,
    read_recent_warning,
    write_high_warning_marker,
)


def fall_event(t=20.0):
    return {
        "type": "imu_fall_event",
        "event": "fall_confirmed",
        "state": "FALL_CONFIRMED",
        "t": t,
        "metrics": {"posture_delta_deg": 82.0, "accel_g": 1.0, "gyro_dps": 1.0},
    }


def warning(ts=1000.0, level=3, source="vision"):
    return {"type": "high_warning", "source": source, "side": "right", "level": level, "ts": ts}


class WarningMarkerTests(unittest.TestCase):
    def test_marker_only_accepts_camera_or_radar_level_three_or_four(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "warning.json"

            self.assertFalse(write_high_warning_marker(path, warning(level=2)))
            self.assertFalse(write_high_warning_marker(path, warning(level=4, source="manual")))
            self.assertFalse(path.exists())

            self.assertTrue(write_high_warning_marker(path, warning(level=4, source="radar:right_rear")))
            recent = read_recent_warning(path, now_wall=1008.0, window_s=10.0)

            self.assertEqual(recent["level"], 4)
            self.assertEqual(recent["source"], "radar:right_rear")

    def test_stale_or_invalid_marker_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "warning.json"
            path.write_text(json.dumps(warning(ts=1000.0)), encoding="utf-8")
            self.assertIsNone(read_recent_warning(path, now_wall=1010.01, window_s=10.0))

            path.write_text("not json", encoding="utf-8")
            self.assertIsNone(read_recent_warning(path, now_wall=1001.0, window_s=10.0))


class FallFusionGateTests(unittest.TestCase):
    def setUp(self):
        self.cfg = FallFusionConfig(
            warning_window_s=10.0,
            recovery_window_s=7.0,
            standing_posture_deg=25.0,
            standing_hold_s=1.0,
        )

    def test_missing_or_stale_warning_never_arms_fall_alarm(self):
        gate = FallFusionGate(self.cfg)
        self.assertFalse(gate.start(fall_event(), None, now_mono=20.0, now_wall=1000.0))
        self.assertFalse(gate.start(fall_event(), warning(ts=989.9), now_mono=20.0, now_wall=1000.0))
        self.assertIsNone(gate.update_motion(80.0, now_mono=30.0, now_wall=1010.0))

    def test_standing_up_within_seven_seconds_cancels_alarm(self):
        gate = FallFusionGate(self.cfg)
        self.assertTrue(gate.start(fall_event(), warning(ts=995.0), now_mono=20.0, now_wall=1000.0))

        self.assertIsNone(gate.update_motion(18.0, now_mono=24.0, now_wall=1004.0))
        self.assertIsNone(gate.update_motion(16.0, now_mono=25.1, now_wall=1005.1))
        self.assertFalse(gate.pending)
        self.assertIsNone(gate.update_motion(80.0, now_mono=28.0, now_wall=1008.0))

    def test_no_standing_motion_for_seven_seconds_outputs_one_json_alarm(self):
        gate = FallFusionGate(self.cfg)
        self.assertTrue(gate.start(fall_event(), warning(ts=995.0, level=4), now_mono=20.0, now_wall=1000.0))

        self.assertIsNone(gate.update_motion(78.0, now_mono=26.9, now_wall=1006.9))
        alarm = gate.update_motion(80.0, now_mono=27.0, now_wall=1007.0)

        self.assertEqual(alarm["type"], "fall_alarm")
        self.assertEqual(alarm["alarmType"], "fall_detected")
        self.assertEqual(alarm["signal"], "FALL_ALARM")
        self.assertEqual(
            alarm["conditions"],
            {
                "imu_fall_confirmed": True,
                "recent_level_3_or_4_warning": True,
                "no_standing_recovery_7s": True,
            },
        )
        self.assertEqual(alarm["evidence"]["warning"]["level"], 4)
        self.assertFalse(gate.pending)
        self.assertIsNone(gate.update_motion(80.0, now_mono=28.0, now_wall=1008.0))


if __name__ == "__main__":
    unittest.main()
