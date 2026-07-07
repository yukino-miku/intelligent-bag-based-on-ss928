import unittest

from calibration import GroundPoint
from vision_core import (
    DetectionObservation,
    StableTrackIdManager,
    TrackState,
    TrackedObject,
    compute_observation_quality,
    format_overlay_label,
    parse_target_classes,
)


class VisionCoreTest(unittest.TestCase):
    def test_first_observation_has_zero_speed(self) -> None:
        state = TrackState()
        observation = DetectionObservation(
            track_id=7,
            class_name="car",
            confidence=0.91,
            bbox_xyxy=(10, 20, 110, 220),
            ground_point=GroundPoint(x_m=0.0, z_m=6.0),
            timestamp_s=10.0,
        )

        tracked = state.update(observation)

        self.assertEqual(7, tracked.track_id)
        self.assertEqual(6.0, tracked.distance_m)
        self.assertEqual(0.0, tracked.speed_mps)
        self.assertEqual(0.0, tracked.vx_mps)
        self.assertEqual(0.0, tracked.vz_mps)

    def test_second_observation_estimates_velocity_vector(self) -> None:
        state = TrackState(smoothing_alpha=1.0, history_seconds=10.0)
        state.update(
            DetectionObservation(
                track_id=7,
                class_name="car",
                confidence=0.91,
                bbox_xyxy=(10, 20, 110, 220),
                ground_point=GroundPoint(x_m=0.0, z_m=8.0),
                timestamp_s=10.0,
            )
        )

        tracked = state.update(
            DetectionObservation(
                track_id=7,
                class_name="car",
                confidence=0.90,
                bbox_xyxy=(15, 25, 115, 225),
                ground_point=GroundPoint(x_m=1.0, z_m=5.0),
                timestamp_s=11.0,
            )
        )

        self.assertAlmostEqual(1.0, tracked.vx_mps)
        self.assertAlmostEqual(-3.0, tracked.vz_mps)
        self.assertAlmostEqual(3.162, tracked.speed_mps, places=3)

    def test_velocity_uses_history_window_instead_of_single_frame_jump(self) -> None:
        state = TrackState(smoothing_alpha=1.0, history_seconds=2.0)
        state.update(
            DetectionObservation(
                track_id=9,
                class_name="car",
                confidence=0.9,
                bbox_xyxy=(0, 0, 10, 10),
                ground_point=GroundPoint(x_m=0.0, z_m=20.0),
                timestamp_s=0.0,
            )
        )
        state.update(
            DetectionObservation(
                track_id=9,
                class_name="car",
                confidence=0.9,
                bbox_xyxy=(0, 0, 10, 10),
                ground_point=GroundPoint(x_m=0.0, z_m=18.0),
                timestamp_s=0.5,
            )
        )

        tracked = state.update(
            DetectionObservation(
                track_id=9,
                class_name="car",
                confidence=0.9,
                bbox_xyxy=(0, 0, 10, 10),
                ground_point=GroundPoint(x_m=0.0, z_m=14.0),
                timestamp_s=1.0,
            )
        )

        self.assertAlmostEqual(-6.0, tracked.vz_mps, places=3)
        self.assertAlmostEqual(6.0, tracked.speed_mps, places=3)

    def test_speed_estimate_uses_robust_recent_motion_not_last_position_spike(self) -> None:
        state = TrackState(smoothing_alpha=1.0, history_seconds=3.0, max_speed_mps=40.0)
        samples = [
            (0.0, GroundPoint(x_m=-2.5, z_m=4.0)),
            (0.5, GroundPoint(x_m=-2.45, z_m=4.02)),
            (1.0, GroundPoint(x_m=-2.55, z_m=3.98)),
            (1.5, GroundPoint(x_m=2.5, z_m=8.0)),
        ]

        tracked = None
        for timestamp_s, point in samples:
            tracked = state.update(
                DetectionObservation(
                    track_id=31,
                    class_name="motorcycle",
                    confidence=0.90,
                    bbox_xyxy=(0, 0, 10, 10),
                    ground_point=point,
                    timestamp_s=timestamp_s,
                    distance_confidence=0.8,
                )
            )

        self.assertIsNotNone(tracked)
        self.assertLess(tracked.speed_mps, 1.0)
        self.assertLess(tracked.velocity_confidence, 0.8)
        self.assertGreater(tracked.position_jitter_m, 0.5)
        self.assertIn("position_jitter", tracked.motion_quality_flags)

    def test_track_state_reports_distance_trend_and_approach_consistency(self) -> None:
        state = TrackState(smoothing_alpha=1.0, history_seconds=3.0)
        tracked = None
        for timestamp_s, z_m in [(0.0, 8.0), (0.5, 7.0), (1.0, 6.0), (1.5, 5.0)]:
            tracked = state.update(
                DetectionObservation(
                    track_id=41,
                    class_name="car",
                    confidence=0.90,
                    bbox_xyxy=(0, 0, 10, 10),
                    ground_point=GroundPoint(x_m=0.4, z_m=z_m),
                    timestamp_s=timestamp_s,
                    distance_confidence=0.9,
                )
            )

        self.assertIsNotNone(tracked)
        self.assertLess(tracked.distance_trend_mps, 0.0)
        self.assertGreaterEqual(tracked.approach_consistency, 0.9)
        self.assertGreaterEqual(tracked.path_conflict_consistency, 0.9)

    def test_track_state_reports_moving_away_distance_trend(self) -> None:
        state = TrackState(smoothing_alpha=1.0, history_seconds=3.0)
        tracked = None
        for timestamp_s, z_m in [(0.0, 4.0), (0.5, 4.8), (1.0, 5.6), (1.5, 6.4)]:
            tracked = state.update(
                DetectionObservation(
                    track_id=42,
                    class_name="car",
                    confidence=0.90,
                    bbox_xyxy=(0, 0, 10, 10),
                    ground_point=GroundPoint(x_m=3.0, z_m=z_m),
                    timestamp_s=timestamp_s,
                    distance_confidence=0.9,
                )
            )

        self.assertIsNotNone(tracked)
        self.assertGreater(tracked.distance_trend_mps, 0.0)
        self.assertLessEqual(tracked.approach_consistency, 0.1)
        self.assertLessEqual(tracked.path_conflict_consistency, 0.1)

    def test_velocity_direction_reversal_lowers_confidence(self) -> None:
        state = TrackState(smoothing_alpha=1.0, history_seconds=3.0)
        for timestamp_s, point in [
            (0.0, GroundPoint(x_m=0.0, z_m=5.0)),
            (0.5, GroundPoint(x_m=0.5, z_m=5.0)),
            (1.0, GroundPoint(x_m=0.0, z_m=5.0)),
            (1.5, GroundPoint(x_m=0.5, z_m=5.0)),
        ]:
            tracked = state.update(
                DetectionObservation(
                    track_id=32,
                    class_name="bicycle",
                    confidence=0.90,
                    bbox_xyxy=(0, 0, 10, 10),
                    ground_point=point,
                    timestamp_s=timestamp_s,
                    distance_confidence=0.9,
                )
            )

        self.assertLess(tracked.velocity_confidence, 0.7)
        self.assertIn("velocity_reversal", tracked.motion_quality_flags)

    def test_distance_smoothing_reduces_single_frame_noise(self) -> None:
        state = TrackState(smoothing_alpha=0.5, history_seconds=2.0)
        state.update(
            DetectionObservation(
                track_id=5,
                class_name="car",
                confidence=0.9,
                bbox_xyxy=(0, 0, 10, 10),
                ground_point=GroundPoint(x_m=0.0, z_m=20.0),
                timestamp_s=0.0,
            )
        )

        tracked = state.update(
            DetectionObservation(
                track_id=5,
                class_name="car",
                confidence=0.9,
                bbox_xyxy=(0, 0, 10, 10),
                ground_point=GroundPoint(x_m=0.0, z_m=10.0),
                timestamp_s=1.0,
            )
        )

        self.assertAlmostEqual(15.0, tracked.distance_m, places=3)

    def test_missing_ground_point_keeps_target_displayable(self) -> None:
        state = TrackState()

        tracked = state.update(
            DetectionObservation(
                track_id=3,
                class_name="traffic light",
                confidence=0.70,
                bbox_xyxy=(1, 2, 3, 4),
                ground_point=None,
                timestamp_s=1.0,
            )
        )

        self.assertIsNone(tracked.distance_m)
        self.assertEqual(0.0, tracked.speed_mps)
        self.assertIn("d=unknown", format_overlay_label(tracked))

    def test_manual_tracked_object_defaults_use_neutral_quality_confidence(self) -> None:
        point = GroundPoint(x_m=0.0, z_m=4.0)

        tracked = TrackedObject(
            track_id=1,
            class_name="car",
            confidence=0.9,
            bbox_xyxy=(0, 0, 10, 10),
            ground_point=point,
            distance_m=point.distance_m,
            vx_mps=0.0,
            vz_mps=-2.0,
            speed_mps=2.0,
            timestamp_s=1.0,
        )

        self.assertEqual(1.0, tracked.distance_confidence)
        self.assertEqual(1.0, tracked.ground_confidence)
        self.assertEqual(1.0, tracked.size_confidence)

    def test_strong_ego_motion_lowers_velocity_confidence(self) -> None:
        state = TrackState(smoothing_alpha=1.0, history_seconds=2.0)
        state.update(
            DetectionObservation(
                track_id=12,
                class_name="car",
                confidence=0.90,
                bbox_xyxy=(0, 0, 10, 10),
                ground_point=GroundPoint(x_m=0.0, z_m=10.0),
                timestamp_s=0.0,
                distance_confidence=0.9,
            )
        )

        tracked = state.update(
            DetectionObservation(
                track_id=12,
                class_name="car",
                confidence=0.90,
                bbox_xyxy=(0, 0, 10, 10),
                ground_point=GroundPoint(x_m=0.0, z_m=9.0),
                timestamp_s=1.0,
                distance_confidence=0.9,
            ),
            ego_motion_magnitude=16.0,
        )

        self.assertLess(tracked.velocity_confidence, 0.9)
        self.assertGreater(tracked.velocity_confidence, 0.5)
        self.assertIn("strong_ego_motion", tracked.motion_quality_flags)

    def test_low_distance_confidence_reduces_observation_quality(self) -> None:
        high_quality = compute_observation_quality(
            detection_confidence=0.9,
            distance_confidence=0.9,
            velocity_confidence=0.9,
            track_age_frames=5,
        )
        low_distance_quality = compute_observation_quality(
            detection_confidence=0.9,
            distance_confidence=0.2,
            velocity_confidence=0.9,
            track_age_frames=5,
        )

        self.assertLess(low_distance_quality, high_quality)
        self.assertLess(low_distance_quality, 0.65)

    def test_parse_target_classes_keeps_vehicle_and_bicycle_names(self) -> None:
        classes = parse_target_classes("car,bicycle,motorcycle,bus,truck")

        self.assertIn("car", classes)
        self.assertIn("bicycle", classes)
        self.assertIn("truck", classes)

    def test_parse_target_classes_all_disables_class_filter(self) -> None:
        self.assertIsNone(parse_target_classes("all"))

    def test_stable_id_recovers_short_tracker_id_switch(self) -> None:
        manager = StableTrackIdManager(max_match_distance_m=2.0, max_time_gap_s=1.0)
        first = manager.assign(
            [
                DetectionObservation(
                    track_id=11,
                    class_name="car",
                    confidence=0.90,
                    bbox_xyxy=(100, 100, 180, 220),
                    ground_point=GroundPoint(x_m=0.0, z_m=18.0),
                    timestamp_s=0.0,
                )
            ]
        )[0]
        switched = manager.assign(
            [
                DetectionObservation(
                    track_id=42,
                    class_name="car",
                    confidence=0.88,
                    bbox_xyxy=(102, 101, 182, 221),
                    ground_point=GroundPoint(x_m=0.2, z_m=17.2),
                    timestamp_s=0.4,
                )
            ]
        )[0]

        self.assertEqual(first.track_id, switched.track_id)

    def test_stable_id_does_not_merge_different_classes(self) -> None:
        manager = StableTrackIdManager(max_match_distance_m=2.0, max_time_gap_s=1.0)
        car = manager.assign(
            [
                DetectionObservation(
                    track_id=11,
                    class_name="car",
                    confidence=0.90,
                    bbox_xyxy=(100, 100, 180, 220),
                    ground_point=GroundPoint(x_m=0.0, z_m=18.0),
                    timestamp_s=0.0,
                )
            ]
        )[0]
        bicycle = manager.assign(
            [
                DetectionObservation(
                    track_id=42,
                    class_name="bicycle",
                    confidence=0.88,
                    bbox_xyxy=(102, 101, 182, 221),
                    ground_point=GroundPoint(x_m=0.2, z_m=17.2),
                    timestamp_s=0.4,
                )
            ]
        )[0]

        self.assertNotEqual(car.track_id, bicycle.track_id)

    def test_overlay_label_verbosity_controls_detail(self) -> None:
        point = GroundPoint(x_m=0.3, z_m=3.0)
        tracked = TrackedObject(
            track_id=2,
            class_name="car",
            confidence=0.9,
            bbox_xyxy=(0, 0, 10, 10),
            ground_point=point,
            distance_m=point.distance_m,
            vx_mps=-0.5,
            vz_mps=-1.0,
            speed_mps=1.12,
            timestamp_s=1.0,
            distance_source="fused",
            distance_confidence=0.8,
            velocity_confidence=0.7,
        )

        minimal = format_overlay_label(tracked, verbosity="minimal")
        normal = format_overlay_label(tracked, verbosity="normal")
        debug = format_overlay_label(tracked, verbosity="debug")

        self.assertIn("car", minimal)
        self.assertNotIn("ID", minimal)
        self.assertIn("ID 2", normal)
        self.assertNotIn("vx=", normal)
        self.assertIn("qV=", debug)
        self.assertIn("vx=", debug)


if __name__ == "__main__":
    unittest.main()
