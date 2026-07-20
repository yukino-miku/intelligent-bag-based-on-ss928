from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "09_deliverables" / "board_deploy"


class Rev2AutonomousConfigTest(unittest.TestCase):
    def test_rev2_profile_has_four_haptic_patterns_persistent_lights_and_optional_audio(self) -> None:
        profile = json.loads((DEPLOY / "hardware-profiles" / "rev2_tm6605_mr20.json").read_text(encoding="utf-8"))
        self.assertEqual({str(level): level for level in range(5)}, profile["output_policy"]["haptic_level_map"])
        self.assertTrue(all(profile["haptics"]["level_effects"][str(level)]["effect"] > 0 for level in range(1, 5)))
        self.assertEqual("slow_blink", profile["lights"]["level_patterns"]["3"]["mode"])
        self.assertTrue(profile["lights"]["level_patterns"]["3"]["repeat"])
        self.assertEqual("fast_blink", profile["lights"]["level_patterns"]["4"]["mode"])
        self.assertTrue(profile["audio"]["enabled"])
        self.assertFalse(profile["audio"]["required"])

    def test_default_runtime_is_alternating_and_uses_fixed_venv(self) -> None:
        config = json.loads((DEPLOY / "config.example.json").read_text(encoding="utf-8"))
        self.assertEqual("/root/smartbag/venv/bin/python", config["paths"]["python"])
        self.assertEqual("alternating_single_model", config["vision_runtime"]["mode"])
        self.assertTrue(config["alternating_camera"]["enabled"])
        self.assertTrue(config["audio"]["enabled"])

    def test_core_systemd_has_no_network_online_dependency_and_has_safe_stop(self) -> None:
        target = (DEPLOY / "systemd" / "smartbag.target").read_text(encoding="utf-8")
        controller = (DEPLOY / "systemd" / "smartbag-controller.service").read_text(encoding="utf-8")
        self.assertIn("WantedBy=multi-user.target", target)
        self.assertIn("smartbag-controller.service", target)
        self.assertNotIn("network-online.target", target + controller)
        self.assertIn("/root/smartbag/venv/bin/python", controller)
        self.assertIn("ExecStopPost=", controller)
        self.assertIn("Restart=always", controller)
        self.assertIn("KillMode=control-group", controller)
        self.assertIn("StandardInput=null", controller)

    def test_wait_for_hardware_writes_bounded_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model = root / "model.pt"
            left = root / "left"
            right = root / "right"
            for path in (model, left, right):
                path.write_bytes(b"x")
            config = root / "config.json"
            config.write_text(json.dumps({
                "paths": {"model": str(model)},
                "cameras": {"left": {"camera_device": str(left)}, "right": {"camera_device": str(right)}},
            }), encoding="utf-8")
            report = root / "report.json"
            completed = subprocess.run([
                sys.executable, str(DEPLOY / "wait_for_hardware.py"),
                "--profile", "vision", "--config", str(config),
                "--timeout-s", "0.1", "--report", str(report),
            ], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(0, completed.returncode, completed.stderr)
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual("ready", payload["final"])
            self.assertTrue(all(item["attempts"] >= 1 for item in payload["checks"].values()))


if __name__ == "__main__":
    unittest.main()
