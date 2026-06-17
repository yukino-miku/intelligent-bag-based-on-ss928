import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radar_protocol import RadarTarget
from risk import classify_area, evaluate_target, summarize_targets


class RiskTest(unittest.TestCase):
    def test_classifies_target_area_by_angle(self):
        self.assertEqual(classify_area(-30), "left")
        self.assertEqual(classify_area(-15), "center")
        self.assertEqual(classify_area(0), "center")
        self.assertEqual(classify_area(15), "center")
        self.assertEqual(classify_area(30), "right")

    def test_evaluates_risk_from_distance_and_velocity(self):
        emergency = evaluate_target(RadarTarget(1, 0, 0, 1))
        high = evaluate_target(RadarTarget(2, 10, 3, 2))
        medium = evaluate_target(RadarTarget(4, -10, 1, 3))
        low = evaluate_target(RadarTarget(7, 30, 0, 4))
        safe = evaluate_target(RadarTarget(12, 30, 0, 5))

        self.assertEqual(emergency.risk_level, "emergency")
        self.assertEqual(high.risk_level, "high")
        self.assertEqual(medium.risk_level, "medium")
        self.assertEqual(low.risk_level, "low")
        self.assertEqual(safe.risk_level, "safe")

    def test_summarizes_highest_risk_per_area(self):
        targets = [
            RadarTarget(7, -25, 1, 1),
            RadarTarget(2, -25, 1, 2),
            RadarTarget(3, 25, 0, 3),
        ]

        summary = summarize_targets(targets)

        self.assertEqual(summary["left"].target.target_id, 2)
        self.assertEqual(summary["left"].risk_level, "high")
        self.assertEqual(summary["right"].target.target_id, 3)
        self.assertIsNone(summary["center"])


if __name__ == "__main__":
    unittest.main()
