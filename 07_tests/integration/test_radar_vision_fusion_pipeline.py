from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOARD_RUNTIME = ROOT / "06_software" / "board_runtime"
VISION = ROOT / "06_software" / "vision_obstacle_tracker"
for path in (BOARD_RUNTIME, VISION):
    sys.path.insert(0, str(path))

from mr20_radar.mr20_radar import MR20Target, RadarConfig, RadarScan, RiskConfig  # noqa: E402
from radar_vision_fusion.fusion_runtime import RadarVisionFusionRuntime  # noqa: E402
from radar_vision_fusion.models import ClassificationFrame, VehicleDetection  # noqa: E402
from radar_vision_fusion.radar_camera_calibration import FusionCalibration  # noqa: E402


def config() -> RadarConfig:
    return RadarConfig(
        name="left_rear", side="left", bind_host="0.0.0.0", port=2368, radar_ip="192.0.2.1",
        lateral_min_m=-10.0, lateral_max_m=10.0, longitudinal_min_m=0.0, longitudinal_max_m=30.0,
        approaching_velocity_sign=-1, min_consecutive_frames=2, log_path="unused.jsonl",
    )


def scan(count: int, timestamp: float, z_m: float, *, targets: int = 1) -> RadarScan:
    items = tuple(
        MR20Target(
            target_id=index + 1,
            longitudinal_distance_m=z_m + index,
            lateral_distance_m=0.0,
            longitudinal_velocity_mps=-2.0,
            lateral_velocity_mps=0.0,
            status="oncoming",
        )
        for index in range(targets)
    )
    return RadarScan("left_rear", "left", count, timestamp, items)


def visual_frame(frame_id: int, timestamp: float, class_name: str = "truck") -> ClassificationFrame:
    detection = VehicleDetection.from_bbox(frame_id, 7, class_name, 0.9, (270, 100, 370, 350))
    return ClassificationFrame("left", frame_id, timestamp, 640, 480, (detection,), "LIVE", 5.0, 20.0)


def empty_visual_frame(frame_id: int, timestamp: float) -> ClassificationFrame:
    return ClassificationFrame("left", frame_id, timestamp, 640, 480, (), "LIVE", 5.0, 20.0)


class RadarVisionFusionPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.events = []
        radar = config()
        self.runtime = RadarVisionFusionRuntime(
            [radar],
            RiskConfig(levels=((1, 8.0, 12.0, 1.0), (2, 5.0, 8.0, 2.0), (3, 3.0, 5.0, 3.0), (4, 1.5, 3.0, 4.0))),
            {"left": FusionCalibration(side="left", camera_horizontal_fov_deg=90.0, camera_mount_y_m=0.8)},
            self.events.append,
        )

    def test_radar_risk_continues_with_unknown_class_when_camera_is_absent(self) -> None:
        records = self.runtime.process_scan(scan(1, 1.0, 8.0))
        self.assertEqual(1, len(records))
        self.assertEqual("unknown", records[0].fused.class_name)
        self.assertEqual("unknown", records[0].fused.class_source)
        self.assertTrue(any(event.source == "radar_vision_fusion" for event in self.events))

    def test_visual_class_binds_after_confirmation_and_is_cached_across_scan(self) -> None:
        self.runtime.process_scan(scan(1, 1.0, 8.0))
        self.runtime.process_classification(visual_frame(1, 1.0))
        self.runtime.process_classification(visual_frame(2, 1.05))
        records = self.runtime.process_scan(scan(2, 1.1, 7.8))
        self.assertEqual("truck", records[0].fused.class_name)
        self.assertIn(records[0].fused.class_source, {"vision_bound", "cached_binding"})
        latest_left = next(event for event in reversed(self.events) if event.side == "left")
        self.assertEqual(1.10, latest_left.class_weight)

    def test_multiple_targets_keep_independent_track_keys(self) -> None:
        records = self.runtime.process_scan(scan(1, 1.0, 7.0, targets=2))
        self.assertEqual(2, len(records))
        self.assertEqual(2, len({record.fused.track_key for record in records}))

    def test_single_visual_detection_never_binds_multiple_radar_targets(self) -> None:
        self.runtime.process_scan(scan(1, 1.0, 7.0, targets=2))
        result = self.runtime.process_classification(visual_frame(1, 1.02))
        self.assertEqual(1, len(result.matches))

    def test_yolo_no_target_keeps_radar_unknown_risk_active(self) -> None:
        self.runtime.process_scan(scan(1, 1.0, 7.0))
        self.runtime.process_classification(empty_visual_frame(1, 1.02))
        records = self.runtime.process_scan(scan(2, 1.1, 6.8))
        self.assertEqual("unknown", records[0].fused.class_name)
        self.assertTrue(any(event.source == "radar_vision_fusion" for event in self.events))

    def test_visual_binding_expires_without_clearing_radar_target(self) -> None:
        self.runtime.process_scan(scan(1, 1.0, 8.0))
        self.runtime.process_classification(visual_frame(1, 1.0))
        self.runtime.process_classification(visual_frame(2, 1.05))
        bound = self.runtime.process_scan(scan(2, 1.1, 7.8))
        self.assertEqual("truck", bound[0].fused.class_name)
        expired = bound
        for count, timestamp in enumerate((1.6, 2.2, 2.8, 3.4, 4.0, 4.2), start=3):
            expired = self.runtime.process_scan(scan(count, timestamp, 7.8 - count * 0.05))
        self.assertEqual("unknown", expired[0].fused.class_name)
        self.assertEqual(1, len(expired))

    def test_unchanged_rate_limited_event_is_marked_heartbeat(self) -> None:
        empty = lambda count, timestamp: RadarScan("left_rear", "left", count, timestamp, ())
        self.runtime.process_scan(empty(1, 1.0))
        self.runtime.process_scan(empty(2, 1.3))
        left_events = [event for event in self.events if event.side == "left"]
        self.assertEqual("clear", left_events[0].event_kind)
        self.assertEqual("heartbeat", left_events[-1].event_kind)

    def test_same_level_targets_are_ranked_by_score_not_list_order(self) -> None:
        records = self.runtime.process_scan(scan(1, 1.0, 4.0, targets=2))
        selected = next(event for event in reversed(self.events) if event.side == "left")
        expected = sorted(records, key=lambda item: (-item.stable.score, item.fused.distance_m))[0]
        self.assertEqual(expected.fused.radar_target_id, selected.radar_target_id)

    def test_repeated_empty_scans_clear_side_alert(self) -> None:
        self.runtime.process_scan(scan(1, 1.0, 5.0))
        empty = lambda count, timestamp: RadarScan("left_rear", "left", count, timestamp, ())
        self.runtime.process_scan(empty(2, 1.1))
        self.runtime.process_scan(empty(3, 1.2))
        self.runtime.process_scan(empty(4, 1.3))
        self.assertTrue(any(event.side == "left" and event.level == 0 for event in self.events))


if __name__ == "__main__":
    unittest.main()
