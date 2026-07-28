from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

BOARD_RUNTIME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BOARD_RUNTIME))

from radar_vision_fusion.models import ClassificationFrame, VehicleDetection  # noqa: E402
from radar_vision_fusion.radar_camera_calibration import FusionCalibration, project_radar_track  # noqa: E402
from radar_vision_fusion.radar_tracks import RadarTrack  # noqa: E402
from radar_vision_fusion.radar_vision_association import AssociationConfig, RadarVisionAssociation  # noqa: E402
from radar_vision_fusion.visual_binding import BindingConfig, BindingState, VisualClassBindingManager  # noqa: E402


def track(key: str, side: str, x: float, z: float, timestamp: float = 1.0) -> RadarTrack:
    return RadarTrack(
        track_key=key, radar_name=f"{side}_rear", side=side, target_id=int(key[-1]), generation=1,
        first_seen_mono_s=timestamp, last_seen_mono_s=timestamp, age_scans=4, missed_scans=0,
        x_m=x, z_m=z, vx_mps=0.0, vz_mps=-1.0, distance_m=(x * x + z * z) ** 0.5,
        speed_mps=1.0, status="oncoming", measurement_count=1,
        position_history=[(timestamp, x, z)], velocity_history=[(timestamp, 0.0, -1.0)], radar_quality=1.0,
    )


def detection(identifier: int, class_name: str, center_x: float) -> VehicleDetection:
    return VehicleDetection.from_bbox(identifier, 2, class_name, 0.9, (center_x - 40, 100, center_x + 40, 300))


def frame(frame_id: int, side: str, *detections: VehicleDetection, timestamp: float = 1.0) -> ClassificationFrame:
    return ClassificationFrame(side, frame_id, timestamp, 640, 480, tuple(detections), "LIVE", 2.0, 10.0)


class AssociationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.calibration = FusionCalibration(side="left", camera_horizontal_fov_deg=90.0, camera_mount_y_m=0.8)
        self.association = RadarVisionAssociation(
            AssociationConfig(
                projection_half_width_px=80,
                projection_half_width_ratio=0.0,
                max_center_distance_px=120,
                max_association_cost=1.0,
            )
        )

    def test_two_tracks_match_one_to_one_when_bbox_order_is_reversed(self) -> None:
        tracks = [track("left:1", "left", -1.0, 5.0), track("left:2", "left", 1.0, 5.0)]
        result = self.association.associate(
            frame(1, "left", detection(20, "truck", 384), detection(10, "car", 256)),
            tracks,
            self.calibration,
        )
        self.assertEqual(2, len(result.matches))
        self.assertEqual({10, 20}, {item.detection_id for item in result.matches})
        self.assertEqual(2, len({item.track_key for item in result.matches}))

    def test_time_gap_fov_and_side_gates_leave_target_unknown(self) -> None:
        wrong_side = track("right:1", "right", 0.0, 5.0)
        stale = track("left:1", "left", 0.0, 5.0, timestamp=0.0)
        result = self.association.associate(frame(1, "left", detection(1, "car", 320), timestamp=1.0), [wrong_side, stale], self.calibration)
        self.assertEqual((), result.matches)

    def test_one_bbox_cannot_bind_two_radar_tracks(self) -> None:
        tracks = [track("left:1", "left", -0.1, 5.0), track("left:2", "left", 0.1, 5.0)]
        result = self.association.associate(frame(1, "left", detection(10, "car", 320)), tracks, self.calibration)
        self.assertEqual(1, len(result.matches))
        self.assertEqual(1, len({item.detection_id for item in result.matches}))

    def test_horizontal_interval_overlap_is_a_hard_gate(self) -> None:
        strict = RadarVisionAssociation(
            AssociationConfig(
                projection_half_width_px=20,
                projection_half_width_ratio=0.0,
                bbox_expand_ratio=0.0,
                max_center_distance_px=300,
            )
        )
        result = strict.associate(
            frame(1, "left", detection(1, "car", 430)),
            [track("left:1", "left", 0.0, 5.0)],
            self.calibration,
        )
        self.assertEqual((), result.matches)

    def test_overlapping_candidates_with_near_equal_cost_are_ambiguous(self) -> None:
        ambiguous = RadarVisionAssociation(
            AssociationConfig(
                projection_half_width_px=100,
                projection_half_width_ratio=0.0,
                ambiguity_cost_gap=0.20,
            )
        )
        target = track("left:1", "left", 0.0, 5.0)
        result = ambiguous.associate(
            frame(1, "left", detection(1, "car", 300), detection(2, "truck", 340)),
            [target],
            self.calibration,
        )
        self.assertEqual((), result.matches)
        self.assertEqual((target.track_key,), result.ambiguous_track_keys)

    def test_explicit_extrinsic_uses_rotation_then_translation(self) -> None:
        calibration = FusionCalibration(
            side="left",
            camera_horizontal_fov_deg=90.0,
            camera_mount_y_m=0.8,
            radar_to_camera_rotation=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            radar_to_camera_translation=(1.0, 0.0, 0.0),
        )
        projection = project_radar_track(track("left:1", "left", 1.0, 5.0), calibration, 1.0, 640, 480)
        self.assertAlmostEqual(448.0, projection.projected_u_px, places=4)


class BindingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.track = track("left:1", "left", 0.0, 5.0)
        self.calibration = FusionCalibration(side="left", camera_horizontal_fov_deg=90.0, camera_mount_y_m=0.8)
        self.association = RadarVisionAssociation()
        self.bindings = VisualClassBindingManager(BindingConfig(binding_min_confirmations=2, binding_max_visual_misses=3, class_switch_confirmations=2))

    def update(self, frame_id: int, class_name: str | None = "car") -> None:
        detections = () if class_name is None else (detection(frame_id, class_name, 320),)
        current_frame = frame(frame_id, "left", *detections, timestamp=1.0 + frame_id * 0.05)
        result = self.association.associate(current_frame, [self.track], self.calibration, self.bindings.bound_classes())
        self.bindings.update(current_frame, result.matches, [self.track], result.projections)

    def test_two_confirmations_bind_and_one_miss_does_not_unbind(self) -> None:
        self.update(1)
        self.assertEqual("unknown", self.bindings.resolve(self.track.track_key, 1.05)[0])
        self.update(2)
        self.assertEqual("car", self.bindings.resolve(self.track.track_key, 1.1)[0])
        self.update(3, None)
        resolved = self.bindings.resolve(self.track.track_key, 1.15)
        self.assertEqual("car", resolved[0])
        self.assertEqual(BindingState.STALE.value, resolved[4])

    def test_single_class_change_does_not_switch_but_repeated_change_does(self) -> None:
        self.update(1)
        self.update(2)
        self.update(3, "truck")
        self.assertEqual("car", self.bindings.resolve(self.track.track_key, 1.15)[0])
        self.update(4, "truck")
        self.assertEqual("truck", self.bindings.resolve(self.track.track_key, 1.2)[0])

    def test_consecutive_visual_misses_clear_binding(self) -> None:
        self.update(1)
        self.update(2)
        self.update(3, None)
        self.update(4, None)
        self.update(5, None)
        self.assertEqual("unknown", self.bindings.resolve(self.track.track_key, 1.25)[0])

    def test_radar_removal_and_fov_exit_clear_binding(self) -> None:
        self.update(1)
        self.update(2)
        empty_frame = frame(3, "left", timestamp=1.15)
        events = self.bindings.update(empty_frame, (), (), ())
        self.assertTrue(any(item.event == "radar_track_removed" for item in events))

        self.update(4)
        self.update(5)
        outside = replace(
            self.track,
            x_m=20.0,
            z_m=5.0,
            position_history=[(1.3, 20.0, 5.0)],
            velocity_history=[(1.3, 0.0, -1.0)],
        )
        outside_frame = frame(6, "left", timestamp=1.3)
        result = self.association.associate(outside_frame, [outside], self.calibration, self.bindings.bound_classes())
        events = self.bindings.update(outside_frame, result.matches, [outside], result.projections)
        self.assertTrue(any(item.event == "left_fov" for item in events))

    def test_processing_left_frame_does_not_clear_right_binding(self) -> None:
        right_track = track("right:2", "right", 0.0, 5.0)
        right_calibration = FusionCalibration(side="right", camera_horizontal_fov_deg=90.0, camera_mount_y_m=0.8)
        for frame_id in (1, 2):
            right_frame = frame(frame_id, "right", detection(frame_id, "truck", 320), timestamp=1.0 + frame_id * 0.05)
            result = self.association.associate(right_frame, [right_track], right_calibration, self.bindings.bound_classes())
            self.bindings.update(right_frame, result.matches, [right_track], result.projections)
        left_frame = frame(3, "left", timestamp=1.2)
        self.bindings.update(left_frame, (), [self.track], ())
        self.assertEqual("truck", self.bindings.resolve(right_track.track_key, 1.2)[0])

    def test_binding_timeout_returns_unknown(self) -> None:
        self.update(1)
        self.update(2)
        self.assertEqual("unknown", self.bindings.resolve(self.track.track_key, 10.0)[0])


if __name__ == "__main__":
    unittest.main()
