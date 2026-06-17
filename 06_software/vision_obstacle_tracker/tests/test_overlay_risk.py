import unittest

from risk_model import RiskAssessment, RiskLevel
from vision_obstacle_tracker import RiskWarningStabilizer, risk_color_bgr, risk_level_name


def make_assessment(level: RiskLevel, score: float) -> RiskAssessment:
    return RiskAssessment(
        track_id=7,
        score=score,
        level=level,
        ttc_s=0.5,
        trajectory_distance_m=0.0,
        drac_mps2=4.0,
        closing_speed_mps=8.0,
    )


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

    def test_warning_level_waits_for_four_recent_frames_before_displaying_warning(self) -> None:
        stabilizer = RiskWarningStabilizer(min_warning_frames=3)
        warning = make_assessment(RiskLevel.EMERGENCY, 0.92)

        first = stabilizer.stabilize({7: warning})[7]
        second = stabilizer.stabilize({7: warning})[7]
        third = stabilizer.stabilize({7: warning})[7]
        fourth = stabilizer.stabilize({7: warning})[7]

        self.assertEqual(RiskLevel.SAFE, first.level)
        self.assertEqual(RiskLevel.SAFE, second.level)
        self.assertEqual(RiskLevel.SAFE, third.level)
        self.assertEqual(RiskLevel.EMERGENCY, fourth.level)
        self.assertEqual(0.0, first.score)
        self.assertEqual(0.92, fourth.score)

    def test_warning_level_uses_minimum_score_from_closest_three_of_last_four_frames(self) -> None:
        stabilizer = RiskWarningStabilizer(min_warning_frames=3)
        first = make_assessment(RiskLevel.ATTENTION, 0.50)
        second = make_assessment(RiskLevel.EMERGENCY, 0.80)
        third = make_assessment(RiskLevel.ATTENTION, 0.55)
        fourth = make_assessment(RiskLevel.ATTENTION, 0.54)

        first_display = stabilizer.stabilize({7: first})[7]
        second_display = stabilizer.stabilize({7: second})[7]
        third_display = stabilizer.stabilize({7: third})[7]
        fourth_display = stabilizer.stabilize({7: fourth})[7]

        self.assertEqual(RiskLevel.SAFE, first_display.level)
        self.assertEqual(RiskLevel.SAFE, second_display.level)
        self.assertEqual(RiskLevel.SAFE, third_display.level)
        self.assertEqual(RiskLevel.ATTENTION, fourth_display.level)
        self.assertEqual(0.50, fourth_display.score)

    def test_single_safe_outlier_does_not_force_safe_when_three_closest_scores_are_dangerous(self) -> None:
        stabilizer = RiskWarningStabilizer(min_warning_frames=3)

        stabilizer.stabilize({7: make_assessment(RiskLevel.SAFE, 0.10)})
        stabilizer.stabilize({7: make_assessment(RiskLevel.EMERGENCY, 0.90)})
        stabilizer.stabilize({7: make_assessment(RiskLevel.EMERGENCY, 0.91)})
        fourth = stabilizer.stabilize({7: make_assessment(RiskLevel.EMERGENCY, 0.89)})[7]

        self.assertEqual(RiskLevel.EMERGENCY, fourth.level)
        self.assertEqual(0.89, fourth.score)

    def test_warning_level_can_jump_to_emergency_when_last_three_scores_all_support_it(self) -> None:
        stabilizer = RiskWarningStabilizer(min_warning_frames=3)

        stabilizer.stabilize({7: make_assessment(RiskLevel.EMERGENCY, 0.90)})
        stabilizer.stabilize({7: make_assessment(RiskLevel.EMERGENCY, 0.91)})
        stabilizer.stabilize({7: make_assessment(RiskLevel.EMERGENCY, 0.88)})
        fourth = stabilizer.stabilize({7: make_assessment(RiskLevel.EMERGENCY, 0.89)})[7]

        self.assertEqual(RiskLevel.EMERGENCY, fourth.level)
        self.assertEqual(0.89, fourth.score)

    def test_two_safe_scores_keep_display_safe_against_one_warning_score(self) -> None:
        stabilizer = RiskWarningStabilizer(min_warning_frames=3)
        warning = make_assessment(RiskLevel.DANGER, 0.72)
        safe = make_assessment(RiskLevel.SAFE, 0.0)

        stabilizer.stabilize({7: warning})
        stabilizer.stabilize({7: safe})
        stabilizer.stabilize({7: safe})
        fourth = stabilizer.stabilize({7: safe})[7]

        self.assertEqual(RiskLevel.SAFE, fourth.level)
        self.assertEqual(0.0, fourth.score)


if __name__ == "__main__":
    unittest.main()
