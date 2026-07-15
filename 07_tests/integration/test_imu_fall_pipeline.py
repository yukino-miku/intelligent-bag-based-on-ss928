import sys
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BMI = ROOT / "06_software" / "board_runtime" / "bmi270_backpack"
if str(BMI) not in sys.path:
    sys.path.insert(0, str(BMI))

from fall_bridge import FallEventBridge


@dataclass
class BmiSample:
    t: float
    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float


class ImuFallPipelineTest(unittest.TestCase):
    def test_bmi_sample_converts_directly_without_text_round_trip(self) -> None:
        source = BmiSample(1.25, 0.1, 0.2, 0.9, 2.0, 3.0, 4.0)
        converted = FallEventBridge.convert(source)
        self.assertEqual(1.25, converted.t)
        self.assertEqual((0.1, 0.2, 0.9), (converted.ax, converted.ay, converted.az))
        self.assertEqual((2.0, 3.0, 4.0), (converted.gx, converted.gy, converted.gz))


if __name__ == "__main__":
    unittest.main()
