from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

BOARD_RUNTIME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BOARD_RUNTIME))

from radar_vision_fusion.alternating_snapshot_classifier import (  # noqa: E402
    AlternatingSnapshotClassifier,
    SnapshotCameraConfig,
    SnapshotClassifierConfig,
    default_snapshot_camera_factory,
)
from radar_vision_fusion.v4l2_snapshot_camera import NativeV4L2SnapshotCamera  # noqa: E402


class FakeFrame:
    shape = (480, 640, 3)

    def __init__(self, token: int = 0) -> None:
        self.token = token


class FakeCamera:
    active = 0
    maximum_active = 0
    fail_side = ""
    raise_side = ""
    open_attempts = 0

    def __init__(self, config) -> None:
        self.config = config
        self.read_count = 0

    def open(self) -> bool:
        FakeCamera.open_attempts += 1
        if self.config.side == self.raise_side:
            raise OSError("camera transport failed")
        if self.config.side == self.fail_side:
            return False
        FakeCamera.active += 1
        FakeCamera.maximum_active = max(FakeCamera.maximum_active, FakeCamera.active)
        return True

    def read(self, _timeout_s):
        self.read_count += 1
        return True, FakeFrame(self.read_count)

    def close(self) -> None:
        if FakeCamera.active:
            FakeCamera.active -= 1


class FakeBackend:
    instances = 0

    def __init__(self) -> None:
        FakeBackend.instances += 1
        self.names = {2: "car"}
        self.calls = 0
        self.fail_next = False

    def detect(self, _frame, **_kwargs):
        self.calls += 1
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("model failed")
        return {"type": "detections", "detections": [{"class_id": 2, "class_name": "car", "confidence": 0.9, "bbox": [10, 20, 100, 200]}]}

    def track(self, *_args, **_kwargs):
        raise AssertionError("snapshot classification must not call tracker")

    def close(self) -> None:
        return None


class PersistentFakeCamera:
    active = 0
    maximum_active = 0
    prepare_count = 0

    def __init__(self, config) -> None:
        self.config = config
        self.read_count = 0
        self.streaming = False

    def prepare(self) -> None:
        PersistentFakeCamera.prepare_count += 1

    def stream_on(self) -> None:
        if self.streaming:
            raise AssertionError("camera streamed twice")
        self.streaming = True
        PersistentFakeCamera.active += 1
        PersistentFakeCamera.maximum_active = max(PersistentFakeCamera.maximum_active, PersistentFakeCamera.active)

    def read(self, _timeout_s):
        self.read_count += 1
        return True, FakeFrame(self.read_count)

    def stream_off(self) -> None:
        if self.streaming:
            self.streaming = False
            PersistentFakeCamera.active -= 1

    def close(self) -> None:
        self.stream_off()


