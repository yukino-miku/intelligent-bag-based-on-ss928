import unittest

from calibration import GroundPoint
from risk_model import MotionPattern, RiskLevel, RiskModel, RiskModelConfig, RiskWeights, assess_collision_risk
from vision_core import TrackedObject


def make_target(
    class_name: str = "car",
    x_m: float = 0.0,
    z_m: float = 20.0,
    vx_mps: float = 0.0,
    vz_mps: float = 0.0,
    confidence: float = 0.9,
    timestamp_s: float = 1.0,
    velocity_confidence: float = 1.0,
    distance_confidence: float = 1.0,
    track_age_frames: int = 10,
    motion_quality_flags: tuple[str, ...] = (),
) -> TrackedObject:
    point = GroundPoint(x_m=x_m, z_m=z_m)
    return TrackedObject(
        track_id=1,
        class_name=class_name,
        confidence=confidence,
        bbox_xyxy=(10, 10, 100, 100),
        ground_point=point,
        distance_m=point.distance_m,
        vx_mps=vx_mps,
        vz_mps=vz_mps,
        speed_mps=(vx_mps**2 + vz_mps**2) ** 0.5,
        timestamp_s=timestamp_s,
        distance_source="fused",
        velocity_confidence=velocity_confidence,
        distance_confidence=distance_confidence,
        track_age_frames=track_age_frames,
        motion_quality_flags=motion_quality_flags,
    )


