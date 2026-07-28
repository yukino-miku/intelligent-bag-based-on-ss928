from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

BOARD_RUNTIME = Path(__file__).resolve().parents[2]
VISION = BOARD_RUNTIME.parent / "vision_obstacle_tracker"
for path in (BOARD_RUNTIME, VISION):
    sys.path.insert(0, str(path))

from mr20_radar.mr20_radar import RadarConfig, RiskConfig
from radar_vision_fusion.fusion_debug_server import FusionDebugServer
from radar_vision_fusion.fusion_runtime import FusionRuntimeSettings, RadarVisionFusionRuntime
from radar_vision_fusion.models import ClassificationFrame, VehicleDetection
from radar_vision_fusion.radar_camera_calibration import FusionCalibration


class RuntimeApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        radar = RadarConfig(
            "left_rear", "left", "0.0.0.0", 2368, "192.0.2.1",
            -10.0, 10.0, 0.0, 30.0, -1, 2, "unused.jsonl",
        )
        self.runtime = RadarVisionFusionRuntime(
            [radar],
            RiskConfig(((1, 8.0, 12.0, 1.0), (2, 5.0, 8.0, 2.0), (3, 3.0, 5.0, 3.0), (4, 1.5, 3.0, 4.0))),
            {"left": FusionCalibration(side="left")},
            lambda _event: None,
            settings=FusionRuntimeSettings(
                runtime_tuning_path=str(Path(self.temp.name) / "runtime.json"),
                alert_history_root=str(Path(self.temp.name) / "alerts"),
            ),
        )
        self.server = FusionDebugServer(self.runtime, bind="127.0.0.1", port=0, access_token="secret")
        self.server.start()
        self.base = f"http://127.0.0.1:{self.server.bound_port}"

    def tearDown(self) -> None:
        self.server.stop()
        self.temp.cleanup()

    def request(self, path, method="GET", payload=None, token="secret"):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "X-SmartBag-Token": token},
        )
        with urllib.request.urlopen(request, timeout=2.0) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_get_patch_reset_and_atomic_validation(self) -> None:
        status, current = self.request("/api/v1/settings/runtime")
        self.assertEqual(200, status)
        applied = self.request(
            "/api/v1/settings/runtime",
            "PATCH",
            {"association": {"bbox_expand_ratio": 0.4}, "risk": {"warning_sensitivity": 1.3}},
        )[1]
        self.assertEqual(0.4, applied["association"]["bbox_expand_ratio"])
        self.assertEqual(1.3, self.runtime.risk_windows.warning_sensitivity)
        version = applied["version"]
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("/api/v1/settings/runtime", "PATCH", {"risk": {"warning_sensitivity": 8.0}})
        self.assertEqual(400, raised.exception.code)
        self.assertEqual(version, self.runtime.runtime_settings()["version"])

        reloaded = RadarVisionFusionRuntime(
            list(self.runtime.radar_configs.values()),
            self.runtime.legacy_risk_config,
            {"left": FusionCalibration(side="left")},
            lambda _event: None,
            settings=FusionRuntimeSettings(
                runtime_tuning_path=str(Path(self.temp.name) / "runtime.json"),
                alert_history_root=str(Path(self.temp.name) / "reloaded-alerts"),
            ),
        )
        self.assertEqual(1.3, reloaded.runtime_settings()["risk"]["warning_sensitivity"])
        self.assertEqual(0.4, reloaded.runtime_settings()["association"]["bbox_expand_ratio"])
        reset = self.request("/api/v1/settings/runtime/reset", "POST", {})[1]
        self.assertEqual(1.0, reset["risk"]["warning_sensitivity"])

    def test_token_and_empty_history(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("/api/v1/settings/runtime", token="bad")
        self.assertEqual(401, raised.exception.code)
        history = self.request("/api/v1/alerts/history?limit=5")[1]
        self.assertEqual([], history["events"])

    def test_alert_detail_and_saved_image_endpoints(self) -> None:
        detection = VehicleDetection.from_bbox(7, 2, "car", 0.9, (10, 10, 80, 90))
        frame = ClassificationFrame(
            "left", 3, 20.0, 120, 100, (detection,), "LIVE", 1.0, 2.0,
            image=np.zeros((100, 120, 3), dtype=np.uint8),
        )
        self.runtime.process_classification(frame)
        event = self.runtime.alert_history.apply(
            "left",
            3,
            {"radar_track_key": "left:7:1", "radar_target_id": 7, "detection_id": 7},
            now_mono_s=20.1,
            now_epoch_s=1000.0,
        )
        event_id = event["event_id"]
        detail = self.request(f"/api/v1/alerts/{event_id}")[1]
        self.assertEqual("saved", detail["image_status"])
        image_request = urllib.request.Request(
            self.base + f"/api/v1/alerts/{event_id}/image.jpg",
            headers={"X-SmartBag-Token": "secret"},
        )
        with urllib.request.urlopen(image_request, timeout=2.0) as response:
            self.assertEqual("image/jpeg", response.headers.get_content_type())
            self.assertGreater(len(response.read()), 100)


if __name__ == "__main__":
    unittest.main()
