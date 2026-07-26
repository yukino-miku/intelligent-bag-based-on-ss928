from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "09_deliverables" / "board_deploy" / "migrate_config.py"
SPEC = importlib.util.spec_from_file_location("smartbag_migrate_config", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DeployConfigMigrationTest(unittest.TestCase):
    def test_adds_new_defaults_without_overwriting_local_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "config.json"
            defaults = root / "defaults.json"
            config.write_text(json.dumps({"paths": {"model": "/local/model.pt"}}), encoding="utf-8")
            defaults.write_text(
                json.dumps({"paths": {"model": "/default/model.pt", "python": "/usr/bin/python3"}, "radar": {"enabled": False}}),
                encoding="utf-8",
            )

            self.assertTrue(MODULE.migrate(config, defaults))
            result = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual("/local/model.pt", result["paths"]["model"])
            self.assertEqual("/usr/bin/python3", result["paths"]["python"])
            self.assertFalse(result["radar"]["enabled"])
            self.assertEqual(1, len(list(root.glob("config.json.bak-*"))))
            self.assertFalse(MODULE.migrate(config, defaults))


if __name__ == "__main__":
    unittest.main()
