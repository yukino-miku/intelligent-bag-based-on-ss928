import io
import sys
import unittest
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VISION = ROOT / "06_software" / "vision_obstacle_tracker"
if str(VISION) not in sys.path:
    sys.path.insert(0, str(VISION))

from alert_output import AlertJsonlEmitter


class Level(IntEnum):
    CAUTION = 2


@dataclass
class Point:
    x_m: float


@dataclass
class Target:
    track_id: int
    ground_point: Point


@dataclass
class Risk:
    haptic_level: Level = Level.CAUTION
    score: float = 0.7


class SingleCameraSideRoutingTest(unittest.TestCase):
    def test_left_right_and_center_both_routing(self) -> None:
        emitter = AlertJsonlEmitter(io.StringIO(), dead_zone_m=0.3, clock=lambda: 1.0)
        risks = {1: Risk(), 2: Risk(), 3: Risk()}
        emitted = emitter.update(
            [Target(1, Point(-1.0)), Target(2, Point(1.0)), Target(3, Point(0.0))],
            risks,
        )
        self.assertEqual({"left", "right"}, {item["side"] for item in emitted})


if __name__ == "__main__":
    unittest.main()
