import time
import unittest

from camera_runtime import LatestFrameBuffer, LatestOpenCvCameraCapture


class LatestFrameBufferTest(unittest.TestCase):
    def test_latest_frame_replaces_stale_frames_without_queue_growth(self) -> None:
        buffer = LatestFrameBuffer()
        first = buffer.put("frame-1", 1.0)
        buffer.put("frame-2", 2.0)
        buffer.put("frame-3", 3.0)

        snapshot = buffer.take_latest(after_sequence=first, timeout_s=0.0)

        self.assertIsNotNone(snapshot)
        self.assertEqual("frame-3", snapshot.frame)
        self.assertEqual(2, buffer.overwritten_frames)

    def test_normal_camera_runtime_opens_device_once(self) -> None:
        factory_calls = []

        class FakeFrame:
            shape = (480, 640, 3)

            def __str__(self) -> str:
                return "frame"

        class FakeCapture:
            def __init__(self) -> None:
                self.opened = True
                self.index = 0

            def isOpened(self):
                return self.opened

            def set(self, *_args):
                return True

            def read(self):
                if not self.opened:
                    return False, None
                self.index += 1
                time.sleep(0.002)
                return True, FakeFrame()

            def release(self):
                self.opened = False

        def factory(device):
            factory_calls.append(device)
            return FakeCapture()

        capture = LatestOpenCvCameraCapture(
            "/dev/video-test",
            960,
            540,
            20,
            capture_factory=factory,
        )
        try:
            ok, frame = capture.read()
            self.assertTrue(ok)
            self.assertEqual("frame", str(frame))
            self.assertEqual(["/dev/video-test"], factory_calls)
            self.assertEqual((640, 480), (capture.status()["capture_width"], capture.status()["capture_height"]))
        finally:
            capture.release()

    def test_disconnect_uses_bounded_reconnect_attempts(self) -> None:
        factory_calls = []

        class FailedCapture:
            def isOpened(self):
                return False

            def set(self, *_args):
                return False

            def release(self):
                return None

        def factory(device):
            factory_calls.append(device)
            return FailedCapture()

        capture = LatestOpenCvCameraCapture(
            "/dev/missing",
            640,
            480,
            20,
            max_reconnect_attempts=2,
            reconnect_backoff_s=0.01,
            capture_factory=factory,
        )
        try:
            deadline = time.monotonic() + 1.0
            while capture.isOpened() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(capture.isOpened())
            self.assertEqual(3, len(factory_calls))
            self.assertEqual(2, capture.reconnect_count)
        finally:
            capture.release()


if __name__ == "__main__":
    unittest.main()
