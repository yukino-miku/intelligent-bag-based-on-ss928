from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BOARD_RUNTIME = Path(__file__).resolve().parents[2]
VISION = BOARD_RUNTIME.parent / "vision_obstacle_tracker"
for path in (BOARD_RUNTIME, VISION):
    sys.path.insert(0, str(path))

from mr20_radar.mr20_radar import MR20Target, RadarConfig, RadarScan, RiskConfig  # noqa: E402
from radar_vision_fusion.fusion_replay import FusionReplay, load_replay_records  # noqa: E402
from radar_vision_fusion.fusion_runtime import (  # noqa: E402
    FusionRuntimeSettings,
    RadarVisionFusionRuntime,
)
from radar_vision_fusion.models import ClassificationFrame, VehicleDetection  # noqa: E402
from radar_vision_fusion.radar_camera_calibration import FusionCalibration  # noqa: E402


def radar_config() -> RadarConfig:
    return RadarConfig(
        name="left_rear",
        side="left",
        bind_host="0.0.0.0",
        port=2368,
        radar_ip="192.0.2.1",
        lateral_min_m=-10.0,
        lateral_max_m=10.0,
        longitudinal_min_m=0.0,
        longitudinal_max_m=30.0,
        approaching_velocity_sign=-1,
        min_consecutive_frames=2,
        log_path="unused.jsonl",
    )


def scan(count: int, timestamp: float, distance_m: float) -> RadarScan:
    target = MR20Target(7, distance_m, 0.0, -2.0, 0.0, "oncoming")
    return RadarScan(
        "left_rear", "left", count, timestamp, (target,),
        expected_target_count=1, received_target_count=1, unique_target_count=1,
    )


def classification(frame_id: int, timestamp: float) -> ClassificationFrame:
    detection = VehicleDetection.from_bbox(frame_id, 2, "car", 0.9, (270, 100, 370, 350))
    return ClassificationFrame("left", frame_id, timestamp, 640, 480, (detection,), "LIVE", 4.0, 12.0)


def runtime(record_dir: str = "") -> RadarVisionFusionRuntime:
    return RadarVisionFusionRuntime(
        [radar_config()],
        RiskConfig(levels=((1, 8.0, 12.0, 1.0), (2, 5.0, 8.0, 2.0), (3, 3.0, 5.0, 3.0), (4, 1.5, 3.0, 4.0))),
        {"left": FusionCalibration(side="left", camera_horizontal_fov_deg=90.0, camera_mount_y_m=0.8)},
        lambda _event: None,
        settings=FusionRuntimeSettings(record_dir=record_dir),
    )


class FusionReplayTest(unittest.TestCase):
    def test_recorded_scan_and_classification_replay_through_same_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = runtime(temp_dir)
            source.process_scan(scan(1, 1.0, 8.0))
            source.process_classification(classification(1, 1.02))
            source.process_classification(classification(2, 1.06))
            source.process_scan(scan(2, 1.1, 7.9))
            source.process_scan(scan(3, 1.51, 7.8))

            expected_streams = {
                "radar_scans",
                "classification_frames",
                "yolo_detections",
                "association_events",
                "visual_class_map",
                "fused_targets",
                "risk_events",
            }
            self.assertTrue(all((Path(temp_dir) / f"{name}.jsonl").is_file() for name in expected_streams))

            records = load_replay_records(temp_dir)
            self.assertEqual(5, len(records))
            replayed = runtime()
            FusionReplay(replayed).replay(records)
            latest = replayed.latest_risks()
            self.assertEqual(1, len(latest))
            self.assertEqual("car", latest[0].fused.class_name)
            self.assertEqual("vision_snapshot", latest[0].fused.class_source)


if __name__ == "__main__":
    unittest.main()
