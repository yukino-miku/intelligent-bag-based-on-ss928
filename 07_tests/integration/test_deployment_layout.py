import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "09_deliverables" / "board_deploy"


class DeploymentLayoutTest(unittest.TestCase):
    def test_default_unit_uses_unified_paths_and_single_supervisor(self) -> None:
        unit = (DEPLOY / "systemd" / "smartbag-alert.service").read_text(encoding="utf-8")
        self.assertIn("/root/smartbag/vision", unit)
        self.assertIn("/root/smartbag/controller", unit)
        self.assertIn("--single-camera", unit)
        self.assertIn("--no-ble", unit)
        self.assertIn("Conflicts=smartbag-vision.service", unit)
        self.assertNotIn("/root/vision_obstacle_tracker", unit)

    def test_target_starts_controller_which_owns_child_processes(self) -> None:
        target = (DEPLOY / "systemd" / "smartbag.target").read_text(encoding="utf-8")
        self.assertIn("Requires=smartbag-alert.service", target)
        self.assertNotIn("smartbag-gnss.service", target)
        self.assertNotIn("smartbag-imu.service", target)


if __name__ == "__main__":
    unittest.main()
