import csv
import json
import sys
import tempfile
import unittest
from collections import deque
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from alternating_camera.gateway import AlternatingCameraGateway
from alternating_camera.pipeline import ObservationGapTracker, select_latest_inference_frames
from alternating_camera.scheduler import (
    AlternatingCaptureConfig,
    AlternatingRiskScheduleConfig,
    AlternatingV4l2Capture,
    CapturedFrame,
    RiskPrioritySlicePolicy,
    percentile,
)
from alternating_camera.session import (
    ALERT_FIELDS,
    CAMERA_EVENT_FIELDS,
    PERFORMANCE_FIELDS,
    SWITCH_EVENT_FIELDS,
    AlternatingSessionRecorder,
)
from alternating_camera.v4l2_capture import NegotiatedFormat, RawMjpegFrame
from alternating_camera.vision_runtime import SharedModelAlternatingEngine, tracker_buffer_frames


class FakeClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeDevice:
    backend = "v4l2_stream_toggle"

    def __init__(
        self,
        path,
        width,
        height,
        fps,
        *,
        clock,
        shared,
        fail_starts=0,
        fail_stop_once=False,
        fail_reads=0,
    ):
        self.path = path
        self.width = width
        self.height = height
        self.fps = fps
        self.clock = clock
        self.shared = shared
        self.fail_starts = fail_starts
        self.fail_stop_once = fail_stop_once
        self.fail_reads = fail_reads
        self.start_attempts = 0
        self.streaming = False
        self.sequence = 0
        self.streamon_failures = 0
        self.streamoff_failures = 0
        self.read_failures = 0
        self.negotiated = NegotiatedFormat(width, height, "MJPG", fps, 30.0, 256000, 4)

    @property
    def is_streaming(self):
        return self.streaming

    def open(self):
        self.shared["events"].append(("open", self.path))
        return self.negotiated

    def start(self):
        self.start_attempts += 1
        self.shared["events"].append(("start", self.path))
        if self.start_attempts <= self.fail_starts:
            self.streamon_failures += 1
            raise OSError(5, "simulated STREAMON failure")
        active = [device for device in self.shared["devices"] if device.streaming]
        if active:
            raise AssertionError("simultaneous STREAMON")
        self.streaming = True
        self.clock.advance(0.010)

    def stop(self):
        self.shared["events"].append(("stop", self.path))
        if self.fail_stop_once:
            self.fail_stop_once = False
            self.streamoff_failures += 1
            raise OSError(5, "simulated STREAMOFF failure")
        self.streaming = False
        self.clock.advance(0.005)

    def read_frame(self, _timeout_s):
        if not self.streaming:
            raise AssertionError("read while stopped")
        self.clock.advance(0.030)
        if self.fail_reads > 0:
            self.fail_reads -= 1
            self.read_failures += 1
            raise OSError(19, "simulated camera disconnect")
        self.sequence += 1
        return RawMjpegFrame(
            data=b"\xff\xd8fake-jpeg\xff\xd9",
            captured_at_s=self.clock(),
            sequence=self.sequence,
            width=self.width,
            height=self.height,
        )

    def close(self):
        self.streaming = False
        self.shared["events"].append(("close", self.path))

    def enumerate_formats(self):
        return [{"pixel_format": "MJPG", "sizes": [{"width": self.width, "height": self.height, "fps": [30.0]}]}]

    def identity(self):
        return {"requested_path": self.path, "vid": "0000", "pid": "0000", "serial": "fixture"}


def build_capture(*, config=None, left_options=None, right_options=None):
    clock = FakeClock()
    shared = {"events": [], "devices": []}
    options = {"left": left_options or {}, "right": right_options or {}}

    def factory(path, width, height, fps):
        side = "left" if "left" in path else "right"
        device = FakeDevice(path, width, height, fps, clock=clock, shared=shared, **options[side])
        shared["devices"].append(device)
        return device

    capture = AlternatingV4l2Capture(
        "/dev/left-camera",
        "/dev/right-camera",
        config
        or AlternatingCaptureConfig(
            slice_ms=500,
            frames_per_slice=2,
            warmup_frames=1,
            switch_backoff_ms=1,
        ),
        device_factory=factory,
        clock=clock,
        sleep=lambda seconds: clock.advance(seconds),
    )
    return capture, clock, shared


