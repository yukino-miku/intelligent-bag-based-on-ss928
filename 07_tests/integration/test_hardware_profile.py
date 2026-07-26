from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "09_deliverables" / "board_deploy" / "apply_hardware_profile.py"
SPEC = importlib.util.spec_from_file_location("apply_hardware_profile", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HardwareProfileTest(unittest.TestCase):
    def test_profile_merges_nested_values_without_deleting_camera_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config_path = Path(temp) / "config.json"
            profile_path = Path(temp) / "profile.json"
            config_path.write_text(
                json.dumps({"cameras": {"left": {"camera_device": "/dev/video0"}}, "radar": {"enabled": False}}),
                encoding="utf-8",
            )
            profile_path.write_text(
                json.dumps({"name": "test", "config_patch": {"radar": {"enabled": True}}}),
                encoding="utf-8",
            )

            merged = MODULE.apply_profile(config_path, profile_path)

            self.assertTrue(merged["radar"]["enabled"])
            self.assertEqual("/dev/video0", merged["cameras"]["left"]["camera_device"])


if __name__ == "__main__":
    unittest.main()
