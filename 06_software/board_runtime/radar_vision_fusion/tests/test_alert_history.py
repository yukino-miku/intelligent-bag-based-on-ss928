from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

import numpy as np

BOARD_RUNTIME = Path(__file__).resolve().parents[2]
VISION = BOARD_RUNTIME.parent / "vision_obstacle_tracker"
for path in (BOARD_RUNTIME, VISION):
    sys.path.insert(0, str(path))

from radar_vision_fusion.alert_history import AlertHistoryStore
from radar_vision_fusion.models import ClassificationFrame, VehicleDetection


def frame(side: str, timestamp: float) -> ClassificationFrame:
    detection = VehicleDetection.from_bbox(1, 2, "car", 0.9, (20, 20, 100, 100))
    return ClassificationFrame(
        side, 1, timestamp, 160, 120, (detection,), "LIVE", 2.0, 3.0,
        image=np.zeros((120, 160, 3), dtype=np.uint8),
    )


class AlertHistoryStoreTest(unittest.TestCase):
    def test_same_track_and_level_updates_without_duplicate_image(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            calls = []

            def provider(side):
                calls.append(side)
                return frame(side, 10.0)

            store = AlertHistoryStore(temp_dir, snapshot_provider=provider)
            payload = {
                "radar_track_key": "left:1:1", "radar_target_id": 1, "effective_score": 0.8,
                "distance_m": 3.0, "speed_mps": 2.0, "class_name": "car",
            }
            first = store.apply("left", 3, payload, now_mono_s=10.1, now_epoch_s=100.0)
            second = store.apply("left", 3, {**payload, "effective_score": 0.9}, now_mono_s=10.2, now_epoch_s=101.0)
            third = store.apply(
                "left",
                3,
                {**payload, "class_name": "truck", "effective_score": 0.85},
                now_mono_s=10.3,
                now_epoch_s=102.0,
            )
            self.assertEqual(first["event_id"], second["event_id"])
            self.assertEqual(first["event_id"], third["event_id"])
            self.assertEqual(1, len(store.history()["events"]))
            self.assertEqual(["left"], calls)
            self.assertEqual(0.9, second["peak_score"])
            self.assertEqual("saved", first["image_status"])
            self.assertTrue(Path(first["image_path"]).is_file())

    def test_level_upgrade_or_track_change_creates_new_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AlertHistoryStore(temp_dir, snapshot_provider=lambda side: frame(side, 20.0))
            first = store.apply("right", 3, {"radar_track_key": "r:1"}, now_mono_s=20.0, now_epoch_s=200.0)
            second = store.apply("right", 4, {"radar_track_key": "r:1"}, now_mono_s=20.1, now_epoch_s=201.0)
            third = store.apply("right", 4, {"radar_track_key": "r:2"}, now_mono_s=20.2, now_epoch_s=202.0)
            self.assertEqual(3, len({first["event_id"], second["event_id"], third["event_id"]}))

    def test_snapshot_is_same_side_and_stale_image_is_not_saved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            requested = []

            def provider(side):
                requested.append(side)
                return frame(side, 1.0)

            store = AlertHistoryStore(temp_dir, max_snapshot_age_s=0.5, snapshot_provider=provider)
            event = store.apply("right", 3, {"radar_track_key": "r:1"}, now_mono_s=3.0, now_epoch_s=300.0)
            self.assertEqual(["right"], requested)
            self.assertEqual("stale", event["image_status"])
            self.assertEqual("", event["image_path"])


if __name__ == "__main__":
    unittest.main()
