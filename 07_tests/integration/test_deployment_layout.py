import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "09_deliverables" / "board_deploy"


class DeploymentLayoutTest(unittest.TestCase):
    def test_default_unit_uses_configured_alternating_camera_supervisor(self) -> None:
        unit = (DEPLOY / "systemd" / "smartbag-controller.service").read_text(encoding="utf-8")
        self.assertIn("/root/smartbag/vision", unit)
        self.assertIn("/root/smartbag/controller", unit)
        self.assertIn("--config /etc/smartbag/config.json", unit)
        self.assertNotIn("--single-camera", unit)
        self.assertNotIn("--side auto", unit)
        self.assertIn("--no-ble", unit)
        self.assertIn("--hardware-profile /etc/smartbag/hardware.json", unit)
        self.assertNotIn("/root/vision_obstacle_tracker", unit)

    def test_target_starts_controller_which_owns_child_processes(self) -> None:
        target = (DEPLOY / "systemd" / "smartbag.target").read_text(encoding="utf-8")
        self.assertIn("smartbag-controller.service", target)
        self.assertIn("smartbag-safe-off.service", target)
        self.assertNotIn("smartbag-video.service", target)
        self.assertNotIn("smartbag-gnss.service", target)
        self.assertNotIn("smartbag-imu.service", target)

    def test_imx347_and_single_diagnostic_are_not_in_default_target(self) -> None:
        target = (DEPLOY / "systemd" / "smartbag.target").read_text(encoding="utf-8")
        self.assertNotIn("imx347", target.lower())
        self.assertNotIn("smartbag-vision.service", target)

        alert_unit = (DEPLOY / "systemd" / "smartbag-controller.service").read_text(encoding="utf-8")
        diagnostic_unit = (DEPLOY / "systemd" / "smartbag-vision.service").read_text(encoding="utf-8")
        self.assertNotIn("smartbag-vision.service", target)
        self.assertIn("smartbag-controller.service", diagnostic_unit)

    def test_mr20_network_is_host_route_without_gateway(self) -> None:
        network = (DEPLOY / "systemd-networkd" / "20-mr20-radar.network").read_text(encoding="utf-8")
        self.assertIn("Address=192.168.1.102/32", network)
        self.assertIn("Destination=192.168.1.200/32", network)
        self.assertIn("Scope=link", network)
        self.assertNotIn("Gateway=", network)

    def test_cloud_uploader_is_optional_and_not_in_default_target(self) -> None:
        target = (DEPLOY / "systemd" / "smartbag.target").read_text(encoding="utf-8")
        cloud = (DEPLOY / "systemd" / "smartbag-cloud-uploader.service").read_text(encoding="utf-8")
        self.assertNotIn("smartbag-cloud-uploader", target)
        self.assertIn("EnvironmentFile=-/etc/smartbag/cloud-uploader.env", cloud)
        self.assertIn("https", (ROOT / "06_software/board_runtime/cloud_uploader/config.example.json").read_text(encoding="utf-8"))

    def test_profile_aware_pinmux_does_not_enable_legacy_right_pwm_in_rev2_branch(self) -> None:
        script = (ROOT / "05_firmware/ss928/pinmux/apply-smartbag-pinmux.sh").read_text(encoding="utf-8")
        rev2 = script.split("rev2_tm6605_mr20)", 1)[1].split(";;", 1)[0]
        self.assertIn("0x102F0110", rev2)
        self.assertIn("0x102F01EC", rev2)
        self.assertNotIn("0x102F0100", rev2)
        self.assertNotIn("0x102F00DC", rev2)

    def test_hardware_test_tools_and_output_timing_log_are_deployed(self) -> None:
        install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
        config = (DEPLOY / "config.example.json").read_text(encoding="utf-8")
        for name in ("hardware-preflight.sh", "mr20-capture.sh", "full-hardware-test.sh"):
            self.assertIn(name, install)
            self.assertTrue((DEPLOY / name).is_file())
        self.assertIn("controller_actuator_jsonl", config)


if __name__ == "__main__":
    unittest.main()
