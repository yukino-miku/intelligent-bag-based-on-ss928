from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from temperature_reader import parse_tsensor_text, read_temperature  # noqa: E402


class TemperatureReaderTests(unittest.TestCase):
    def test_parses_all_three_channels(self) -> None:
        result = parse_tsensor_text("TSENSOR[0] DATA: 42.5\nTSENSOR[1] DATA: 43\nTSENSOR[2] DATA: -4.25\n")
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.values_c["tsensor2"], -4.25)

    def test_partial_data_is_explicitly_invalid(self) -> None:
        result = parse_tsensor_text("TSENSOR[0] DATA: 42\n")
        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.values_c, {})

    def test_missing_proc_file_is_unavailable_not_fake_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = read_temperature(Path(temp) / "missing")
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.values_c, {})


if __name__ == "__main__":
    unittest.main()
