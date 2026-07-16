import json
import time
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

import numpy as np

from video_stream_server import DetectorVideoServer


class DetectorVideoServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = DetectorVideoServer("left", "/dev/video0", bind="127.0.0.1", port=0)
        self.server.start()
        self.base = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self) -> None:
        self.server.stop()

    def test_offline_status_is_explicit(self) -> None:
        with urlopen(self.base + "/api/v1/camera/left/status", timeout=2.0) as response:
            payload = json.loads(response.read())
        self.assertFalse(payload["online"])
        with self.assertRaises(HTTPError) as context:
            urlopen(self.base + "/api/v1/camera/left/snapshot.jpg", timeout=2.0)
        self.assertEqual(503, context.exception.code)

    def test_snapshot_returns_latest_raw_and_overlay_frames(self) -> None:
        raw = np.zeros((48, 64, 3), dtype=np.uint8)
        overlay = raw.copy()
        overlay[:, :, 2] = 255
        self.server.publish(raw, overlay, {"online": True, "risk_level": 2, "risk_name": "CAUTION"})

        status = self.server.status()
        self.assertEqual((640, 360, 70), (status["jpeg_stream_width"], status["jpeg_stream_height"], status["jpeg_quality"]))

        for view in ("raw", "overlay"):
            with urlopen(
                self.base + f"/api/v1/camera/left/snapshot.jpg?view={view}",
                timeout=2.0,
            ) as response:
                jpeg = response.read()
            self.assertTrue(jpeg.startswith(b"\xff\xd8"))
            self.assertTrue(jpeg.endswith(b"\xff\xd9"))

    def test_publish_is_not_blocked_by_encoding_or_slow_clients(self) -> None:
        frame = np.zeros((540, 960, 3), dtype=np.uint8)
        started = time.perf_counter()
        for _index in range(100):
            self.server.publish(frame, None, {"online": True})
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 0.2)

    def test_debug_page_propagates_encoded_access_token(self) -> None:
        page = self.server._debug_page("token with spaces")

        self.assertIn("token=token+with+spaces", page)

    def test_capture_status_provider_can_mark_published_camera_offline(self) -> None:
        self.server.status_provider = lambda: {"online": False, "last_error": "camera read failed"}
        frame = np.zeros((24, 32, 3), dtype=np.uint8)
        self.server.publish(frame, frame, {"online": True})

        status = self.server.status()

        self.assertFalse(status["online"])
        self.assertEqual("camera read failed", status["last_error"])


if __name__ == "__main__":
    unittest.main()