class AlternatingCaptureTest(unittest.TestCase):
    def test_streamoff_precedes_other_side_streamon_and_only_one_is_active(self) -> None:
        capture, _clock, shared = build_capture()
        capture.open()
        left = capture.capture_slice("left")
        right = capture.capture_slice("right")

        self.assertTrue(left.event.success)
        self.assertTrue(right.event.success)
        self.assertEqual("right", capture.active_side)
        self.assertFalse(capture.devices["left"].is_streaming)
        self.assertTrue(capture.devices["right"].is_streaming)
        stop_left = shared["events"].index(("stop", "/dev/left-camera"))
        start_right = shared["events"].index(("start", "/dev/right-camera"))
        self.assertLess(stop_left, start_right)
        capture.close()
        self.assertFalse(any(device.is_streaming for device in shared["devices"]))

    def test_streamon_failure_retries_are_bounded(self) -> None:
        config = AlternatingCaptureConfig(
            frames_per_slice=1,
            warmup_frames=0,
            switch_failure_limit=3,
            switch_backoff_ms=1,
        )
        capture, _clock, _shared = build_capture(config=config, left_options={"fail_starts": 2})

        result = capture.capture_slice("left")

        self.assertTrue(result.event.success)
        self.assertEqual(3, capture.devices["left"].start_attempts)
        self.assertEqual(2, capture.streamon_failures)
        capture.close()

    def test_streamoff_after_slice_leaves_both_cameras_inactive(self) -> None:
        capture, _clock, shared = build_capture()

        result = capture.capture_slice("left", streamoff_after_slice=True)

        self.assertTrue(result.event.success)
        self.assertIsNone(capture.active_side)
        self.assertFalse(any(device.is_streaming for device in shared["devices"]))
        self.assertIsNotNone(result.event.streamoff_end_s)
        capture.close()

    def test_streamoff_failure_enters_safe_state_before_other_start(self) -> None:
        capture, _clock, shared = build_capture(left_options={"fail_stop_once": True})
        capture.capture_slice("left")

        result = capture.capture_slice("right")

        self.assertFalse(result.event.success)
        self.assertEqual("streamoff_failure", result.event.error_type)
        self.assertIn("STREAMOFF", result.event.error_message)
        self.assertIsNone(capture.active_side)
        self.assertFalse(any(device.is_streaming for device in shared["devices"]))
        self.assertNotIn(("start", "/dev/right-camera"), shared["events"])
        capture.close()

    def test_one_side_reconnects_without_blocking_the_other_camera(self) -> None:
        config = AlternatingCaptureConfig(
            frames_per_slice=1,
            warmup_frames=0,
            camera_reconnect_initial_backoff_s=0.0,
            camera_reconnect_max_backoff_s=0.0,
            tracker_reset_after_disconnect_s=0.0,
        )
        capture, _clock, _shared = build_capture(
            config=config,
            left_options={"fail_reads": 1},
        )

        failed_left = capture.capture_slice("left", streamoff_after_slice=True)
        healthy_right = capture.capture_slice("right", streamoff_after_slice=True)
        recovered_left = capture.capture_slice("left", streamoff_after_slice=True)

        self.assertFalse(failed_left.event.success)
        self.assertTrue(healthy_right.event.success)
        self.assertTrue(recovered_left.event.success)
        self.assertEqual(1, capture.side_state["left"].reconnect_count)
        self.assertEqual("ONLINE", capture.side_state["left"].connection_state)
        self.assertEqual("RECOVERED", recovered_left.event.connection_state)
        self.assertIsNotNone(recovered_left.event.disconnect_time_s)
        self.assertIsNotNone(recovered_left.event.reconnect_start_s)
        self.assertIsNotNone(recovered_left.event.reconnect_success_s)
        self.assertIsNotNone(recovered_left.event.reconnect_duration_ms)
        self.assertIsNone(recovered_left.event.offline_detect_latency_ms)
        self.assertTrue(recovered_left.event.tracker_reset)
        self.assertIsNotNone(recovered_left.event.first_recovered_frame_latency_ms)
        self.assertTrue(capture.consume_tracker_reset_required("left"))
        self.assertEqual(0, capture.side_state["right"].reconnect_count)
        capture.close()

    def test_latest_frames_and_blind_intervals_are_independent(self) -> None:
        capture, clock, _shared = build_capture()
        capture.capture_slice("left")
        left_frame = capture.latest_frame("left")
        self.assertIsNotNone(left_frame)
        self.assertIsNone(capture.latest_frame("right"))

        clock.advance(0.2)
        capture.capture_slice("right")
        status = capture.status()

        self.assertIs(left_frame, capture.latest_frame("left"))
        self.assertIsNotNone(capture.latest_frame("right"))
        self.assertGreater(status["left_last_frame_age_ms"], status["right_last_frame_age_ms"])
        self.assertEqual(2, status["switch_count"])
        capture.close()

    def test_percentile_uses_linear_interpolation(self) -> None:
        self.assertEqual(2.5, percentile([1.0, 2.0, 3.0, 4.0], 0.5))
        self.assertAlmostEqual(3.85, percentile([1.0, 2.0, 3.0, 4.0], 0.95))

    def test_risk_priority_extends_only_the_stabilized_haptic_side(self) -> None:
        policy = RiskPrioritySlicePolicy(
            AlternatingRiskScheduleConfig(
                normal_slice_ms=500,
                risk_slice_ms=700,
                minimum_other_side_slice_ms=250,
                max_blind_interval_ms=1200,
            )
        )

        policy.update_haptic_level("left", 3)

        self.assertEqual(700, policy.slice_ms_for("left"))
        self.assertEqual(250, policy.slice_ms_for("right"))

    def test_only_newest_bounded_frames_are_selected_for_inference(self) -> None:
        frames = tuple(
            CapturedFrame("left", b"x", sequence, float(sequence), float(sequence), 640, 480, "MJPG")
            for sequence in range(1, 5)
        )

        selected, skipped = select_latest_inference_frames(frames, 1)

        self.assertEqual([4], [frame.sequence for frame in selected])
        self.assertEqual(3, skipped)

    def test_observation_gap_uses_only_frames_that_enter_processing(self) -> None:
        gaps = ObservationGapTracker()
        gaps.observe("left", 1.0)
        gaps.observe("right", 1.5)
        left = gaps.observe("left", 2.2)
        summary = gaps.summary()

        self.assertAlmostEqual(1200.0, left["end_to_end_observation_gap_ms"])
        self.assertEqual(1200.0, summary["end_to_end_left_max_gap_ms"])
        self.assertEqual(500.0, summary["left_to_right_p95_latency_ms"])

    def test_observation_gap_history_is_bounded(self) -> None:
        gaps = ObservationGapTracker(history_limit=2)
        for index in range(5):
            gaps.observe("left", float(index))

        self.assertEqual(2, len(gaps.gaps_by_side["left"]))
        self.assertEqual(2, gaps.gaps_by_side["left"].maxlen)

    def test_effective_tracker_buffer_retains_time_without_unbounded_tracks(self) -> None:
        self.assertEqual(2, tracker_buffer_frames(1.0, 30))
        self.assertEqual(30, tracker_buffer_frames(30.0, 30))
        self.assertLessEqual(tracker_buffer_frames(1000.0, 300), 300)


