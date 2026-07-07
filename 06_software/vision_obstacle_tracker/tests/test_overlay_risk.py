from types import SimpleNamespace
import unittest

from risk_model import CorridorZone, MotionPattern, RiskAssessment, RiskLevel
from vision_obstacle_tracker import (
    RiskWarningStabilizer,
    RiskWarningStabilizerConfig,
    risk_color_bgr,
    risk_level_name,
)


def make_assessment(
    level: RiskLevel,
    score: float,
    ttc_s: float | None = 2.0,
    motion_pattern: MotionPattern = MotionPattern.HEAD_ON_OR_CLOSING,
    trajectory_distance_m: float | None = 0.0,
    cpa_time_s: float | None = 1.5,
    cpa_distance_m: float | None = 0.5,
    severity_class: str = "large_vehicle",
    risk_action_reason: str = "large_vehicle_path_conflict",
) -> RiskAssessment:
    return RiskAssessment(
        track_id=7,
        score=score,
        level=level,
        ttc_s=ttc_s,
        trajectory_distance_m=trajectory_distance_m,
        cpa_time_s=cpa_time_s,
        cpa_distance_m=cpa_distance_m,
        cpa_valid=cpa_time_s is not None and cpa_distance_m is not None,
        drac_mps2=4.0,
        closing_speed_mps=8.0,
        motion_pattern=motion_pattern,
        corridor_zone=CorridorZone.IN_PATH,
        severity_class=severity_class,
        warning_action="none",
        warning_time_horizon_s=6.0,
        warning_radius_m=2.4,
        risk_action_reason=risk_action_reason,
    )


def make_target(quality: float = 1.0, distance_m: float = 5.0):
    return SimpleNamespace(track_id=7, observation_quality=quality, distance_m=distance_m)


