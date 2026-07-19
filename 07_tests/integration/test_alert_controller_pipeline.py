import io
import queue
import sys
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = ROOT / "06_software" / "board_runtime" / "smartbag_alert_controller"
if str(CONTROLLER) not in sys.path:
    sys.path.insert(0, str(CONTROLLER))

from alert_core import AlertEvent, AlertState, event_is_stale, parse_vision_alert_jsonl
from smartbag_alert_controller import (
    DetectorProcess,
    alternating_detector_command_from_config,
    alert_event_ble_payload,
    detector_commands_from_config,
    should_publish_alert_history,
    validate_dual_camera_config,
)


class AlertControllerPipelineTest(unittest.TestCase):
    def test_level_zero_clears_vibration(self) -> None:
        state = AlertState(event_timeout_s=1.0)
        active = state.apply_event(AlertEvent("left", 3), now=1.0)
        cleared = state.apply_event(AlertEvent("left", 0), now=1.1)

        self.assertGreater(active.duties_ns["left_1"], 0)
        self.assertEqual(0, cleared.duties_ns["left_1"])
        self.assertEqual(0, cleared.duties_ns["left_2"])

    def test_stale_event_is_rejected_by_age_gate(self) -> None:
        self.assertTrue(event_is_stale(AlertEvent("right", 4, ts=1.0), now_s=4.0, max_age_s=2.0))
        self.assertFalse(event_is_stale(AlertEvent("right", 4, ts=3.0), now_s=4.0, max_age_s=2.0))

    def test_malformed_and_out_of_range_events_are_rejected(self) -> None:
        with self.assertRaises(Exception):
            parse_vision_alert_jsonl("not-json")
        with self.assertRaises(ValueError):
            parse_vision_alert_jsonl('{"type":"vision_alert","side":"left","level":5}')

    def test_detector_exit_queues_clear_for_its_side(self) -> None:
        event_queue = queue.Queue()
        detector = DetectorProcess("left", "unused", event_queue)

        class FakeProcess:
            stdout = io.StringIO('{"type":"vision_alert","side":"left","level":2,"ts":1}\n')

        detector.process = FakeProcess()
        detector._reader()

        self.assertEqual(2, event_queue.get_nowait().level)
        clear = event_queue.get_nowait()
        self.assertEqual("left", clear.side)
        self.assertEqual(0, clear.level)
        self.assertLessEqual(clear.ts, time.monotonic())

    def test_right_detector_exit_queues_only_right_clear(self) -> None:
        event_queue = queue.Queue()
        detector = DetectorProcess("right", "unused", event_queue)

        class FakeProcess:
            stdout = io.StringIO("")

        detector.process = FakeProcess()
        detector._reader()

        clear = event_queue.get_nowait()
        self.assertEqual(("right", 0), (clear.side, clear.level))
        self.assertTrue(event_queue.empty())

    def test_clearing_left_side_preserves_active_right_side(self) -> None:
        state = AlertState(event_timeout_s=1.0)
        state.apply_event(AlertEvent("left", 2), now=1.0)
        state.apply_event(AlertEvent("right", 3), now=1.0)

        output = state.apply_event(AlertEvent("left", 0), now=1.1)

        self.assertEqual(0, output.duties_ns["left_1"])
        self.assertEqual(0, output.duties_ns["left_2"])
        self.assertGreater(output.duties_ns["right_1"], 0)
        self.assertGreater(output.duties_ns["right_2"], 0)

    def test_single_camera_detector_exit_clears_both_sides(self) -> None:
        event_queue = queue.Queue()
        detector = DetectorProcess(None, "unused", event_queue)

        class FakeProcess:
            stdout = io.StringIO("")

        detector.process = FakeProcess()
        detector._reader()

        clears = [event_queue.get_nowait(), event_queue.get_nowait()]
        self.assertEqual({"left", "right"}, {event.side for event in clears})
        self.assertTrue(all(event.level == 0 for event in clears))

    def test_fixed_side_detector_rejects_cross_side_events(self) -> None:
        event_queue = queue.Queue()
        detector = DetectorProcess("left", "unused", event_queue)

        class FakeProcess:
            stdout = io.StringIO('{"type":"vision_alert","side":"right","level":3,"ts":1}\n')

            @staticmethod
            def poll():
                return 1

        detector.process = FakeProcess()
        detector._reader()

        clear = event_queue.get_nowait()
        self.assertEqual(("left", 0), (clear.side, clear.level))
        self.assertTrue(event_queue.empty())

    def test_dual_config_rejects_same_camera_device(self) -> None:
        config = {
            "cameras": {
                "left": {"camera_device": "/dev/video0", "stream_port": 18081},
                "right": {"camera_device": "/dev/video0", "stream_port": 18082},
            }
        }
        with self.assertRaisesRegex(ValueError, "must be different"):
            validate_dual_camera_config(config)

    def test_configured_detector_commands_are_fixed_side_and_independent(self) -> None:
        config = {
            "paths": {"python": "python3", "vision": "/vision", "model": "/models/yolo.pt"},
            "cameras": {
                "left": {"camera_device": "/dev/video0", "stream_port": 18081},
                "right": {"camera_device": "/dev/video2", "stream_port": 18082},
            },
        }

        left, right = detector_commands_from_config(config)

        self.assertIn("--camera-device /dev/video0", left)
        self.assertIn("--side left", left)
        self.assertIn("--alert-min-level 1", left)
        self.assertIn("--camera-reconnect-attempts 5", left)
        self.assertNotIn("--side right", left)
        self.assertIn("--camera-device /dev/video2", right)
        self.assertIn("--side right", right)
        self.assertNotIn("--side left", right)

    def test_alternating_mode_builds_one_complete_detector_command(self) -> None:
        config = {
            "paths": {"python": "python3", "vision": "/vision", "model": "/models/yolo.pt"},
            "vision_runtime": {"mode": "alternating_single_model"},
            "alternating_camera": {"enabled": True, "normal_slice_ms": 500},
            "cameras": {
                "left": {
                    "camera_device": "/dev/v4l/by-path/left",
                    "calibration_file": "/etc/smartbag/left.json",
                    "stream_port": 18081,
                },
                "right": {
                    "camera_device": "/dev/v4l/by-path/right",
                    "calibration_file": "/etc/smartbag/right.json",
                    "stream_port": 18082,
                },
            },
        }

        command = alternating_detector_command_from_config(config)

        self.assertIn("alternating_dual_camera_tracker.py", command)
        self.assertIn("--left-device /dev/v4l/by-path/left", command)
        self.assertIn("--right-device /dev/v4l/by-path/right", command)
        self.assertIn("--backend v4l2_stream_toggle", command)
        self.assertIn("--left-calibration-file /etc/smartbag/left.json", command)
        self.assertIn("--right-calibration-file /etc/smartbag/right.json", command)
        self.assertNotIn("--side", command)

    def test_alternating_config_can_disable_risk_priority(self) -> None:
        config = {
            "paths": {"python": "python3", "vision": "/vision", "model": "/models/yolo.pt"},
            "vision_runtime": {"mode": "alternating_single_model"},
            "alternating_camera": {"enabled": True, "risk_priority_enabled": False},
            "cameras": {
                "left": {"camera_device": "/dev/v4l/by-path/left"},
                "right": {"camera_device": "/dev/v4l/by-path/right"},
            },
        }

        self.assertIn("--disable-risk-priority", alternating_detector_command_from_config(config))

    def test_heartbeat_is_not_mobile_history_but_state_change_is(self) -> None:
        self.assertFalse(should_publish_alert_history(AlertEvent("left", 2, event_kind="heartbeat")))
        self.assertTrue(should_publish_alert_history(AlertEvent("left", 2, event_kind="state_change")))

    def test_ble_alert_payload_keeps_optional_target_context(self) -> None:
        payload = alert_event_ble_payload(
            AlertEvent("right", 3, score=0.78, track_id=123, ts=12.3, class_name="car", distance_m=4.2)
        )
        self.assertIn('"typ":"alert"', payload)
        self.assertIn('"name":"DANGER"', payload)
        self.assertIn('"class":"car"', payload)
        self.assertIn('"distance_m":4.2', payload)


if __name__ == "__main__":
    unittest.main()
