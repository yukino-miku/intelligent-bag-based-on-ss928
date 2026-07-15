import io
import sys
import unittest
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VISION = ROOT / "06_software" / "vision_obstacle_tracker"
CONTROLLER = ROOT / "06_software" / "board_runtime" / "smartbag_alert_controller"
for path in (VISION, CONTROLLER):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from alert_core import parse_vision_alert_jsonl
from alert_output import AlertJsonlEmitter


class Level(IntEnum):
    SAFE = 0
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


class VisionAlertProtocolTest(unittest.TestCase):
    def test_controller_parses_detector_jsonl_and_uses_haptic_level(self) -> None:
        stream = io.StringIO()
        emitter = AlertJsonlEmitter(stream, fixed_side="left", clock=lambda: 123.45)
        emitter.update([Target(120, Point(-0.8))], {120: Risk(Level.CAUTION, 0.63)})

        event = parse_vision_alert_jsonl(stream.getvalue().strip())

        self.assertIsNotNone(event)
        self.assertEqual("left", event.side)
        self.assertEqual(2, event.level)
        self.assertEqual(120, event.track_id)


if __name__ == "__main__":
    unittest.main()