class SessionRecorderTest(unittest.TestCase):
    def test_bounded_switch_history_keeps_exact_totals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            clock = FakeClock(10.0)
            recorder = AlternatingSessionRecorder(temporary, "bounded-session", clock=clock)
            recorder.switch_events = deque(maxlen=1)
            capture, _capture_clock, _shared = build_capture()
            first = capture.capture_slice("left").event
            second = capture.capture_slice("right").event
            capture.close()

            recorder.record_switch(first)
            recorder.record_switch(second)
            summary = recorder.finish(acceptance_min_duration_s=0.0)
            recorder.close()

            self.assertEqual(1, len(recorder.switch_events))
            self.assertEqual(2, summary["switch_count"])
            self.assertEqual(2, summary["successful_switches"])
            self.assertEqual(100.0, summary["switch_success_rate_percent"])

    def test_session_files_have_required_headers_and_summary_percentiles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            latest = root / "latest-summary.md"
            clock = FakeClock(10.0)
            recorder = AlternatingSessionRecorder(root, "fixture-session", latest_summary_path=latest, clock=clock)
            event = build_capture()[0].capture_slice("left").event
            event.switch_index = 0
            event.success = True
            event.streamon_latency_ms = 10.0
            event.streamoff_latency_ms = 5.0
            event.first_frame_latency_ms = 30.0
            event.left_blind_interval_ms = 100.0
            event.right_blind_interval_ms = 200.0
            recorder.record_switch(event)
            frame = CapturedFrame("left", b"\xff\xd8x\xff\xd9", 1, 10.1, 10.2, 640, 480, "MJPG")
            recorder.record_frame(frame, active_side="left")
            right_frame = CapturedFrame("right", b"\xff\xd8y\xff\xd9", 2, 10.15, 10.25, 640, 480, "MJPG")
            recorder.record_frame(right_frame, active_side="right")
            next_left = CapturedFrame("left", b"\xff\xd8z\xff\xd9", 3, 11.3, 11.35, 640, 480, "MJPG")
            recorder.record_frame(
                next_left,
                active_side="left",
                end_to_end_observation_gap_ms=1200.0,
                side_to_side_latency_ms=1150.0,
            )
            recorder.record_alert(
                {
                    "haptic_level": 3,
                    "event_kind": "state_change",
                    "confirmed_across_slices": True,
                }
            )
            recorder.record_alert(
                {
                    "haptic_level": 3,
                    "event_kind": "heartbeat",
                    "confirmed_across_slices": True,
                    "fast_path_reason": "must_not_be_counted_twice",
                }
            )
            recorder.record_alert(
                {
                    "haptic_level": 0,
                    "event_kind": "state_change",
                    "clear_reason": "stale_observation",
                }
            )
            clock.advance(2.0)
            recorder.record_performance({"active_camera": "left", "switch_count": 1})
            summary = recorder.finish(
                acceptance_min_duration_s=0.0,
                acceptance_max_blind_interval_ms=1200.0,
            )
            recorder.close()

            session = root / "fixture-session"
            self.assertTrue((session / "session.json").is_file())
            self.assertTrue((session / "summary.json").is_file())
            self.assertTrue(latest.is_file())
            self.assertEqual(15.0, summary["switch_latency_ms"]["p95"])
            self.assertEqual(30.0, summary["first_frame_latency_ms"]["p99"])
            self.assertTrue(summary["acceptance_met"])
            self.assertEqual("end_to_end_observation_gap_ms", summary["acceptance_gap_metric"])
            self.assertEqual(1200.0, summary["end_to_end_max_gap_ms"])
            self.assertEqual(1, summary["dropped_frames"])
            self.assertEqual(2, summary["state_change_count"])
            self.assertEqual(1, summary["heartbeat_count"])
            self.assertEqual(1, summary["stale_clear_count"])
            self.assertEqual(1, summary["cross_slice_confirmed_count"])
            self.assertEqual(0, summary["emergency_fast_path_count"])
            self.assertIsNone(summary["camera_offline_clear_verified"])
            for filename, expected in (
                ("switch-events.csv", SWITCH_EVENT_FIELDS),
                ("camera-events.csv", CAMERA_EVENT_FIELDS),
                ("performance.csv", PERFORMANCE_FIELDS),
                ("alerts.csv", ALERT_FIELDS),
            ):
                with (session / filename).open(encoding="utf-8", newline="") as handle:
                    header = next(csv.reader(handle))
                self.assertEqual(list(expected), header)
            metadata = json.loads((session / "session.json").read_text(encoding="utf-8"))
            self.assertEqual("fixture-session", metadata["session_id"])
            self.assertNotIn("password", json.dumps(metadata).lower())


