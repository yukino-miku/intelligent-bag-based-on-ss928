from __future__ import annotations

import sys
import unittest
from pathlib import Path

BOARD_RUNTIME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BOARD_RUNTIME))

from radar_vision_fusion.alternating_snapshot_classifier import (  # noqa: E402
    AlternatingSnapshotClassifier,
    SnapshotCameraConfig,
    SnapshotClassifierConfig,
)


class FakeFrame:
    shape = (480, 640, 3)

    def __init__(self, token: int = 0) -> None:
        self.token = token


class FakeCamera:
    active = 0
    maximum_active = 0
    fail_side = ""
    raise_side = ""

    def __init__(self, config) -> None:
        self.config = config
        self.read_count = 0

    def open(self) -> bool:
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


class SnapshotClassifierTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeCamera.active = 0
        FakeCamera.maximum_active = 0
        FakeCamera.fail_side = ""
        FakeCamera.raise_side = ""
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


if __name__ == "__main__":
    unittest.main()
