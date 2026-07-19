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

    def test_home_has_dual_camera_entry_and_no_fake_status_values(self) -> None:
        home = "\n".join(
            (MINI / "pages" / "home" / name).read_text(encoding="utf-8")
            for name in ("index.js", "index.wxml")
        )
        app = json.loads((MINI / "app.json").read_text(encoding="utf-8"))

        self.assertIn("双摄实时画面", home)
        self.assertIn("pages/cameras/index", app["pages"])
        self.assertNotIn("在线设备 1 台", home)
        self.assertNotIn("86%", home)
        monitor = (MINI / "pages" / "monitor" / "index.js").read_text(encoding="utf-8")
        self.assertIn("smartbagAlertHistory", monitor)
        self.assertIn("wx.removeStorageSync", monitor)

    def test_camera_page_uses_completion_driven_refresh_and_lifecycle_guards(self) -> None:
        camera_page = (MINI / "pages" / "cameras" / "index.js").read_text(encoding="utf-8")

        self.assertNotIn("setInterval", camera_page)
        self.assertIn("snapshotInFlight", camera_page)
        self.assertIn("snapshotGeneration", camera_page)
        self.assertIn("onSnapshotLoad", camera_page)
        self.assertIn("onSnapshotError", camera_page)
        self.assertIn("onHide()", camera_page)
        self.assertIn("task.abort", camera_page)
        self.assertIn("focusPenalty", camera_page)


if __name__ == "__main__":
    unittest.main()
