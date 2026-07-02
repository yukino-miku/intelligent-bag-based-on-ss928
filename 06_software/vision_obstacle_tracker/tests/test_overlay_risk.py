from types import SimpleNamespace
import unittest

from risk_model import RiskAssessment, RiskLevel
from vision_obstacle_tracker import (
    RiskWarningStabilizer,
    RiskWarningStabilizerConfig,
    risk_color_bgr,
    risk_level_name,
)


def make_assessment(level: RiskLevel, score: float, ttc_s: float | None = 2.0) -> RiskAssessment:
    return RiskAssessment(
        track_id=7,
        score=score,
        level=level,
        ttc_s=ttc_s,
        trajectory_distance_m=0.0,
        drac_mps2=4.0,
        closing_speed_mps=8.0,
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

    def test_fast_path_emergency_can_display_immediately_for_short_ttc(self) -> None:
        stabilizer = RiskWarningStabilizer()
        emergency = make_assessment(RiskLevel.EMERGENCY, 0.92, ttc_s=0.4)

        display = stabilizer.stabilize({7: emergency}, {7: make_target(quality=0.3)})[7]

        self.assertEqual(RiskLevel.EMERGENCY, display.level)
        self.assertEqual(0.92, display.score)

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
