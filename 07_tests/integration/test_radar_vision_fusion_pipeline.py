from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOARD_RUNTIME = ROOT / "06_software" / "board_runtime"
VISION = ROOT / "06_software" / "vision_obstacle_tracker"
for path in (BOARD_RUNTIME, VISION):
    sys.path.insert(0, str(path))

from mr20_radar.mr20_radar import MR20Target, RadarConfig, RadarScan, RiskConfig  # noqa: E402
from radar_vision_fusion.fusion_runtime import FusionRuntimeSettings, RadarVisionFusionRuntime  # noqa: E402
from radar_vision_fusion.models import ClassificationFrame, VehicleDetection  # noqa: E402
from radar_vision_fusion.radar_camera_calibration import FusionCalibration  # noqa: E402


def config() -> RadarConfig:
    return RadarConfig(
        name="left_rear", side="left", bind_host="0.0.0.0", port=2368, radar_ip="192.0.2.1",
        lateral_min_m=-10.0, lateral_max_m=10.0, longitudinal_min_m=0.0, longitudinal_max_m=30.0,
        approaching_velocity_sign=-1, min_consecutive_frames=2, log_path="unused.jsonl",
    )


def scan(count: int, timestamp: float, z_m: float, *, targets: int = 1, complete: bool = True) -> RadarScan:
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
    return RadarScan(
        "left_rear", "left", count, timestamp, items,
        expected_target_count=targets,
        received_target_count=targets,
        unique_target_count=targets,
        complete=complete,
        completion_reason="target_count_reached" if complete else "scan_timeout",
    )


def visual_frame(frame_id: int, timestamp: float, class_name: str = "truck") -> ClassificationFrame:
    detection = VehicleDetection.from_bbox(frame_id, 7, class_name, 0.9, (270, 100, 370, 350))
    return ClassificationFrame("left", frame_id, timestamp, 640, 480, (detection,), "LIVE", 5.0, 20.0)


def empty_visual_frame(frame_id: int, timestamp: float) -> ClassificationFrame:
    return ClassificationFrame("left", frame_id, timestamp, 640, 480, (), "LIVE", 5.0, 20.0)


class RadarVisionFusionPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.events = []
        radar = config()
        self.runtime = RadarVisionFusionRuntime(
            [radar],
            RiskConfig(levels=((1, 8.0, 12.0, 1.0), (2, 5.0, 8.0, 2.0), (3, 3.0, 5.0, 3.0), (4, 1.5, 3.0, 4.0))),
            {"left": FusionCalibration(side="left", camera_horizontal_fov_deg=90.0, camera_mount_y_m=0.8)},
            self.events.append,
            settings=FusionRuntimeSettings(
                runtime_tuning_path=str(Path(self.temp.name) / "runtime.json"),
                alert_history_root=str(Path(self.temp.name) / "alerts"),
            ),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_no_internal_mixed_event_queue_exists(self) -> None:
        self.assertFalse(hasattr(self.runtime, "_queue"))
        self.assertFalse(hasattr(self.runtime, "_run"))

    def test_radar_samples_continue_with_unknown_when_camera_is_absent(self) -> None:
        self.assertEqual((), self.runtime.process_scan(scan(1, 1.01, 8.0)))
        records = self.runtime.process_scan(scan(2, 1.51, 7.8))
        self.assertEqual(1, len(records))
        self.assertEqual("unknown", records[0].fused.class_name)
        self.assertEqual("median_500ms_window", records[0].stabilizer.reason)

    def test_each_visual_frame_atomically_replaces_the_whole_class_map(self) -> None:
        self.runtime.process_scan(scan(1, 2.01, 8.0))
        self.runtime.process_classification(visual_frame(1, 2.02))
        first = self.runtime.latest_class_map("left")
        self.assertIsNotNone(first)
        assert first is not None
        self.assertEqual("truck", next(iter(first.mapping.values())).class_name)

        self.runtime.process_classification(empty_visual_frame(2, 2.04))
        second = self.runtime.latest_class_map("left")
        assert second is not None
        self.assertEqual(2, second.frame_id)
        self.assertEqual("unknown", next(iter(second.mapping.values())).class_name)

    def test_single_visual_frame_is_immediately_used_without_binding_confirmation(self) -> None:
        self.runtime.process_scan(scan(1, 3.01, 8.0))
        self.runtime.process_classification(visual_frame(1, 3.02, "truck"))
        self.runtime.process_scan(scan(2, 3.2, 7.9))
        records = self.runtime.process_scan(scan(3, 3.51, 7.8))
        self.assertEqual("truck", records[0].fused.class_name)
        self.assertEqual("vision_snapshot", records[0].fused.class_source)

    def test_visual_mapping_expires_to_unknown_without_deleting_radar_track(self) -> None:
        self.runtime.process_scan(scan(1, 4.01, 8.0))
        self.runtime.process_classification(visual_frame(1, 4.02))
        self.runtime.process_scan(scan(2, 4.51, 7.8))
        self.runtime.process_scan(scan(3, 6.01, 7.5))
        records = self.runtime.process_scan(scan(4, 6.51, 7.4))
        self.assertTrue(records)
        self.assertEqual("unknown", records[-1].fused.class_name)
        self.assertEqual(1, len(self.runtime.track_manager.active_tracks("left")))

    def test_incomplete_scan_updates_seen_target_without_pruning_missing_track(self) -> None:
        self.runtime.process_scan(scan(1, 7.01, 7.0, targets=2))
        incomplete = scan(2, 7.21, 6.8, targets=1, complete=False)
        for _index in range(5):
            self.runtime.process_scan(incomplete)
        self.assertEqual(2, len(self.runtime.track_manager.active_tracks("left")))

    def test_status_reports_current_and_latest_scan_target_counts(self) -> None:
        self.runtime.process_scan(scan(1, 7.51, 7.0, targets=2))
        status = self.runtime.status()
        radar = status["radars"]["left_rear"]
        self.assertEqual(2, radar["current_target_count"])
        self.assertEqual(2, radar["latest_scan_target_count"])
        self.assertTrue(radar["latest_scan_complete"])
        self.assertEqual("target_count_reached", radar["latest_scan_completion_reason"])

    def test_complete_empty_window_clears_side(self) -> None:
        self.runtime.process_scan(scan(1, 8.01, 5.0))
        self.runtime.process_scan(scan(2, 8.51, 4.8))
        empty = lambda count, timestamp: scan(count, timestamp, 0.0, targets=0)
        self.runtime.process_scan(empty(3, 9.01))
        self.runtime.process_scan(empty(4, 9.51))
        self.assertTrue(any(event.side == "left" and event.level == 0 for event in self.events))

    def test_runtime_sensitivity_patch_applies_and_persists(self) -> None:
        applied = self.runtime.patch_runtime_settings({"risk": {"warning_sensitivity": 1.4}})
        self.assertEqual(1.4, applied["risk"]["warning_sensitivity"])
        self.assertEqual(1.4, self.runtime.risk_windows.warning_sensitivity)
        self.assertTrue((Path(self.temp.name) / "runtime.json").is_file())
        with self.assertRaises(ValueError):
            self.runtime.patch_runtime_settings({"risk": {"warning_sensitivity": 9.0}})
        self.assertEqual(1.4, self.runtime.risk_windows.warning_sensitivity)

    def test_runtime_radar_mount_patch_reprojects_active_track_and_clears_partial_window(self) -> None:
        self.runtime.process_scan(scan(1, 10.01, 8.0))
        track = self.runtime.track_manager.active_tracks("left")[0]
        before_x = track.x_m
        self.assertEqual(1, sum(self.runtime.risk_windows.sample_counts().values()))
        self.runtime.patch_runtime_settings({"left": {"radar_mount_x_m": 1.0, "radar_yaw_deg": 10.0}})
        updated = self.runtime.track_manager.get(track.track_key)
        self.assertIsNotNone(updated)
        self.assertNotAlmostEqual(before_x, updated.x_m)
        self.assertEqual({}, self.runtime.risk_windows.sample_counts())
        self.assertEqual(1.0, self.runtime.radar_configs["left_rear"].mount_x_m)


if __name__ == "__main__":
    unittest.main()
