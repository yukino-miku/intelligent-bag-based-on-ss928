import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GNSS = ROOT / "06_software" / "board_runtime" / "dx_gp21_tracker"
if str(GNSS) not in sys.path:
    sys.path.insert(0, str(GNSS))

from dx_gp21_tracker import NmeaLocationTracker, is_valid_nmea


class GnssProtocolIntegrationTest(unittest.TestCase):
    def test_checksum_and_wgs84_fix_pipeline(self) -> None:
        gga = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
        self.assertTrue(is_valid_nmea(gga))
        tracker = NmeaLocationTracker()
        self.assertIsNone(tracker.update(gga))
        point = tracker.update("$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A")
        self.assertIsNotNone(point)
        self.assertEqual("wgs84", point["cs"])
        self.assertEqual("dx_gp21", point["src"])


if __name__ == "__main__":
    unittest.main()