class SharedModelRuntimeTest(unittest.TestCase):
    def test_model_loads_once_and_side_contexts_do_not_share_history(self) -> None:
        model_loads = []

        class FakeModel:
            names = {0: "car"}

            def predict(self, image, **_kwargs):
                return [f"detections:{image}"]

        class FakeContext:
            def __init__(self, side):
                self.side = side
                self.history = []
                self.tracker = object()
                self.calibration = object()
                self.stable_track_ids = object()
                self.track_state = object()
                self.risk_model = object()
                self.risk_stabilizer = object()
                self.self_object_filter = object()
                self.risk_logger = object()

            def process_detection(self, result, _image, timestamp_s, **_context):
                self.history.append((result, timestamp_s))
                return (self.side, len(self.history))

        def load_model(path):
            model_loads.append(path)
            return FakeModel()

        engine = SharedModelAlternatingEngine(
            "fixture.pt",
            FakeContext,
            model_factory=load_model,
        )

        self.assertEqual(("left", 1), engine.process("left", "L1", 1.0))
        self.assertEqual(("right", 1), engine.process("right", "R1", 2.0))
        self.assertEqual(("left", 2), engine.process("left", "L2", 3.0))
        self.assertEqual(["fixture.pt"], model_loads)
        self.assertIsNot(engine.contexts["left"], engine.contexts["right"])
        self.assertEqual(2, len(engine.contexts["left"].history))
        self.assertEqual(1, len(engine.contexts["right"].history))
        for attribute in (
            "tracker",
            "calibration",
            "stable_track_ids",
            "track_state",
            "risk_model",
            "risk_stabilizer",
            "self_object_filter",
            "risk_logger",
        ):
            self.assertIsNot(
                getattr(engine.contexts["left"], attribute),
                getattr(engine.contexts["right"], attribute),
            )

    def test_shared_mutable_side_state_is_rejected(self) -> None:
        shared_tracker = object()

        class FakeModel:
            def predict(self, image, **_kwargs):
                return [image]

        class BadContext:
            def __init__(self, side):
                self.side = side
                self.tracker = shared_tracker

            def process_detection(self, result, _image, _timestamp_s, **_context):
                return result

        with self.assertRaisesRegex(ValueError, "share mutable state: tracker"):
            SharedModelAlternatingEngine(
                "fixture.pt",
                BadContext,
                model_factory=lambda _path: FakeModel(),
            )


class GatewayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.capture, _clock, _shared = build_capture()
        self.capture.capture_slice("left")
        self.gateway = AlternatingCameraGateway(self.capture, bind="127.0.0.1", port=0)
        self.gateway.start()
        self.base = f"http://127.0.0.1:{self.gateway.port}"

    def tearDown(self) -> None:
        self.gateway.stop()
        self.capture.close()

    def test_status_marks_inactive_side_as_cached_or_offline(self) -> None:
        with urlopen(self.base + "/api/v1/status", timeout=2.0) as response:
            payload = json.loads(response.read())

        cameras = {camera["side"]: camera for camera in payload["cameras"]}
        self.assertEqual("live", cameras["left"]["frame_state"])
        self.assertEqual("offline", cameras["right"]["frame_state"])

    def test_snapshot_uses_cached_mjpeg_and_gateway_never_reopens_camera(self) -> None:
        starts_before = self.capture.devices["left"].start_attempts
        with urlopen(self.base + "/api/v1/camera/left/snapshot.jpg", timeout=2.0) as response:
            data = response.read()
        self.assertTrue(data.startswith(b"\xff\xd8"))
        self.assertEqual(starts_before, self.capture.devices["left"].start_attempts)
        with self.assertRaises(HTTPError) as context:
            urlopen(self.base + "/api/v1/camera/right/snapshot.jpg", timeout=2.0)
        self.assertEqual(503, context.exception.code)

    def test_raw_and_overlay_views_are_distinct_cached_frames(self) -> None:
        frame = self.capture.latest_frame("left")
        self.assertIsNotNone(frame)
        overlay = b"\xff\xd8overlay-jpeg\xff\xd9"
        self.gateway.publish_overlay(
            "left",
            overlay,
            sequence=frame.sequence,
            captured_at_s=frame.captured_at_s,
            metadata={"risk_name": "CAUTION", "slice_id": 7},
        )

        with urlopen(self.base + "/api/v1/camera/left/snapshot.jpg?view=raw", timeout=2.0) as response:
            raw = response.read()
        with urlopen(self.base + "/api/v1/camera/left/snapshot.jpg?view=overlay", timeout=2.0) as response:
            rendered = response.read()
        with urlopen(self.base + "/api/v1/camera/left/status", timeout=2.0) as response:
            status = json.loads(response.read())

        self.assertNotEqual(raw, rendered)
        self.assertEqual(overlay, rendered)
        self.assertTrue(status["raw_available"])
        self.assertTrue(status["overlay_available"])
        self.assertEqual("CAUTION", status["risk_name"])


if __name__ == "__main__":
    unittest.main()
