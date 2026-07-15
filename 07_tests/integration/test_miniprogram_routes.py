import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MINI = ROOT / "06_software" / "mobile" / "ssminiprogram" / "miniprogram"


class MiniProgramRouteTest(unittest.TestCase):
    def test_every_app_route_has_its_page_files(self) -> None:
        app = json.loads((MINI / "app.json").read_text(encoding="utf-8"))
        self.assertNotIn("pages/example/index", app["pages"])
        self.assertNotIn("pages/placeholder/index", app["pages"])
        for route in app["pages"]:
            for suffix in (".js", ".json", ".wxml", ".wxss"):
                self.assertTrue((MINI / f"{route}{suffix}").is_file(), f"missing {route}{suffix}")

    def test_default_device_and_commands_use_unified_namespace(self) -> None:
        paths = list(MINI.rglob("*.js")) + list(MINI.rglob("*.wxml"))
        source = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        self.assertIn("SS928-SmartBag", source)
        self.assertIn("GNSS TL", source)
        self.assertIn("IMU STATUS", source)
        self.assertNotIn('"DX-GP21-Track"', source)
        self.assertNotIn('"BMI270-Backpack"', source)


if __name__ == "__main__":
    unittest.main()
