from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from alert_core import (  # noqa: E402
    DEFAULT_PWM_PERIOD_NS,
    AlertEvent,
    AlertState,
    duties_for_levels,
    event_is_stale,
    parse_alert_command,
    parse_vision_alert_jsonl,
)
from smartbag_alert_controller import best_effort_stop_all  # noqa: E402


class AlertCoreTest(unittest.TestCase):
    def test_level_to_pwm_duty_table(self) -> None:
        duties = duties_for_levels({"left": 1, "right": 4})

        self.assertEqual(duties["left_1"], int(DEFAULT_PWM_PERIOD_NS * 0.60))
        self.assertEqual(duties["left_2"], 0)
        self.assertEqual(duties["right_1"], DEFAULT_PWM_PERIOD_NS)
        self.assertEqual(duties["right_2"], DEFAULT_PWM_PERIOD_NS)

    def test_parse_ble_alert_commands(self) -> None:
        left = parse_alert_command("AL L1")
        right = parse_alert_command(" al r4 ")
        clear = parse_alert_command("AL CLEAR")

        self.assertEqual(left.kind, "alert")
        self.assertEqual(left.side, "left")
        self.assertEqual(left.level, 1)
        self.assertEqual(right.side, "right")
        self.assertEqual(right.level, 4)
        self.assertEqual(clear.kind, "clear")

    def test_invalid_alert_command_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_alert_command("AL X5")

    def test_clear_stops_all_vibration(self) -> None:
        state = AlertState(event_timeout_s=1.0)

        active = state.apply_command(parse_alert_command("AL R4"), now=10.0)
        self.assertEqual(active.audio_clip, "R4")
        self.assertEqual(active.duties_ns["right_1"], DEFAULT_PWM_PERIOD_NS)
        self.assertEqual(active.duties_ns["right_2"], DEFAULT_PWM_PERIOD_NS)

        cleared = state.apply_command(parse_alert_command("AL CLEAR"), now=10.1)
        self.assertIsNone(cleared.audio_clip)
        self.assertTrue(all(value == 0 for value in cleared.duties_ns.values()))

    def test_event_timeout_closes_stale_side_only(self) -> None:
        state = AlertState(event_timeout_s=1.0)
        state.apply_event(AlertEvent(side="left", level=2, score=0.61, track_id=3, ts=1.2), now=100.0)
        state.apply_event(AlertEvent(side="right", level=3, score=0.72, track_id=8, ts=1.3), now=100.8)

        still_active = state.expire(now=100.95)
        self.assertEqual(still_active.duties_ns["left_1"], int(DEFAULT_PWM_PERIOD_NS * 0.60))
        self.assertEqual(still_active.duties_ns["right_1"], DEFAULT_PWM_PERIOD_NS)

        expired = state.expire(now=101.05)
        self.assertEqual(expired.duties_ns["left_1"], 0)
        self.assertEqual(expired.duties_ns["left_2"], 0)
        self.assertEqual(expired.duties_ns["right_1"], DEFAULT_PWM_PERIOD_NS)
        self.assertEqual(expired.duties_ns["right_2"], int(DEFAULT_PWM_PERIOD_NS * 0.60))

    def test_best_effort_stop_does_not_block_shutdown_on_sysfs_error(self) -> None:
        pwm = MagicMock()
        pwm.stop_all.side_effect = OSError("sysfs unavailable")

        best_effort_stop_all(pwm)

        pwm.stop_all.assert_called_once_with()

    def test_heartbeat_refreshes_pwm_without_replaying_audio(self) -> None:
        state = AlertState(event_timeout_s=1.0, min_audio_interval_s=0.0)
        changed = state.apply_event(AlertEvent(side="left", level=3, event_kind="state_change"), now=10.0)
        heartbeat = state.apply_event(AlertEvent(side="left", level=3, event_kind="heartbeat"), now=10.8)

        self.assertEqual("L3", changed.audio_clip)
        self.assertIsNone(heartbeat.audio_clip)
        self.assertFalse(state.expire(now=11.5).expired_sides)

    def test_heartbeat_cannot_create_or_change_a_warning_level(self) -> None:
        state = AlertState(event_timeout_s=1.0)

        ignored = state.apply_event(AlertEvent(side="right", level=4, event_kind="heartbeat"), now=10.0)

        self.assertEqual(0, ignored.levels["right"])
        self.assertEqual(0, ignored.duties_ns["right_1"])
        self.assertNotIn("right", state.last_event_mono_by_side)

    def test_parser_preserves_event_kind_and_observation_age(self) -> None:
        event = parse_vision_alert_jsonl(
            '{"type":"vision_alert","side":"right","level":2,'
            '"event_kind":"heartbeat","ts":10.0,"observation_age_ms":250.0}'
        )

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual("heartbeat", event.event_kind)
        self.assertEqual(250.0, event.observation_age_ms)
        self.assertTrue(event_is_stale(event, now_s=10.1, max_age_s=0.2))


if __name__ == "__main__":
    unittest.main()
