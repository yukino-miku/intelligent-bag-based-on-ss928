import unittest

from calibration import GroundPoint
from risk_model import (
    CorridorZone,
    MotionPattern,
    RiskLevel,
    assess_collision_risk,
    corridor_zone_name,
    warning_action_for_level,
)
from vision_core import TrackedObject


def make_target(
    class_name: str = "car",
    x_m: float = 0.0,
    z_m: float = 4.0,
    vx_mps: float = 0.0,
    vz_mps: float = 0.0,
    track_age_frames: int = 10,
    velocity_confidence: float = 1.0,
    distance_confidence: float = 1.0,
    motion_quality_flags: tuple[str, ...] = (),
) -> TrackedObject:
    point = GroundPoint(x_m=x_m, z_m=z_m)
    speed_mps = (vx_mps**2 + vz_mps**2) ** 0.5
    return TrackedObject(
        track_id=23,
        class_name=class_name,
        confidence=0.90,
        bbox_xyxy=(10, 20, 110, 220),
        ground_point=point,
        distance_m=point.distance_m,
        vx_mps=vx_mps,
        vz_mps=vz_mps,
        speed_mps=speed_mps,
        timestamp_s=1.0,
        distance_source="fused",
        distance_confidence=distance_confidence,
        velocity_confidence=velocity_confidence,
        motion_quality_flags=motion_quality_flags,
        track_age_frames=track_age_frames,
    )


