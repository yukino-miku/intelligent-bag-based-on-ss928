import unittest

from calibration import GroundPoint
from risk_model import CorridorZone, MotionPattern, RiskLevel, assess_collision_risk, corridor_zone_name
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

    def test_remote_cross_traffic_is_not_caution_even_when_infinite_line_passes_origin(self) -> None:
        assessment = assess_collision_risk(
            make_target(class_name="car", x_m=11.0, z_m=8.0, vx_mps=-5.0, vz_mps=-3.5)
        )

        self.assertEqual(CorridorZone.REMOTE_TRAFFIC, assessment.corridor_zone)
        self.assertLessEqual(assessment.level.value, RiskLevel.ATTENTION.value)
        self.assertIn("remote_traffic", assessment.risk_cap_reason)

    def test_fast_car_entering_front_path_is_danger(self) -> None:
        assessment = assess_collision_risk(
            make_target(class_name="car", x_m=0.5, z_m=5.0, vx_mps=0.0, vz_mps=-3.0)
        )

        self.assertEqual(CorridorZone.IN_PATH, assessment.corridor_zone)
        self.assertGreaterEqual(assessment.level.value, RiskLevel.DANGER.value)
        self.assertLess(assessment.cpa_time_s, 2.0)
        self.assertLess(assessment.cpa_distance_m, 0.8)

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


if __name__ == "__main__":
    unittest.main()
