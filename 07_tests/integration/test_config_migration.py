from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "06_software" / "board_runtime" / "common"
sys.path.insert(0, str(COMMON))

from config_migration import migrate_config  # noqa: E402
from hardware_profile import validate_hardware_profile  # noqa: E402


class ConfigMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.legacy = {
            "pwm": {
                "period_ns": 1000000,
                "level_duty_percent": {str(level): [level * 10, level * 10] for level in range(5)},
            },
            "cameras": {
                "left": {"pwm_channels": ["left_1", "left_2"]},
                "right": {"pwm_channels": ["right_1", "right_2"]},
            },
            "audio": {"enabled": False},
        }

    def test_default_migration_preserves_legacy_wiring_and_fields(self) -> None:
        migrated, report = migrate_config(self.legacy)
        validate_hardware_profile(migrated["hardware"])
        self.assertEqual("legacy_pwm_haptics", migrated["hardware"]["profile"])
        self.assertIn("pwm", migrated)
        self.assertIn("cameras.left.pwm_channels", report.retained_legacy_fields)

    def test_rev2_requires_explicit_profile_and_reports_manual_wiring(self) -> None:
        migrated, report = migrate_config(self.legacy, new_profile="rev2_tm6605_mr20")
        validate_hardware_profile(migrated["hardware"])
        self.assertEqual(0, migrated["hardware"]["i2c_mux"]["channels"]["bmi270"])
        self.assertTrue(any("Pin7/32" in item for item in report.manual_confirmation))

    def test_profile_examples_parse_and_validate(self) -> None:
        profile_dir = ROOT / "09_deliverables" / "board_deploy" / "hardware-profiles"
        for path in profile_dir.glob("*.json"):
            with self.subTest(path=path.name):
                validate_hardware_profile(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()