class OverlayRiskTest(unittest.TestCase):
    def test_warning_level_colors_match_requested_palette(self) -> None:
        self.assertEqual((0, 255, 255), risk_color_bgr(RiskLevel.ATTENTION))
        self.assertEqual((0, 191, 255), risk_color_bgr(RiskLevel.CAUTION))
        self.assertEqual((0, 80, 255), risk_color_bgr(RiskLevel.DANGER))
        self.assertEqual((0, 0, 255), risk_color_bgr(RiskLevel.EMERGENCY))

    def test_warning_level_names_are_stable_for_overlay(self) -> None:
        self.assertEqual("ATTENTION", risk_level_name(RiskLevel.ATTENTION))
        self.assertEqual("CAUTION", risk_level_name(RiskLevel.CAUTION))
        self.assertEqual("DANGER", risk_level_name(RiskLevel.DANGER))
        self.assertEqual("EMERGENCY", risk_level_name(RiskLevel.EMERGENCY))

    def test_low_quality_high_risk_single_frame_does_not_immediately_display_danger(self) -> None:
        stabilizer = RiskWarningStabilizer(
            RiskWarningStabilizerConfig(min_confirm_frames_danger=2, low_quality_extra_frames=2)
        )
        danger = make_assessment(RiskLevel.DANGER, 0.72)

        display = stabilizer.stabilize({7: danger}, {7: make_target(quality=0.2)})[7]

        self.assertEqual(RiskLevel.SAFE, display.level)
        self.assertEqual(0.0, display.score)

    def test_attention_displays_on_first_frame(self) -> None:
        stabilizer = RiskWarningStabilizer()
        attention = make_assessment(RiskLevel.ATTENTION, 0.45)

        display = stabilizer.stabilize({7: attention}, {7: make_target(quality=0.8)})[7]

        self.assertEqual(RiskLevel.ATTENTION, display.level)

    def test_high_quality_cut_in_caution_needs_two_confirmed_frames(self) -> None:
        stabilizer = RiskWarningStabilizer()
        caution = make_assessment(
            RiskLevel.CAUTION,
            0.62,
            ttc_s=3.2,
            motion_pattern=MotionPattern.LATERAL_CUT_IN,
            trajectory_distance_m=0.25,
        )

        first = stabilizer.stabilize({7: caution}, {7: make_target(quality=0.85)})[7]
        second = stabilizer.stabilize({7: caution}, {7: make_target(quality=0.85)})[7]

        self.assertEqual(RiskLevel.SAFE, first.level)
        self.assertEqual(RiskLevel.CAUTION, second.level)

    def test_stabilizer_reports_pending_reason_for_risk_log(self) -> None:
        stabilizer = RiskWarningStabilizer(
            RiskWarningStabilizerConfig(min_confirm_frames_danger=2, low_quality_extra_frames=1)
        )
        danger = make_assessment(RiskLevel.DANGER, 0.72)

        stabilizer.stabilize({7: danger}, {7: make_target(quality=0.2)})
        info = stabilizer.debug_info_by_track_id()[7]

        self.assertEqual(RiskLevel.DANGER, info.pending_level)
        self.assertEqual(1, info.pending_count)
        self.assertEqual(3, info.required_frames)
        self.assertIn("waiting", info.reason)

    def test_high_quality_consecutive_danger_frames_upgrade_display(self) -> None:
        stabilizer = RiskWarningStabilizer(
            RiskWarningStabilizerConfig(min_confirm_frames_danger=2, low_quality_extra_frames=2)
        )
        danger = make_assessment(RiskLevel.DANGER, 0.72)

        first = stabilizer.stabilize({7: danger}, {7: make_target(quality=0.95)})[7]
        second = stabilizer.stabilize({7: danger}, {7: make_target(quality=0.95)})[7]

        self.assertEqual(RiskLevel.SAFE, first.level)
        self.assertEqual(RiskLevel.DANGER, second.level)
        self.assertEqual(0.72, second.score)

    def test_default_danger_needs_three_confirmed_frames(self) -> None:
        stabilizer = RiskWarningStabilizer()
        danger = make_assessment(RiskLevel.DANGER, 0.72)

        first = stabilizer.stabilize({7: danger}, {7: make_target(quality=0.95)})[7]
        second = stabilizer.stabilize({7: danger}, {7: make_target(quality=0.95)})[7]
        third = stabilizer.stabilize({7: danger}, {7: make_target(quality=0.95)})[7]

        self.assertEqual(RiskLevel.SAFE, first.level)
        self.assertEqual(RiskLevel.SAFE, second.level)
        self.assertEqual(RiskLevel.DANGER, third.level)

    def test_low_quality_danger_needs_extra_confirmation_frames(self) -> None:
        stabilizer = RiskWarningStabilizer(
            RiskWarningStabilizerConfig(min_confirm_frames_danger=2, low_quality_extra_frames=2)
        )
        danger = make_assessment(RiskLevel.DANGER, 0.72)

        for _ in range(3):
            display = stabilizer.stabilize({7: danger}, {7: make_target(quality=0.2)})[7]
            self.assertEqual(RiskLevel.SAFE, display.level)
        fourth = stabilizer.stabilize({7: danger}, {7: make_target(quality=0.2)})[7]

        self.assertEqual(RiskLevel.DANGER, fourth.level)

    def test_low_quality_single_frame_short_ttc_emergency_does_not_fast_path(self) -> None:
        stabilizer = RiskWarningStabilizer()
        emergency = make_assessment(RiskLevel.EMERGENCY, 0.92, ttc_s=0.4)

        display = stabilizer.stabilize({7: emergency}, {7: make_target(quality=0.3)})[7]

        self.assertEqual(RiskLevel.SAFE, display.level)

    def test_fast_path_emergency_can_display_immediately_when_currently_inside_personal_space(self) -> None:
        stabilizer = RiskWarningStabilizer()
        emergency = make_assessment(RiskLevel.EMERGENCY, 0.92, ttc_s=None, cpa_time_s=None, cpa_distance_m=None)

        display = stabilizer.stabilize({7: emergency}, {7: make_target(quality=0.3, distance_m=0.5)})[7]

        self.assertEqual(RiskLevel.EMERGENCY, display.level)
        self.assertEqual(0.92, display.score)

    def test_single_frame_distance_or_velocity_jump_does_not_directly_show_danger(self) -> None:
        stabilizer = RiskWarningStabilizer()
        safe_far = make_assessment(RiskLevel.SAFE, 0.0, ttc_s=None, cpa_time_s=None, cpa_distance_m=None)
        jump_danger = make_assessment(RiskLevel.DANGER, 0.76, ttc_s=0.7, cpa_time_s=0.5, cpa_distance_m=0.2)

        first = stabilizer.stabilize({7: safe_far}, {7: make_target(quality=0.9, distance_m=10.0)})[7]
        jump = stabilizer.stabilize({7: jump_danger}, {7: make_target(quality=0.4, distance_m=2.0)})[7]
        recovered = stabilizer.stabilize({7: safe_far}, {7: make_target(quality=0.9, distance_m=10.0)})[7]

        self.assertEqual(RiskLevel.SAFE, first.level)
        self.assertEqual(RiskLevel.SAFE, jump.level)
        self.assertEqual(RiskLevel.SAFE, recovered.level)

    def test_one_safe_frame_does_not_drop_danger_to_safe_immediately(self) -> None:
        stabilizer = RiskWarningStabilizer(
            RiskWarningStabilizerConfig(min_confirm_frames_danger=1, downgrade_hold_frames=2)
        )
        danger = make_assessment(RiskLevel.DANGER, 0.72)
        safe = make_assessment(RiskLevel.SAFE, 0.0)

        stabilizer.stabilize({7: danger}, {7: make_target(quality=1.0)})
        first_safe_display = stabilizer.stabilize({7: safe}, {7: make_target(quality=1.0)})[7]

        self.assertEqual(RiskLevel.DANGER, first_safe_display.level)
        self.assertGreaterEqual(first_safe_display.score, 0.70)


if __name__ == "__main__":
    unittest.main()