class RealWorldRiskSemanticsTest(unittest.TestCase):
    def test_warning_actions_match_vibration_semantics(self) -> None:
        self.assertEqual("none", warning_action_for_level(RiskLevel.SAFE))
        self.assertEqual("short_weak_pulse", warning_action_for_level(RiskLevel.ATTENTION))
        self.assertEqual("medium_interval_pulse", warning_action_for_level(RiskLevel.CAUTION))
        self.assertEqual("strong_fast_pulse", warning_action_for_level(RiskLevel.DANGER))
        self.assertEqual("continuous_high_frequency", warning_action_for_level(RiskLevel.EMERGENCY))

    def test_assessment_reports_cpa_and_corridor_zone(self) -> None:
        assessment = assess_collision_risk(
            make_target(class_name="bicycle", x_m=1.5, z_m=2.5, vx_mps=-1.0, vz_mps=-1.5)
        )

        self.assertTrue(assessment.cpa_valid)
        self.assertLess(assessment.cpa_time_s, 2.0)
        self.assertLess(assessment.cpa_distance_m, 0.8)
        self.assertEqual(CorridorZone.NEAR_SIDE, assessment.corridor_zone)
        self.assertEqual("SIDE", corridor_zone_name(assessment.corridor_zone))

    def test_roadside_static_motorcycle_is_not_caution(self) -> None:
        assessment = assess_collision_risk(
            make_target(class_name="motorcycle", x_m=-2.5, z_m=4.0, vx_mps=0.0, vz_mps=0.0)
        )

        self.assertLessEqual(assessment.level.value, RiskLevel.ATTENTION.value)
        self.assertIn(assessment.corridor_zone, (CorridorZone.NEAR_SIDE, CorridorZone.SIDE_STATIC))
        self.assertIn(assessment.motion_pattern, (MotionPattern.STATIC_OR_UNCERTAIN, MotionPattern.SIDE_STATIC))

    def test_slow_side_bicycle_that_does_not_enter_path_is_capped_to_attention(self) -> None:
        assessment = assess_collision_risk(
            make_target(class_name="bicycle", x_m=2.0, z_m=4.0, vx_mps=0.0, vz_mps=-0.6)
        )

        self.assertLessEqual(assessment.level.value, RiskLevel.ATTENTION.value)
        self.assertIn("low_speed", assessment.risk_cap_reason)

    def test_bicycle_crossing_into_personal_space_reaches_caution(self) -> None:
        assessment = assess_collision_risk(
            make_target(class_name="bicycle", x_m=1.5, z_m=2.5, vx_mps=-1.0, vz_mps=-1.5)
        )

        self.assertEqual(MotionPattern.LATERAL_CUT_IN, assessment.motion_pattern)
        self.assertGreaterEqual(assessment.level.value, RiskLevel.CAUTION.value)
        self.assertLess(assessment.cpa_time_s, 2.0)
        self.assertLess(assessment.cpa_distance_m, 0.8)

    def test_remote_cross_traffic_without_path_conflict_is_not_caution(self) -> None:
        assessment = assess_collision_risk(
            make_target(class_name="car", x_m=11.0, z_m=8.0, vx_mps=-5.0, vz_mps=0.0)
        )

        self.assertEqual(CorridorZone.REMOTE_TRAFFIC, assessment.corridor_zone)
        self.assertLessEqual(assessment.level.value, RiskLevel.ATTENTION.value)
        self.assertIn("remote_traffic_no_path_conflict", assessment.risk_cap_reason)

    def test_remote_lateral_car_not_entering_path_is_not_caution(self) -> None:
        assessment = assess_collision_risk(
            make_target(class_name="car", x_m=6.0, z_m=8.0, vx_mps=-2.0, vz_mps=0.0)
        )

        self.assertEqual(CorridorZone.REMOTE_TRAFFIC, assessment.corridor_zone)
        self.assertLessEqual(assessment.level.value, RiskLevel.ATTENTION.value)
        self.assertEqual("large_vehicle", assessment.severity_class)
        self.assertIn("remote_traffic_no_path_conflict", assessment.risk_cap_reason)

    def test_remote_large_vehicle_path_conflict_is_warned_early(self) -> None:
        assessment = assess_collision_risk(
            make_target(class_name="car", x_m=4.0, z_m=7.0, vx_mps=-1.0, vz_mps=-1.5)
        )

        self.assertEqual(CorridorZone.REMOTE_TRAFFIC, assessment.corridor_zone)
        self.assertTrue(assessment.cpa_valid)
        self.assertLessEqual(assessment.cpa_time_s, 5.0)
        self.assertLess(assessment.cpa_distance_m, 1.2)
        self.assertGreaterEqual(assessment.level.value, RiskLevel.ATTENTION.value)
        self.assertIn("remote_large_vehicle_path_conflict", assessment.risk_cap_reason)
        self.assertIn("large_vehicle", assessment.risk_action_reason)

    def test_large_vehicle_inside_personal_space_in_three_seconds_is_danger(self) -> None:
        assessment = assess_collision_risk(
            make_target(class_name="car", x_m=0.4, z_m=5.4, vx_mps=0.0, vz_mps=-2.0)
        )

        self.assertEqual("large_vehicle", assessment.severity_class)
        self.assertGreaterEqual(assessment.level.value, RiskLevel.DANGER.value)
        self.assertLessEqual(assessment.cpa_time_s, 3.0)
        self.assertLess(assessment.cpa_distance_m, assessment.warning_radius_m)

    def test_bus_or_truck_path_conflict_at_four_to_five_seconds_is_caution(self) -> None:
        assessment = assess_collision_risk(
            make_target(class_name="truck", x_m=0.8, z_m=7.5, vx_mps=0.0, vz_mps=-1.7)
        )

        self.assertEqual("large_vehicle", assessment.severity_class)
        self.assertGreaterEqual(assessment.level.value, RiskLevel.CAUTION.value)
        self.assertLessEqual(assessment.cpa_time_s, 4.8)
        self.assertIn("large_vehicle", assessment.risk_action_reason)

    def test_fast_car_entering_front_path_is_danger(self) -> None:
        assessment = assess_collision_risk(
            make_target(class_name="car", x_m=0.5, z_m=5.0, vx_mps=0.0, vz_mps=-3.0)
        )

        self.assertEqual(CorridorZone.IN_PATH, assessment.corridor_zone)
        self.assertGreaterEqual(assessment.level.value, RiskLevel.DANGER.value)
        self.assertLess(assessment.cpa_time_s, 2.0)
        self.assertLess(assessment.cpa_distance_m, 0.8)

    def test_bicycle_crossing_into_personal_space_in_two_to_three_seconds_is_caution(self) -> None:
        assessment = assess_collision_risk(
            make_target(class_name="bicycle", x_m=1.8, z_m=3.0, vx_mps=-0.8, vz_mps=-1.0)
        )

        self.assertEqual("small_rider", assessment.severity_class)
        self.assertGreaterEqual(assessment.level.value, RiskLevel.CAUTION.value)
        self.assertLess(assessment.level.value, RiskLevel.DANGER.value)
        self.assertLessEqual(assessment.cpa_time_s, 3.0)
        self.assertLess(assessment.cpa_distance_m, assessment.warning_radius_m)

    def test_fast_motorcycle_entering_personal_space_in_two_seconds_is_danger(self) -> None:
        assessment = assess_collision_risk(
            make_target(class_name="motorcycle", x_m=1.5, z_m=3.5, vx_mps=-1.5, vz_mps=-2.5)
        )

        self.assertEqual("small_rider", assessment.severity_class)
        self.assertGreaterEqual(assessment.level.value, RiskLevel.DANGER.value)
        self.assertLessEqual(assessment.cpa_time_s, 2.0)
        self.assertLess(assessment.cpa_distance_m, assessment.warning_radius_m)

    def test_current_distance_inside_personal_space_is_emergency(self) -> None:
        assessment = assess_collision_risk(
            make_target(class_name="car", x_m=0.2, z_m=0.5, vx_mps=0.0, vz_mps=0.0)
        )

        self.assertEqual(RiskLevel.EMERGENCY, assessment.level)
        self.assertEqual("continuous_high_frequency", assessment.warning_action)
        self.assertIn("current_personal_space", assessment.risk_action_reason)

    def test_short_or_unstable_track_is_capped_unless_currently_inside_personal_space(self) -> None:
        assessment = assess_collision_risk(
            make_target(
                class_name="car",
                x_m=0.4,
                z_m=4.0,
                vx_mps=0.0,
                vz_mps=-5.0,
                track_age_frames=1,
                velocity_confidence=0.2,
                motion_quality_flags=("unstable_velocity",),
            )
        )

        self.assertLessEqual(assessment.level.value, RiskLevel.ATTENTION.value)
        self.assertIn("unstable_track", assessment.risk_cap_reason)

    def test_short_unstable_track_with_extreme_cpa_is_not_danger_unless_extremely_close(self) -> None:
        assessment = assess_collision_risk(
            make_target(
                class_name="truck",
                x_m=0.2,
                z_m=4.5,
                vx_mps=0.0,
                vz_mps=-6.0,
                track_age_frames=1,
                velocity_confidence=0.1,
                motion_quality_flags=("unstable_velocity", "speed_spike"),
            )
        )

        self.assertLessEqual(assessment.level.value, RiskLevel.ATTENTION.value)
        self.assertIn("unstable_track", assessment.risk_cap_reason)


if __name__ == "__main__":
    unittest.main()
