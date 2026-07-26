from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from smartbag_alert_controller import module_commands_from_config  # noqa: E402


class RuntimeConfigTest(unittest.TestCase):
    def test_only_enabled_modules_are_started(self) -> None:
        config = {
            "modules": {
                "gnss": {"enabled": False, "command": "gnss"},
                "imu": {"enabled": True, "command": "imu --no-ble"},
            }
        }
        self.assertEqual(module_commands_from_config(config), {"IMU": "imu --no-ble"})

    def test_enabled_module_requires_command(self) -> None:
        with self.assertRaisesRegex(ValueError, "modules.gnss.command"):
            module_commands_from_config({"modules": {"gnss": {"enabled": True}}})


if __name__ == "__main__":
    unittest.main()
