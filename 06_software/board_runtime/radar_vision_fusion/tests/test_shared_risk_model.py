from __future__ import annotations

import math
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
VISION = ROOT / "06_software" / "vision_obstacle_tracker"
sys.path.insert(0, str(VISION))

from calibration import GroundPoint  # noqa: E402
from risk_model import KinematicRiskTarget, RiskAssessment, RiskLevel, RiskModel, RiskModelConfig  # noqa: E402
from risk_stabilizer import RiskWarningStabilizer  # noqa: E402
from vision_core import TrackedObject  # noqa: E402


def kinematic(class_name: str) -> KinematicRiskTarget:
    return KinematicRiskTarget(
        track_id="radar:1:1", class_name=class_name, x_m=0.2, z_m=5.0, vx_mps=0.0, vz_mps=-2.0,
        distance_m=math.hypot(0.2, 5.0), speed_mps=2.0, track_age_frames=5,
        velocity_confidence=1.0, distance_confidence=1.0, observation_quality=1.0,
        approach_consistency=1.0, path_conflict_consistency=1.0,
    )


class SharedRiskModelTest(unittest.TestCase):
    def test_visual_and_radar_targets_use_identical_core_formula(self) -> None:
        radar_target = kinematic("car")
        visual_target = TrackedObject(
            track_id=1, class_name="car", confidence=0.9, bbox_xyxy=(0, 0, 1, 1),
            ground_point=GroundPoint(radar_target.x_m, radar_target.z_m), distance_m=radar_target.distance_m,
            vx_mps=radar_target.vx_mps, vz_mps=radar_target.vz_mps, speed_mps=radar_target.speed_mps,
            timestamp_s=1.0, track_age_frames=5, velocity_confidence=1.0, distance_confidence=1.0,
            observation_quality=1.0, approach_consistency=1.0, path_conflict_consistency=1.0,
        )
        model = RiskModel()
        radar = model.assess(radar_target)
        visual = model.assess(visual_target)
        self.assertAlmostEqual(visual.base_score, radar.base_score)
        self.assertAlmostEqual(visual.weighted_score, radar.weighted_score)
        self.assertEqual(visual.level, radar.level)

    def test_vehicle_multiplier_is_applied_once_and_unknown_is_one(self) -> None:
        model = RiskModel(RiskModelConfig())
        car = model.assess(kinematic("car"))
        truck = model.assess(kinematic("truck"))
        bicycle = model.assess(kinematic("bicycle"))
        unknown = model.assess(kinematic("unknown"))
        self.assertAlmostEqual(car.base_score, unknown.base_score)
        self.assertAlmostEqual(unknown.base_score, unknown.weighted_score)
        self.assertAlmostEqual(truck.weighted_score, min(1.0, truck.base_score * 1.10))
        self.assertAlmostEqual(bicycle.weighted_score, bicycle.base_score * 0.92)
        bus = model.assess(kinematic("bus"))
        self.assertAlmostEqual(bus.weighted_score, min(1.0, bus.base_score * 1.10))

    def test_moving_away_radar_target_stays_safe(self) -> None:
        target = kinematic("truck")
        target = KinematicRiskTarget(**{**target.__dict__, "vz_mps": 2.0, "distance_trend_mps": 2.0})
        assessment = RiskModel().assess(target)
        self.assertEqual("SAFE", assessment.level.name)

    def test_future_conflict_cpa_and_drac_use_radar_kinematics(self) -> None:
        target = replace(
            kinematic("car"),
            x_m=2.0,
            z_m=4.0,
            vx_mps=-1.0,
            vz_mps=-1.0,
            distance_m=math.hypot(2.0, 4.0),
            speed_mps=math.sqrt(2.0),
        )
        assessment = RiskModel().assess(target)
        self.assertTrue(assessment.path_conflict)
        self.assertTrue(assessment.cpa_valid)
        self.assertIsNotNone(assessment.cpa_time_s)
        self.assertGreaterEqual(assessment.drac_mps2, 0.0)

    def test_personal_space_emergency_is_not_suppressed_by_bicycle_weight(self) -> None:
        target = replace(
            kinematic("bicycle"),
            x_m=0.0,
            z_m=0.4,
            distance_m=0.4,
            vx_mps=0.0,
            vz_mps=-1.0,
            speed_mps=1.0,
        )
        assessment = RiskModel().assess(target)
        self.assertEqual(RiskLevel.EMERGENCY, assessment.level)

    def test_danger_confirmation_is_independent_per_radar_track(self) -> None:
        stabilizer = RiskWarningStabilizer()
        safe = lambda key: RiskAssessment(key, 0.0, RiskLevel.SAFE, None, None, 0.0, 0.0)
        danger = lambda key: RiskAssessment(
            key,
            0.75,
            RiskLevel.DANGER,
            1.5,
            0.2,
            1.0,
            2.0,
            path_conflict=True,
        )
        targets = {"a": kinematic("car"), "b": replace(kinematic("car"), track_id="b")}
        targets["a"] = replace(targets["a"], track_id="a")
        for risks in (
            {"a": danger("a"), "b": safe("b")},
            {"a": safe("a"), "b": danger("b")},
            {"a": danger("a"), "b": safe("b")},
        ):
            displayed = stabilizer.stabilize(risks, targets)
            self.assertNotEqual(RiskLevel.DANGER, displayed["a"].level)
            self.assertNotEqual(RiskLevel.DANGER, displayed["b"].level)
        for _index in range(3):
            displayed = stabilizer.stabilize({"a": danger("a"), "b": safe("b")}, targets)
        self.assertEqual(RiskLevel.DANGER, displayed["a"].level)
        self.assertEqual(RiskLevel.SAFE, displayed["b"].level)


if __name__ == "__main__":
    unittest.main()