class SnapshotClassifierTest(unittest.TestCase):
    def test_linux_by_path_device_uses_native_v4l2_backend(self) -> None:
        config = SnapshotCameraConfig("left", "/dev/v4l/by-path/usb-camera-video-index0")
        with mock.patch("radar_vision_fusion.alternating_snapshot_classifier.os.name", "posix"):
            camera = default_snapshot_camera_factory(config)
        self.assertIsInstance(camera, NativeV4L2SnapshotCamera)

    def setUp(self) -> None:
        FakeCamera.active = 0
        FakeCamera.maximum_active = 0
        FakeCamera.fail_side = ""
        FakeCamera.raise_side = ""
        FakeCamera.open_attempts = 0
        FakeBackend.instances = 0
        self.backend = FakeBackend()
        self.classifier = AlternatingSnapshotClassifier(
            self.backend,
            [SnapshotCameraConfig("left", "left"), SnapshotCameraConfig("right", "right")],
            SnapshotClassifierConfig(),
            camera_factory=FakeCamera,
        )

    def test_cameras_are_streamed_one_at_a_time_and_model_is_shared(self) -> None:
        left = self.classifier.run_once("left")
        right = self.classifier.run_once("right")
        self.assertEqual(1, FakeCamera.maximum_active)
        self.assertEqual(1, FakeBackend.instances)
        self.assertEqual(2, self.backend.calls)
        self.assertEqual("car", left.detections[0].class_name)
        self.assertEqual("car", right.detections[0].class_name)

    def test_one_camera_offline_does_not_block_other_side(self) -> None:
        FakeCamera.fail_side = "left"
        left = self.classifier.run_once("left")
        right = self.classifier.run_once("right")
        self.assertEqual("OFFLINE", left.camera_state)
        self.assertEqual("LIVE", right.camera_state)
        self.assertEqual(1, self.backend.calls)

    def test_failed_capture_is_not_counted_as_snapshot_fps(self) -> None:
        FakeCamera.fail_side = "left"
        self.classifier.run_once("left")
        status = self.classifier.status()
        self.assertEqual(0.0, status["sides"]["left"]["snapshot_fps"])

    def test_only_latest_warmup_capture_is_retained(self) -> None:
        output = self.classifier.run_once("left")
        self.assertEqual(3, output.image.token)
        self.assertIs(output, self.classifier.latest("left"))

    def test_model_failure_does_not_stop_next_side_or_call_tracker(self) -> None:
        self.backend.fail_next = True
        left = self.classifier.run_once("left")
        right = self.classifier.run_once("right")
        self.assertEqual("MODEL_ERROR", left.camera_state)
        self.assertEqual("LIVE", right.camera_state)
        self.assertEqual(2, self.backend.calls)

    def test_camera_exception_on_one_side_does_not_block_other(self) -> None:
        FakeCamera.raise_side = "left"
        left = self.classifier.run_once("left")
        right = self.classifier.run_once("right")
        self.assertEqual("OFFLINE", left.camera_state)
        self.assertEqual("LIVE", right.camera_state)

    def test_native_style_cameras_are_prepared_once_and_never_stream_together(self) -> None:
        PersistentFakeCamera.active = 0
        PersistentFakeCamera.maximum_active = 0
        PersistentFakeCamera.prepare_count = 0
        classifier = AlternatingSnapshotClassifier(
            self.backend,
            [SnapshotCameraConfig("left", "left"), SnapshotCameraConfig("right", "right")],
            SnapshotClassifierConfig(initial_warmup_frames=0, switch_warmup_frames=0),
            camera_factory=PersistentFakeCamera,
        )
        classifier._prepare_cameras()
        classifier.run_once("left")
        classifier.run_once("right")
        classifier.run_once("left")
        self.assertEqual(2, PersistentFakeCamera.prepare_count)
        self.assertEqual(1, PersistentFakeCamera.maximum_active)
        self.assertEqual(2, len(classifier._camera_instances))
        classifier.stop()

    def test_target_scheduler_records_intervals_without_backlog(self) -> None:
        PersistentFakeCamera.active = 0
        PersistentFakeCamera.maximum_active = 0
        classifier = AlternatingSnapshotClassifier(
            self.backend,
            [SnapshotCameraConfig("left", "left"), SnapshotCameraConfig("right", "right")],
            SnapshotClassifierConfig(
                target_switch_interval_s=0.02,
                initial_warmup_frames=0,
                switch_warmup_frames=0,
            ),
            camera_factory=PersistentFakeCamera,
        )
        classifier.start()
        import time
        time.sleep(0.13)
        classifier.stop()
        status = classifier.status()
        self.assertGreaterEqual(status["metrics"]["switch_interval_ms"]["count"], 3)
        self.assertEqual(1, PersistentFakeCamera.maximum_active)

    def test_two_offline_cameras_do_not_busy_spin_during_backoff(self) -> None:
        import time

        FakeCamera.fail_side = "left"
        FakeCamera.raise_side = "right"
        classifier = AlternatingSnapshotClassifier(
            self.backend,
            [SnapshotCameraConfig("left", "left"), SnapshotCameraConfig("right", "right")],
            SnapshotClassifierConfig(target_switch_interval_s=0.0, camera_reset_backoff_s=1.0),
            camera_factory=FakeCamera,
        )
        classifier.start()
        time.sleep(0.08)
        classifier.stop()
        self.assertLessEqual(FakeCamera.open_attempts, 4)

    def test_stop_does_not_close_camera_while_scheduler_is_still_running(self) -> None:
        classifier = AlternatingSnapshotClassifier(
            self.backend,
            [SnapshotCameraConfig("left", "left")],
            SnapshotClassifierConfig(capture_timeout_ms=1000, streamoff_timeout_ms=1000),
            camera_factory=PersistentFakeCamera,
        )
        fake_thread = mock.Mock()
        fake_thread.is_alive.return_value = True
        classifier._thread = fake_thread
        camera = mock.Mock()
        classifier._camera_instances["left"] = camera

        classifier.stop()

        fake_thread.join.assert_called_once_with(timeout=3.0)
        camera.close.assert_not_called()
        self.assertIn("scheduler", classifier.status()["errors"])


if __name__ == "__main__":
    unittest.main()
