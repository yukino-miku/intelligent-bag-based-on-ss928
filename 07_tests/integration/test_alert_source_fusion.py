import argparse
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = ROOT / "06_software" / "board_runtime" / "smartbag_alert_controller"
if str(CONTROLLER) not in sys.path:
    sys.path.insert(0, str(CONTROLLER))

from alert_core import AlertEvent, AlertState
from output_policy import OutputPolicy
from smartbag_alert_controller import (
    PwmController,
    build_actuator_runtime,
    should_publish_alert_history,
)


class AlertSourceFusionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = AlertState(
            event_timeout_s=5.0,
            source_timeouts_s={"vision": 1.0, "radar": 2.0, "manual": 3.0},
        )

    def event(self, source: str, side: str, level: int, kind: str = "state_change") -> AlertEvent:
        return AlertEvent(side=side, level=level, source=source, event_kind=kind)

    def test_max_by_side_and_source_clear(self) -> None:
        self.state.apply_event(self.event("vision:left", "left", 2), now=0.0)
        output = self.state.apply_event(self.event("radar:left_rear", "left", 3), now=0.1)
        self.assertEqual(3, output.levels["left"])

        output = self.state.apply_event(self.event("radar:left_rear", "left", 0), now=0.2)
        self.assertEqual(2, output.levels["left"])
        self.assertEqual({"left": 2}, self.state.source_snapshot()["vision:left"])

    def test_weaker_source_does_not_lower_effective_level(self) -> None:
        self.state.apply_event(self.event("vision:right", "right", 4), now=0.0)
        output = self.state.apply_event(self.event("radar:right_rear", "right", 2), now=0.1)
        self.assertEqual(4, output.levels["right"])

    def test_left_source_does_not_affect_right(self) -> None:
        output = self.state.apply_event(self.event("radar:left_rear", "left", 3), now=0.0)
        self.assertEqual({"left": 3, "right": 0}, output.levels)

    def test_source_timeout_only_removes_expired_source(self) -> None:
        self.state.apply_event(self.event("vision:left", "left", 2), now=0.0)
        self.state.apply_event(self.event("radar:left_rear", "left", 3), now=0.5)
        output = self.state.expire(now=1.1)
        self.assertEqual(3, output.levels["left"])
        self.assertEqual(("vision:left",), output.expired_sources)
        self.assertEqual((("vision:left", "left"),), output.expired_source_sides)

    def test_detector_exit_clear_preserves_radar(self) -> None:
        self.state.apply_event(self.event("vision:right", "right", 4), now=0.0)
        self.state.apply_event(self.event("radar:right_rear", "right", 2), now=0.1)
        output = self.state.apply_event(
            AlertEvent("right", 0, source="vision:right", clear_reason="detector_exit"),
            now=0.2,
        )
        self.assertEqual(2, output.levels["right"])

    def test_radar_exit_clear_preserves_vision(self) -> None:
        self.state.apply_event(self.event("vision:left", "left", 2), now=0.0)
        self.state.apply_event(self.event("radar:left_rear", "left", 3), now=0.1)
        output = self.state.apply_event(
            AlertEvent("left", 0, source="radar:left_rear", clear_reason="radar_exit"),
            now=0.2,
        )
        self.assertEqual(2, output.levels["left"])

    def test_manual_clear_explicitly_clears_all_sources(self) -> None:
        self.state.apply_event(self.event("vision:left", "left", 2), now=0.0)
        self.state.apply_event(self.event("radar:right_rear", "right", 3), now=0.1)
        self.state.clear()
        self.assertEqual({"left": 0, "right": 0}, self.state.levels_by_side)
        self.assertEqual({}, self.state.source_snapshot())

    def test_heartbeat_is_not_history(self) -> None:
        self.assertFalse(should_publish_alert_history(self.event("radar:right_rear", "right", 2, "heartbeat")))
        self.assertTrue(should_publish_alert_history(self.event("radar:right_rear", "right", 2)))


class OutputPolicyTest(unittest.TestCase):
    def test_rev2_profile_builds_dry_run_backends(self) -> None:
        hardware = json.loads(
            (ROOT / "09_deliverables/board_deploy/hardware-profiles/rev2_tm6605_mr20.json")
            .read_text(encoding="utf-8")
        )
        args = argparse.Namespace(
            disable_haptics=False,
            disable_lights=False,
            dry_run=True,
            pwm_root="/not-used",
        )
        legacy_pwm = PwmController(Path("/not-used"), dry_run=True)
        haptics, lights, policy = build_actuator_runtime(hardware, args, legacy_pwm)
        haptics.initialize()
        lights.initialize()
        decision = policy.decide({"left": 3, "right": 4})
        haptics.apply_levels(decision.haptic_levels)
        lights.apply_levels(decision.light_levels)
        self.assertEqual("dry_run", haptics.status()["detail"]["backend"])
        self.assertEqual("pwm_lights", lights.status()["detail"]["backend"])

    def test_rev2_levels_one_and_two_do_not_drive_actuators(self) -> None:
        policy = OutputPolicy.for_profile("rev2_tm6605_mr20")
        decision = policy.decide({"left": 1, "right": 2}, audio_clip="R2")
        self.assertEqual({"left": 0, "right": 0}, decision.haptic_levels)
        self.assertEqual({"left": 0, "right": 0}, decision.light_levels)
        self.assertIsNone(decision.audio_clip)

    def test_rev2_levels_three_and_four_drive_matching_sides(self) -> None:
        policy = OutputPolicy.for_profile("rev2_tm6605_mr20")
        decision = policy.decide({"left": 3, "right": 4}, audio_clip="R4")
        self.assertEqual({"left": 3, "right": 4}, decision.haptic_levels)
        self.assertEqual({"left": 3, "right": 4}, decision.light_levels)
        self.assertEqual("R4", decision.audio_clip)

    def test_legacy_profile_preserves_all_levels(self) -> None:
        policy = OutputPolicy.for_profile("legacy_pwm_haptics")
        decision = policy.decide({"left": 1, "right": 2})
        self.assertEqual({"left": 1, "right": 2}, decision.haptic_levels)


if __name__ == "__main__":
    unittest.main()
