from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
UNIT_DIR = REPO_ROOT / "09_deliverables" / "board_deploy" / "systemd"


class ConnectivityUnitTests(unittest.TestCase):
    def test_connectivity_service_owns_only_mt5710(self) -> None:
        unit = (UNIT_DIR / "smartbag-connectivity.service").read_text(encoding="utf-8")

        for required in (
            "Type=simple",
            "Restart=on-failure",
            "EnvironmentFile=-/etc/smartbag/smartbag.env",
            "/root/smartbag/connectivity/mt5710_connectivity.py",
        ):
            self.assertIn(required, unit)
        for forbidden in ("bmi270_backpack.py", "dx_gp21_tracker.py", "--supervise-sensors"):
            self.assertNotIn(forbidden, unit)

    def test_alert_service_remains_independent_of_connectivity_failure(self) -> None:
        unit = (UNIT_DIR / "smartbag-alert.service").read_text(encoding="utf-8")

        self.assertIn("smartbag-connectivity.service", unit)
        self.assertNotIn("Requires=smartbag-connectivity.service", unit)


if __name__ == "__main__":
    unittest.main()
