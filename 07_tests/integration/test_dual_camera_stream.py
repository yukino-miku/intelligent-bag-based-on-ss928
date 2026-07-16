import json
import sys
import threading
import time
import unittest
from pathlib import Path
from urllib.request import urlopen

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
VISION = ROOT / "06_software" / "vision_obstacle_tracker"
if str(VISION) not in sys.path:
    sys.path.insert(0, str(VISION))

from dual_camera_gateway import DualCameraGateway
from video_stream_server import DetectorVideoServer


class DualCameraStreamTest(unittest.TestCase):
    def setUp(self) -> None:
        self.left = DetectorVideoServer("left", "/dev/video0", port=0)
        self.right = DetectorVideoServer("right", "/dev/video2", port=0)
        self.left.start()
        self.right.start()
        frame = np.zeros((36, 64, 3), dtype=np.uint8)
        self.left.publish(frame, frame, {"online": True, "risk_level": 1, "risk_name": "ATTENTION"})
        self.right.publish(frame, frame, {"online": True, "risk_level": 3, "risk_name": "DANGER"})
        self.gateway = DualCameraGateway(
            "127.0.0.1",
            0,
            f"http://127.0.0.1:{self.left.port}",
            f"http://127.0.0.1:{self.right.port}",
            controller_status_file="missing-controller-status.json",
        )
        self.thread = threading.Thread(target=self.gateway.serve_forever, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 2.0
        while self.gateway.port == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.base = f"http://127.0.0.1:{self.gateway.port}"

    def tearDown(self) -> None:
        if self.gateway.httpd is not None:
            self.gateway.httpd.shutdown()
            self.gateway.httpd.server_close()
        self.thread.join(timeout=2.0)
        self.left.stop()
        self.right.stop()

    def test_gateway_returns_distinct_left_and_right_snapshots_and_statuses(self) -> None:
        with urlopen(self.base + "/api/v1/cameras", timeout=2.0) as response:
            statuses = json.loads(response.read())
        self.assertEqual(["left", "right"], [item["side"] for item in statuses])
        self.assertEqual([1, 3], [item["risk_level"] for item in statuses])

        for side in ("left", "right"):
            with urlopen(self.base + f"/api/v1/camera/{side}/snapshot.jpg", timeout=2.0) as response:
                self.assertEqual("image/jpeg", response.headers.get_content_type())
                self.assertTrue(response.read().startswith(b"\xff\xd8"))

    def test_gateway_debug_page_propagates_encoded_access_token(self) -> None:
        page = self.gateway._debug_page("token with spaces")

        self.assertIn("token=token+with+spaces", page)

    def test_one_offline_camera_does_not_hide_other_camera_status(self) -> None:
        self.gateway.urls["right"] = "http://127.0.0.1:1"

        with urlopen(self.base + "/api/v1/cameras", timeout=2.0) as response:
            statuses = json.loads(response.read())

        self.assertTrue(statuses[0]["online"])
        self.assertFalse(statuses[1]["online"])
        self.assertEqual(["left", "right"], [item["side"] for item in statuses])


if __name__ == "__main__":
    unittest.main()
