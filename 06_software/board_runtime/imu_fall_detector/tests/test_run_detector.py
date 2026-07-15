import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from run_detector import parse_sample_line  # noqa: E402


class RunDetectorParsingTests(unittest.TestCase):
    def test_parse_csv_line_with_required_units(self):
        sample = parse_sample_line("12.5,0.1,-0.2,0.98,1.0,2.0,3.0")
        self.assertEqual(sample.t, 12.5)
        self.assertEqual(sample.ax, 0.1)
        self.assertEqual(sample.ay, -0.2)
        self.assertEqual(sample.az, 0.98)
        self.assertEqual(sample.gx, 1.0)
        self.assertEqual(sample.gy, 2.0)
        self.assertEqual(sample.gz, 3.0)

    def test_parse_json_line_with_a_and_w_arrays(self):
        sample = parse_sample_line('{"t":2,"a":[0,0,1],"w":[4,5,6]}')
        self.assertEqual(sample.t, 2.0)
        self.assertEqual((sample.ax, sample.ay, sample.az), (0.0, 0.0, 1.0))
        self.assertEqual((sample.gx, sample.gy, sample.gz), (4.0, 5.0, 6.0))


if __name__ == "__main__":
    unittest.main()
