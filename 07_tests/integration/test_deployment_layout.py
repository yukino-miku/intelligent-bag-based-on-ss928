import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "09_deliverables" / "board_deploy"


class DeploymentLayoutTest(unittest.TestCase):
    def test_default_unit_uses_configured_dual_camera_supervisor(self) -> None:
        unit = (DEPLOY / "systemd" / "smartbag-alert.service").read_text(encoding="utf-8")
        self.assertIn("/root/smartbag/vision", unit)
        self.assertIn("/root/smartbag/controller", unit)
        self.assertIn("--config /etc/smartbag/config.json", unit)
        self.assertNotIn("--single-camera", unit)
        self.assertNotIn("--side auto", unit)
        self.assertIn("--no-ble", unit)
        self.assertNotIn("/root/vision_obstacle_tracker", unit)

    def test_target_starts_controller_which_owns_child_processes(self) -> None:
        target = (DEPLOY / "systemd" / "smartbag.target").read_text(encoding="utf-8")
        self.assertIn("Requires=smartbag-alert.service", target)
        self.assertIn("smartbag-video.service", target)
        self.assertNotIn("smartbag-gnss.service", target)
        self.assertNotIn("smartbag-imu.service", target)

    def test_imx347_and_single_diagnostic_are_not_in_default_target(self) -> None:
        target = (DEPLOY / "systemd" / "smartbag.target").read_text(encoding="utf-8")
        self.assertNotIn("imx347", target.lower())
        self.assertNotIn("smartbag-vision.service", target)

        alert_unit = (DEPLOY / "systemd" / "smartbag-alert.service").read_text(encoding="utf-8")
        diagnostic_unit = (DEPLOY / "systemd" / "smartbag-vision.service").read_text(encoding="utf-8")
        self.assertIn("Conflicts=smartbag-vision.service", alert_unit)
        self.assertIn("Conflicts=smartbag-alert.service", diagnostic_unit)


if __name__ == "__main__":
    unittest.main()