class RiskModelTest(unittest.TestCase):
    def test_head_on_fast_vehicle_becomes_emergency(self) -> None:
        assessment = assess_collision_risk(make_target(z_m=4.0, vz_mps=-12.0))

        self.assertEqual(RiskLevel.EMERGENCY, assessment.level)
        self.assertGreaterEqual(assessment.score, 0.90)
        self.assertLess(assessment.ttc_s, 0.5)
        self.assertAlmostEqual(0.0, assessment.trajectory_distance_m, places=3)

    def test_trajectory_distance_uses_distance_from_origin_to_motion_line(self) -> None:
        vertical_path = assess_collision_risk(make_target(x_m=3.0, z_m=4.0, vx_mps=0.0, vz_mps=-4.0))
        diagonal_path = assess_collision_risk(make_target(x_m=3.0, z_m=4.0, vx_mps=-3.0, vz_mps=-4.0))

        self.assertAlmostEqual(3.0, vertical_path.trajectory_distance_m, places=3)
        self.assertAlmostEqual(0.0, diagonal_path.trajectory_distance_m, places=3)

    def test_bicycle_trajectory_distance_over_1_5m_is_safe(self) -> None:
        assessment = assess_collision_risk(make_target(class_name="bicycle", x_m=1.6, z_m=4.0, vz_mps=-4.0))

        self.assertEqual(RiskLevel.SAFE, assessment.level)
        self.assertGreater(assessment.trajectory_distance_m, 1.5)

    def test_motor_vehicle_trajectory_distance_over_3m_is_safe_even_when_fast(self) -> None:
        assessment = assess_collision_risk(make_target(class_name="car", x_m=3.2, z_m=4.0, vz_mps=-12.0))

        self.assertEqual(RiskLevel.SAFE, assessment.level)
        self.assertGreater(assessment.trajectory_distance_m, 3.0)

    def test_motorcycle_uses_motor_vehicle_trajectory_threshold(self) -> None:
        assessment = assess_collision_risk(make_target(class_name="motorcycle", x_m=3.1, z_m=4.0, vz_mps=-12.0))

        self.assertEqual(RiskLevel.SAFE, assessment.level)
        self.assertGreater(assessment.trajectory_distance_m, 3.0)

    def test_trajectory_distance_inside_threshold_contributes_to_score(self) -> None:
        assessment = assess_collision_risk(make_target(class_name="car", x_m=1.0, z_m=4.0, vz_mps=-4.0))

        self.assertGreaterEqual(assessment.level.value, RiskLevel.CAUTION.value)
        self.assertAlmostEqual(1.0, assessment.trajectory_distance_m, places=3)

    def test_ttc_over_5s_is_forced_safe_even_inside_trajectory_threshold(self) -> None:
        assessment = assess_collision_risk(make_target(class_name="car", x_m=0.0, z_m=6.0, vz_mps=-1.0))

        self.assertGreater(assessment.ttc_s, 5.0)
        self.assertEqual(RiskLevel.SAFE, assessment.level)
        self.assertEqual(0.0, assessment.score)
        self.assertAlmostEqual(0.0, assessment.trajectory_distance_m, places=3)

    def test_trajectory_distance_risk_rises_fast_then_saturates(self) -> None:
        assessment = assess_collision_risk(
            make_target(class_name="car", x_m=1.5, z_m=4.0, vz_mps=-4.0),
            RiskModelConfig(
                warning_corridor_half_width_m=3.0,
                weights=RiskWeights(trajectory=1.0, ttc=0.0, drac=0.0, closing=0.0),
            ),
        )

        self.assertAlmostEqual(0.75, assessment.score, places=3)

    def test_ttc_risk_uses_saturating_curve_between_emergency_and_safe_time(self) -> None:
        assessment = assess_collision_risk(
            make_target(class_name="car", x_m=0.0, z_m=5.0, vz_mps=-1.538461538),
            RiskModelConfig(weights=RiskWeights(trajectory=0.0, ttc=1.0, drac=0.0, closing=0.0)),
        )

        self.assertAlmostEqual(3.25, assessment.ttc_s, places=3)
        self.assertAlmostEqual(0.75, assessment.score, places=3)

    def test_vehicle_risk_multiplier_changes_final_score_by_class(self) -> None:
        config = RiskModelConfig(
            warning_corridor_half_width_m=3.0,
            in_path_depth_m=0.1,
            weights=RiskWeights(trajectory=1.0, ttc=0.0, drac=0.0, closing=0.0),
        )

        car = assess_collision_risk(make_target(class_name="car", x_m=2.0, z_m=4.0, vz_mps=-4.0), config)
        truck = assess_collision_risk(make_target(class_name="truck", x_m=2.0, z_m=4.0, vz_mps=-4.0), config)

        self.assertAlmostEqual(0.556, car.score, places=3)
        self.assertGreater(truck.score, car.score)

    def test_radial_closing_speed_uses_full_motion_vector(self) -> None:
        assessment = assess_collision_risk(make_target(x_m=3.0, z_m=4.0, vx_mps=-3.0, vz_mps=-4.0))

        self.assertAlmostEqual(5.0, assessment.closing_speed_mps, places=3)

    def test_sideways_pass_with_safe_trajectory_distance_stays_safe(self) -> None:
        assessment = assess_collision_risk(make_target(x_m=4.0, z_m=8.0, vx_mps=3.0, vz_mps=-1.0))

        self.assertEqual(RiskLevel.SAFE, assessment.level)
        self.assertGreater(assessment.trajectory_distance_m, 3.0)

    def test_non_negative_vz_inside_front_corridor_is_not_forced_safe(self) -> None:
        assessment = assess_collision_risk(make_target(x_m=0.2, z_m=1.0, vx_mps=-2.0, vz_mps=0.0))

        self.assertGreaterEqual(assessment.level.value, RiskLevel.ATTENTION.value)
        self.assertIn(assessment.motion_pattern, (MotionPattern.LATERAL_CUT_IN, MotionPattern.HEAD_ON_OR_CLOSING))
        self.assertGreater(assessment.closing_speed_mps, 0.0)

    def test_low_velocity_confidence_cut_in_is_downgraded_to_uncertain(self) -> None:
        assessment = assess_collision_risk(
            make_target(x_m=3.0, z_m=3.0, vx_mps=-0.7, vz_mps=-0.7, velocity_confidence=0.05)
        )

        self.assertEqual(MotionPattern.STATIC_OR_UNCERTAIN, assessment.motion_pattern)
        self.assertLess(assessment.trajectory_distance_m, 0.5)
        self.assertLessEqual(assessment.level.value, RiskLevel.ATTENTION.value)

    def test_cut_in_short_ttc_needs_stable_velocity_for_caution_floor(self) -> None:
        assessment = assess_collision_risk(
            make_target(x_m=3.0, z_m=3.0, vx_mps=-1.0, vz_mps=-1.0, velocity_confidence=0.05)
        )

        self.assertNotEqual(MotionPattern.LATERAL_CUT_IN, assessment.motion_pattern)
        self.assertLess(assessment.ttc_s, 3.5)
        self.assertLessEqual(assessment.level.value, RiskLevel.ATTENTION.value)

    def test_near_static_or_slow_target_has_static_obstacle_risk(self) -> None:
        assessment = assess_collision_risk(
            make_target(x_m=0.0, z_m=0.5, vx_mps=0.0, vz_mps=1.0),
            RiskModelConfig(weights=RiskWeights(trajectory=1.0, ttc=0.0, drac=0.0, closing=0.0)),
        )

        self.assertGreaterEqual(assessment.level.value, RiskLevel.ATTENTION.value)
        self.assertGreater(assessment.static_obstacle_risk, 0.0)

    def test_near_static_target_under_two_meters_is_not_safe(self) -> None:
        assessment = assess_collision_risk(make_target(x_m=0.0, z_m=1.4, vx_mps=0.0, vz_mps=0.0))

        self.assertEqual(MotionPattern.NEAR_STATIC_OBSTACLE, assessment.motion_pattern)
        self.assertGreaterEqual(assessment.level.value, RiskLevel.ATTENTION.value)

    def test_low_velocity_confidence_does_not_zero_closing_risk(self) -> None:
        assessment = assess_collision_risk(
            make_target(x_m=1.0, z_m=4.0, vx_mps=0.0, vz_mps=-4.0, velocity_confidence=0.05)
        )

        self.assertGreaterEqual(assessment.level.value, RiskLevel.ATTENTION.value)
        self.assertGreater(assessment.score, 0.0)

    def test_slow_head_on_bicycle_does_not_become_red(self) -> None:
        assessment = assess_collision_risk(make_target(class_name="bicycle", z_m=3.2, vz_mps=-0.45))

        self.assertLess(assessment.level.value, RiskLevel.DANGER.value)
        self.assertLess(assessment.closing_speed_mps, 0.8)

    def test_detection_confidence_does_not_change_risk_score(self) -> None:
        high_confidence = assess_collision_risk(make_target(x_m=1.0, z_m=4.0, vz_mps=-4.0, confidence=0.95))
        low_confidence = assess_collision_risk(make_target(x_m=1.0, z_m=4.0, vz_mps=-4.0, confidence=0.10))

        self.assertAlmostEqual(high_confidence.score, low_confidence.score, places=6)

    def test_stateful_model_does_not_hold_emergency_after_safe_trajectory_frame(self) -> None:
        model = RiskModel(RiskModelConfig())
        high = model.assess(make_target(z_m=4.0, vz_mps=-12.0, timestamp_s=1.0))
        safe_next_frame = model.assess(make_target(x_m=3.5, z_m=4.0, vz_mps=-12.0, timestamp_s=1.2))

        self.assertEqual(RiskLevel.EMERGENCY, high.level)
        self.assertEqual(RiskLevel.SAFE, safe_next_frame.level)

    def test_receding_motion_clears_stateful_warning(self) -> None:
        model = RiskModel(RiskModelConfig())
        model.assess(make_target(z_m=4.0, vz_mps=-12.0, timestamp_s=1.0))
        receding = model.assess(make_target(z_m=5.0, vz_mps=1.0, timestamp_s=1.2))

        self.assertEqual(RiskLevel.SAFE, receding.level)

    def test_weights_are_configurable_for_the_remaining_risk_terms(self) -> None:
        target = make_target(x_m=2.5, z_m=4.0, vz_mps=-12.0)
        normal = assess_collision_risk(target)
        trajectory_only = assess_collision_risk(
            target,
            RiskModelConfig(weights=RiskWeights(trajectory=1.0, ttc=0.0, drac=0.0, closing=0.0)),
        )

        self.assertNotEqual(round(normal.score, 3), round(trajectory_only.score, 3))


if __name__ == "__main__":
    unittest.main()
