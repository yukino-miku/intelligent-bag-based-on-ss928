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
    alert_event_ble_payload,
    detector_commands_from_config,
    posture_reminder_from_module,
    validate_dual_camera_config,
    validate_snapshot_camera_config,
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

    def test_fused_alert_parser_keeps_string_track_and_kinematics(self) -> None:
        event = parse_vision_alert_jsonl(
            '{"type":"fused_alert","side":"right","level":2,'
            '"track_id":"right_rear:7:2","radar_target_id":7,'
            '"class":"car","class_weight":1.0,"speed_mps":3.2,'
            '"ttc_s":2.5,"association_state":"BOUND","event_kind":"heartbeat"}'
        )
        self.assertEqual("right_rear:7:2", event.track_id)
        self.assertEqual(3.2, event.speed_mps)
        self.assertEqual("heartbeat", event.event_kind)

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

    def test_clearing_one_source_preserves_other_source_on_same_side(self) -> None:
        state = AlertState(event_timeout_s=1.0)
        state.apply_event(AlertEvent("left", 3, source="vision:left"), now=1.0)
        state.apply_event(AlertEvent("left", 2, source="radar:left_rear"), now=1.0)

        output = state.apply_event(AlertEvent("left", 0, source="vision:left"), now=1.1)

        self.assertEqual(2, output.levels["left"])
        self.assertGreater(output.duties_ns["left_1"], 0)
        cleared = state.apply_event(AlertEvent("left", 0, source="radar:left_rear"), now=1.2)
        self.assertEqual(0, cleared.levels["left"])

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

    def test_fusion_camera_validation_uses_snapshot_devices_not_stream_ports(self) -> None:
        config = {
            "snapshot_classifier": {
                "enabled": True,
                "left_device": "/dev/v4l/by-path/left",
                "right_device": "/dev/v4l/by-path/right",
            }
        }
        validate_snapshot_camera_config(config)
        config["snapshot_classifier"]["right_device"] = "/dev/v4l/by-path/left"
        with self.assertRaisesRegex(ValueError, "must be different"):
            validate_snapshot_camera_config(config)

    def test_ble_alert_payload_keeps_optional_target_context(self) -> None:
        payload = alert_event_ble_payload(
            AlertEvent(
                "right",
                3,
                score=0.78,
                track_id="right_rear:12:3",
                ts=12.3,
                class_name="truck",
                distance_m=4.2,
                radar_name="right_rear",
                radar_target_id=12,
                radar_track_key="right_rear:12:3",
                class_confidence=0.91,
                class_weight=1.1,
                class_source="vision_bound",
                lateral_distance_m=0.8,
                longitudinal_distance_m=4.1,
                vx_mps=-0.2,
                vz_mps=-2.0,
                speed_mps=2.01,
                ttc_s=2.1,
                association_state="BOUND",
                association_score=0.12,
                event_kind="alert",
            )
        )
        self.assertIn('"typ":"alert"', payload)
        self.assertIn('"name":"DANGER"', payload)
        self.assertIn('"class":"truck"', payload)
        self.assertIn('"distance_m":4.2', payload)
        self.assertIn('"radar_track_key":"right_rear:12:3"', payload)
        self.assertIn('"class_weight":1.1', payload)
        self.assertIn('"speed_mps":2.01', payload)
        self.assertIn('"ttc_s":2.1', payload)
        self.assertIn('"association_state":"BOUND"', payload)

    def test_hunch_reminder_uses_independent_bilateral_source(self) -> None:
        parsed = posture_reminder_from_module(
            "IMU",
            "REMINDER,HUNCH,level=light,duration=5",
            {"posture_reminder": {"enabled": True, "level": 1, "duration_s": 5, "audio_clip": "bad"}},
            now_s=10.0,
        )
        self.assertIsNotNone(parsed)
        events, clip = parsed
        self.assertEqual("bad", clip)
        self.assertEqual({"left", "right"}, {event.side for event in events})
        self.assertTrue(all(event.source == "posture:hunch" for event in events))

        state = AlertState(event_timeout_s=1.0)
        state.apply_event(AlertEvent("left", 3, source="vision:left"), now=10.0)
        output = state.apply_event(events[0], now=10.0)
        output = state.apply_event(events[1], now=10.0)
        self.assertEqual(3, output.levels["left"])
        self.assertEqual(1, output.levels["right"])
        cleared = state.apply_event(AlertEvent("left", 0, source="vision:left"), now=10.1)
        self.assertEqual(1, cleared.levels["left"])


if __name__ == "__main__":
    unittest.main()
