import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "06_software" / "board_runtime" / "common"
if str(COMMON) not in sys.path:
    sys.path.insert(0, str(COMMON))

from ble_protocol import route_ble_command


class BleCommandRoutingTest(unittest.TestCase):
    def test_namespaced_and_legacy_commands_route_consistently(self) -> None:
        self.assertEqual(("AL", "L2"), (route_ble_command("AL L2").namespace, route_ble_command("AL L2").command))
        self.assertEqual("GNSS", route_ble_command("GNSS TL").namespace)
        self.assertTrue(route_ble_command("TG 0 25").legacy)
        self.assertEqual("IMU", route_ble_command("IMU ZERO").namespace)
        self.assertTrue(route_ble_command("STATUS").legacy)
        self.assertEqual("SYS", route_ble_command("SYS STATUS").namespace)

    def test_gnss_and_bmi_default_configs_do_not_claim_ble(self) -> None:
        gnss = json.loads((ROOT / "06_software/board_runtime/dx_gp21_tracker/config.ss928_uart4.json").read_text(encoding="utf-8"))
        bmi = json.loads((ROOT / "06_software/board_runtime/bmi270_backpack/config.example.json").read_text(encoding="utf-8"))
        self.assertFalse(gnss["output"]["ble_enabled"])
        self.assertFalse(bmi["output"]["ble_enabled"])
        self.assertEqual("SS928-SmartBag", gnss["output"]["ble_name"])
        self.assertEqual("SS928-SmartBag", bmi["output"]["ble_name"])


if __name__ == "__main__":
    unittest.main()
