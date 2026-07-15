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
from smartbag_alert_controller import DetectorProcess


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


if __name__ == "__main__":
    unittest.main()
