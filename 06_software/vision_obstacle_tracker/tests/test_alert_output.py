import io
import json
import unittest
from dataclasses import dataclass
from enum import IntEnum

from alert_output import AlertJsonlEmitter


class Level(IntEnum):
    SAFE = 0
    ATTENTION = 1
    CAUTION = 2
    DANGER = 3


@dataclass
class Point:
    x_m: float


@dataclass
class Target:
    track_id: int
    ground_point: Point


@dataclass
class Risk:
    haptic_level: Level
    score: float
    raw_level: Level = Level.DANGER


class AlertJsonlEmitterTest(unittest.TestCase):
    def test_uses_haptic_level_and_routes_single_camera_by_ground_x(self) -> None:
        stream = io.StringIO()
        emitter = AlertJsonlEmitter(stream, fixed_side="auto", rate_limit_s=1.0, clock=lambda: 10.0)

        emitted = emitter.update(
            [Target(1, Point(-1.0)), Target(2, Point(1.0))],
            {1: Risk(Level.CAUTION, 0.63), 2: Risk(Level.SAFE, 0.99)},
        )

        self.assertEqual(1, len(emitted))
        self.assertEqual("left", emitted[0]["side"])
        self.assertEqual(2, emitted[0]["level"])
        self.assertNotEqual(int(Risk(Level.CAUTION, 0.63).raw_level), emitted[0]["level"])

    def test_center_target_defaults_to_both_sides(self) -> None:
        stream = io.StringIO()
        emitter = AlertJsonlEmitter(stream, clock=lambda: 1.0)

        emitted = emitter.update([Target(7, Point(0.1))], {7: Risk(Level.ATTENTION, 0.3)})

        self.assertEqual({"left", "right"}, {item["side"] for item in emitted})

    def test_center_strongest_keeps_the_current_stronger_side(self) -> None:
        times = iter((1.0, 2.0))
        stream = io.StringIO()
        emitter = AlertJsonlEmitter(stream, center_mode="strongest", clock=lambda: next(times))

        emitter.update([Target(1, Point(-1.0))], {1: Risk(Level.CAUTION, 0.6)})
        emitted = emitter.update([Target(2, Point(0.0))], {2: Risk(Level.DANGER, 0.8)})

        self.assertEqual(1, len(emitted))
        self.assertEqual("left", emitted[0]["side"])

    def test_same_level_is_rate_limited_but_clear_is_immediate(self) -> None:
        times = iter((1.0, 1.1, 1.2))
        stream = io.StringIO()
        emitter = AlertJsonlEmitter(stream, rate_limit_s=1.0, clock=lambda: next(times))
        target = Target(4, Point(-1.0))
        risk = {4: Risk(Level.DANGER, 0.9)}

        self.assertEqual(1, len(emitter.update([target], risk)))
        self.assertEqual([], emitter.update([target], risk))
        cleared = emitter.update([], {})

        self.assertEqual(1, len(cleared))
        self.assertEqual(0, cleared[0]["level"])
        rows = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual([3, 0], [row["level"] for row in rows])


if __name__ == "__main__":
    unittest.main()
