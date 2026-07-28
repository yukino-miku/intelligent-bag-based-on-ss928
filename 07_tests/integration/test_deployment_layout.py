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
        self.assertIn("ExecStopPost=/root/smartbag/safe-off.sh", unit)
        self.assertNotIn("/root/vision_obstacle_tracker", unit)

    def test_target_starts_only_controller_as_camera_owner(self) -> None:
        target = (DEPLOY / "systemd" / "smartbag.target").read_text(encoding="utf-8")
        self.assertIn("Requires=smartbag-alert.service", target)
        self.assertNotIn("smartbag-video.service", target)
        self.assertNotIn("smartbag-gnss.service", target)
        self.assertNotIn("smartbag-imu.service", target)
        self.assertIn("smartbag-connectivity.service", target)
        self.assertIn("smartbag-temperature.service", target)

    def test_imx347_and_single_diagnostic_are_not_in_default_target(self) -> None:
        target = (DEPLOY / "systemd" / "smartbag.target").read_text(encoding="utf-8")
        self.assertNotIn("imx347", target.lower())
        self.assertNotIn("smartbag-vision.service", target)

        alert_unit = (DEPLOY / "systemd" / "smartbag-alert.service").read_text(encoding="utf-8")
        diagnostic_unit = (DEPLOY / "systemd" / "smartbag-vision.service").read_text(encoding="utf-8")
        self.assertIn("Conflicts=smartbag-vision.service", alert_unit)
        self.assertIn("Conflicts=smartbag-alert.service", diagnostic_unit)

    def test_formal_services_have_one_hardware_owner(self) -> None:
        alert = (DEPLOY / "systemd" / "smartbag-alert.service").read_text(encoding="utf-8")
        connectivity = (DEPLOY / "systemd" / "smartbag-connectivity.service").read_text(encoding="utf-8")
        combined = alert + connectivity
        self.assertEqual(1, combined.count("smartbag_alert_controller.py"))
        self.assertEqual(1, combined.count("mt5710_connectivity.py"))
        self.assertNotIn("bmi270_backpack.py", connectivity)
        self.assertNotIn("dx_gp21_tracker.py", connectivity)
        self.assertNotIn("--supervise-sensors", connectivity)

    def test_optional_connectivity_failure_cannot_stop_local_alert_runtime(self) -> None:
        target = (DEPLOY / "systemd" / "smartbag.target").read_text(encoding="utf-8")
        alert = (DEPLOY / "systemd" / "smartbag-alert.service").read_text(encoding="utf-8")
        self.assertIn("Requires=smartbag-alert.service", target)
        self.assertNotIn("Requires=smartbag-video.service", target)
        self.assertIn("Wants=", target)
        self.assertNotIn("Requires=smartbag-connectivity.service", target)
        self.assertNotIn("Requires=smartbag-connectivity.service", alert)

    def test_default_target_does_not_start_duplicate_bmi_or_gnss_services(self) -> None:
        target = (DEPLOY / "systemd" / "smartbag.target").read_text(encoding="utf-8")
        self.assertNotIn("smartbag-imu.service", target)
        self.assertNotIn("smartbag-gnss.service", target)
        alert = (DEPLOY / "systemd" / "smartbag-alert.service").read_text(encoding="utf-8")
        self.assertIn("smartbag_alert_controller.py", alert)

    def test_installer_contains_every_runtime_dependency(self) -> None:
        installer = (DEPLOY / "install.sh").read_text(encoding="utf-8")
        for module in ("cloud_uploader", "mt5710_connectivity", "mr20_radar", "temperature"):
            self.assertIn(module, installer)
        self.assertIn("migrate_config.py", installer)
        self.assertIn("smartbag.env", installer)

    def test_legacy_video_gateway_is_manual_only(self) -> None:
        unit = (DEPLOY / "systemd" / "smartbag-video.service").read_text(encoding="utf-8")
        installer = (DEPLOY / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("WantedBy=smartbag.target", unit)
        self.assertIn("systemctl disable smartbag-video.service", installer)

    def test_om_fusion_dependency_check_does_not_require_torch_stack(self) -> None:
        script = (DEPLOY / "check-runtime-deps.sh").read_text(encoding="utf-8")
        self.assertIn('runtime_mode == "radar_primary_visual_classification"', script)
        self.assertIn('if snapshot_backend == "ultralytics"', script)
        self.assertIn('required += ["cv2", "numpy"]', script)
        self.assertIn('required += ["cv2", "numpy", "torch", "ultralytics", "lap"]', script)
        preflight = (DEPLOY / "preflight.sh").read_text(encoding="utf-8")
        self.assertIn('"$SCRIPT_DIR/check-runtime-deps.sh" "$CONFIG"', preflight)


if __name__ == "__main__":
    unittest.main()
