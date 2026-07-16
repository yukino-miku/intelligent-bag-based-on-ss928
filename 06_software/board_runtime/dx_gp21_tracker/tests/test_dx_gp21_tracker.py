import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import dx_gp21_tracker as gnss  # noqa: E402


class NmeaParsingTests(unittest.TestCase):
    def test_checksum_validation_rejects_corrupt_sentence(self):
        valid = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
        invalid = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*46"

        self.assertTrue(gnss.is_valid_nmea(valid))
        self.assertFalse(gnss.is_valid_nmea(invalid))

    def test_dm_to_decimal_handles_south_and_west(self):
        self.assertAlmostEqual(gnss.dm_to_decimal("2236.40101", "N"), 22.6066835, places=7)
        self.assertAlmostEqual(gnss.dm_to_decimal("11349.73472", "E"), 113.828912, places=6)
        self.assertAlmostEqual(gnss.dm_to_decimal("2236.40101", "S"), -22.6066835, places=7)
        self.assertAlmostEqual(gnss.dm_to_decimal("11349.73472", "W"), -113.828912, places=6)

    def test_tracker_combines_rmc_and_gga_into_valid_location(self):
        tracker = gnss.NmeaLocationTracker()

        self.assertIsNone(tracker.update("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"))
        point = tracker.update("$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A")

        self.assertIsNotNone(point)
        self.assertEqual(point["typ"], "loc")
        self.assertEqual(point["fix"], 1)
        self.assertEqual(point["sat"], 8)
        self.assertAlmostEqual(point["lat"], 48.1173, places=4)
        self.assertAlmostEqual(point["lon"], 11.5166667, places=4)
        self.assertAlmostEqual(point["alt"], 545.4, places=1)
        self.assertAlmostEqual(point["spd"], 11.5235, places=3)
        self.assertAlmostEqual(point["course"], 84.4, places=1)
        self.assertEqual(point["src"], "dx_gp21")
        self.assertEqual(point["cs"], "wgs84")

    def test_invalid_fix_updates_status_but_returns_no_point(self):
        tracker = gnss.NmeaLocationTracker()
        point = tracker.update("$GPRMC,123519,V,4807.038,N,01131.000,E,000.0,000.0,230394,003.1,W*71")

        self.assertIsNone(point)
        status = tracker.status(serial_device="/dev/ttyAMA4", baud=115200, track_count=0)
        self.assertEqual(status["typ"], "ts")
        self.assertEqual(status["fix"], 0)
        self.assertEqual(status["uart"], "/dev/ttyAMA4")
        self.assertEqual(status["baud"], 115200)


class TrackStoreTests(unittest.TestCase):
    def test_store_ignores_invalid_fix_and_paginates_valid_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = gnss.TrackStore(tmp)
            valid_a = {"typ": "loc", "t": 1719981296.0, "lat": 31.23042, "lon": 121.4737, "acc": 4.5, "spd": 0.8, "course": 92.0, "fix": 1}
            valid_b = {"typ": "loc", "t": 1719981297.0, "lat": 31.23043, "lon": 121.4738, "acc": 4.3, "spd": 0.9, "course": 93.0, "fix": 1}
            invalid = {"typ": "loc", "t": 1719981298.0, "lat": 31.23044, "lon": 121.4739, "fix": 0}

            self.assertTrue(store.append(valid_a))
            self.assertTrue(store.append(valid_b))
            self.assertFalse(store.append(invalid))

            listing = store.list_tracks()
            self.assertEqual(len(listing), 1)
            self.assertEqual(listing[0]["n"], 2)
            self.assertEqual(listing[0]["start"], valid_a["t"])
            self.assertEqual(listing[0]["end"], valid_b["t"])

            first = store.chunk(0, 0, limit=1)
            self.assertEqual(first["typ"], "trk")
            self.assertEqual(first["o"], 0)
            self.assertEqual(first["next"], 1)
            self.assertEqual(first["done"], 0)
            self.assertEqual(first["pts"], [[1719981296.0, 31.23042, 121.4737, 4.5, 0.8, 92.0]])

            second = store.chunk(0, first["next"], limit=1)
            self.assertEqual(second["next"], None)
            self.assertEqual(second["done"], 1)
            self.assertEqual(second["pts"], [[1719981297.0, 31.23043, 121.4738, 4.3, 0.9, 93.0]])

            line = next(Path(tmp).glob("*.jsonl")).read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(json.loads(line)["lat"], 31.23042)


class SerialReaderTests(unittest.TestCase):
    def test_reader_waits_when_nonblocking_serial_has_no_data_yet(self):
        original_read = gnss.os.read
        original_sleep = gnss.time.sleep
        events = iter([
            BlockingIOError(11, "Resource temporarily unavailable"),
            b"$GNTXT,hello*00\r\n",
        ])
        sleeps = []

        def fake_read(fd, size):
            item = next(events)
            if isinstance(item, BaseException):
                raise item
            return item

        try:
            gnss.os.read = fake_read
            gnss.time.sleep = lambda seconds: sleeps.append(seconds)
            reader = gnss.SerialLineReader("/dev/ttyAMA4", 115200)
            reader.fd = 123

            self.assertEqual(next(reader.lines()), "$GNTXT,hello*00")
            self.assertEqual(sleeps, [0.02])
        finally:
            gnss.os.read = original_read
            gnss.time.sleep = original_sleep


if __name__ == "__main__":
    unittest.main()
