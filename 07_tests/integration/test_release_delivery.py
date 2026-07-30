from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "09_deliverables" / "board_deploy"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ASSETS = load_module("verify_release_assets", DEPLOY / "verify_release_assets.py")
CAMERAS = load_module("camera_discovery", DEPLOY / "camera_discovery.py")
FIT = load_module(
    "fit_fusion_calibration",
    ROOT / "06_software" / "board_runtime" / "radar_vision_fusion" / "fit_fusion_calibration.py",
)


class ReleaseAssetTest(unittest.TestCase):
    def test_packaged_runner_hash_and_architecture(self) -> None:
        runner = DEPLOY / "bin" / "aarch64" / "ss928_detection_runner"
        manifest = DEPLOY / "bin" / "aarch64" / "runner-manifest.json"
        result = ASSETS.verify_runner(runner, manifest)
        self.assertTrue(result["valid"])
        self.assertEqual("AArch64", result["architecture"])

    def test_missing_runner_and_wrong_architecture_are_rejected(self) -> None:
        manifest = DEPLOY / "bin" / "aarch64" / "runner-manifest.json"
        with self.assertRaises(FileNotFoundError):
            ASSETS.verify_runner(ROOT / "missing-runner", manifest)
        with tempfile.TemporaryDirectory() as temp:
            wrong = Path(temp) / "runner"
            header = bytearray(64)
            header[:6] = b"\x7fELF\x02\x01"
            header[18:20] = (62).to_bytes(2, "little")
            wrong.write_bytes(header)
            with self.assertRaisesRegex(ValueError, "architecture mismatch"):
                ASSETS.verify_elf_aarch64(wrong)

    def test_model_hash_and_unvalidated_contract_are_rejected(self) -> None:
        manifest = DEPLOY / "models" / "vehicle-detector.manifest.json"
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "vehicle-detector.om"
            model.write_bytes(b"wrong")
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                ASSETS.verify_model(model, manifest, require_compatible=True)
        data = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertFalse(data["runner_compatible"])
        self.assertEqual("LICENSE_BLOCKED", data["license_source"]["distribution_status"])

    def test_full_installer_requires_model_but_radar_only_is_explicit(self) -> None:
        installer = (ROOT / "install-on-ss928.sh").read_text(encoding="utf-8")
        self.assertIn("full mode requires --model-source", installer)
        self.assertIn("--radar-only", installer)
        self.assertIn("SMARTBAG_RUNTIME_MODE=radar_only", installer)
        self.assertNotIn("08_media", installer)
        self.assertNotIn("10_archive", installer)

    def test_release_layout_contains_every_required_static_asset(self) -> None:
        required = [
            ROOT / "install-on-ss928.sh",
            DEPLOY / "install.sh",
            DEPLOY / "upgrade.sh",
            DEPLOY / "uninstall.sh",
            DEPLOY / "preflight.sh",
            DEPLOY / "safe-off.sh",
            DEPLOY / "systemd" / "smartbag.target",
            DEPLOY / "profiles" / "euler-pi-ss928-smartbag.json",
            DEPLOY / "bin" / "aarch64" / "ss928_detection_runner",
            DEPLOY / "bin" / "aarch64" / "runner-manifest.json",
            DEPLOY / "models" / "vehicle-detector.manifest.json",
            DEPLOY / "dependency-manifest.json",
        ]
        self.assertEqual([], [str(path.relative_to(ROOT)) for path in required if not path.is_file()])

    def test_release_bundle_excludes_local_media_and_archive(self) -> None:
        builder = (ROOT / "09_deliverables" / "releases" / "build-release.sh").read_text(encoding="utf-8")
        self.assertIn('"$STAGING/$PACKAGE_NAME/08_media"', builder)
        self.assertIn('"$STAGING/$PACKAGE_NAME/10_archive"', builder)

    def test_tracked_repository_passes_secret_scan(self) -> None:
        scanner = ROOT / "06_software" / "tools" / "deployment_audit" / "check_repository_secrets.py"
        result = subprocess.run(
            [sys.executable, str(scanner), "--repo-root", str(ROOT)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_secret_scan_rejects_nonempty_release_credential(self) -> None:
        scanner = ROOT / "06_software" / "tools" / "deployment_audit" / "check_repository_secrets.py"
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
            (repo / "settings.sh").write_text("SMARTBAG_UPLOAD_TOKEN=do-not-commit-this-value\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(scanner), "--repo-root", str(repo)],
                cwd=repo,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("non-empty sensitive setting SMARTBAG_UPLOAD_TOKEN", result.stderr)


class HardwareAndCalibrationTest(unittest.TestCase):
    def test_same_camera_assignment_is_rejected(self) -> None:
        camera = {"real_device": "/dev/video0", "id_path": "usb-port-1"}
        with self.assertRaisesRegex(ValueError, "same video device"):
            CAMERAS.validate_assignment(camera, dict(camera))

    def test_distinct_camera_rules_use_physical_id_path(self) -> None:
        discovery = {
            "left": {"id_path": "platform-x-usb-0:1.3:1.0"},
            "right": {"id_path": "platform-x-usb-0:1.4:1.0"},
        }
        rules = CAMERAS.rules_text(discovery)
        self.assertIn('SYMLINK+="smartbag-camera-left"', rules)
        self.assertIn('SYMLINK+="smartbag-camera-right"', rules)
        self.assertIn('ATTR{index}=="0"', rules)

    def test_horizontal_calibration_fit_recovers_known_projection(self) -> None:
        fx, cx, yaw = 400.0, 320.0, 7.0
        observations = []
        for x, z in [(-1.2, 4.0), (-0.5, 6.0), (0.4, 5.0), (1.4, 7.0), (0.8, 3.5)]:
            angle = __import__("math").radians(-yaw)
            camera_x = __import__("math").cos(angle) * x + __import__("math").sin(angle) * z
            camera_z = -__import__("math").sin(angle) * x + __import__("math").cos(angle) * z
            observations.append({"radar_x_m": x, "radar_z_m": z, "pixel_u": fx * camera_x / camera_z + cx})
        result = FIT.fit_horizontal_projection(observations, 0.0, 0.0)
        self.assertAlmostEqual(yaw, result["camera_yaw_deg"], delta=0.1)
        self.assertAlmostEqual(fx, result["camera_fx"], delta=1.0)
        self.assertLess(result["horizontal_rmse_px"], 0.1)

    def test_templates_are_not_marked_measured(self) -> None:
        for side in ("left", "right"):
            data = json.loads((DEPLOY / f"fusion-{side}.example.json").read_text(encoding="utf-8"))
            self.assertEqual("UNMEASURED_TEMPLATE", data["calibration_status"])

    def test_mr20_profile_uses_two_distinct_endpoints(self) -> None:
        path = ROOT / "06_software" / "board_runtime" / "mr20_radar" / "config.example.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        enabled = [item for item in data["radars"] if item.get("enabled", True)]
        self.assertEqual(2, len(enabled))
        self.assertEqual(2, len({(item["radar_ip"], item["port"]) for item in enabled}))

    def test_preflight_rejects_missing_mr20_and_unmeasured_calibration(self) -> None:
        preflight = (DEPLOY / "preflight.sh").read_text(encoding="utf-8")
        self.assertIn("check_path /etc/smartbag/mr20.json", preflight)
        self.assertIn("--require-measured", preflight)
        self.assertIn('check_path "$LEFT_FUSION_CALIBRATION"', preflight)
        self.assertIn('check_path "$RIGHT_FUSION_CALIBRATION"', preflight)


class MockInstallTest(unittest.TestCase):
    @staticmethod
    def bash_path() -> Path | None:
        found = shutil.which("bash") or shutil.which("sh")
        if found:
            return Path(found)
        candidate = Path(r"C:\Program Files\Git\bin\bash.exe")
        return candidate if candidate.is_file() else None

    @staticmethod
    def msys_path(path: Path) -> str:
        resolved = path.resolve()
        if os.name != "nt":
            return str(resolved)
        drive = resolved.drive.rstrip(":").lower()
        return f"/{drive}{resolved.as_posix()[2:]}"

    def test_repeated_mock_install_preserves_config_and_events(self) -> None:
        bash = self.bash_path()
        if bash is None:
            self.skipTest("POSIX shell unavailable")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "rootfs"
            shim_dir = Path(temp) / "bin"
            shim_dir.mkdir()
            shim = shim_dir / "python3"
            shim.write_text(f'#!/bin/sh\nexec "{self.msys_path(Path(sys.executable))}" "$@"\n', encoding="utf-8")
            shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
            env = dict(os.environ)
            env["SMARTBAG_ROOT_PREFIX"] = self.msys_path(root)
            env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")
            command = [
                str(bash),
                self.msys_path(ROOT / "install-on-ss928.sh"),
                "--radar-only", "--offline", "--skip-optional", "--no-start", "--yes",
            ]
            subprocess.run(command, cwd=ROOT, env=env, check=True, capture_output=True, text=True)
            config_path = root / "etc" / "smartbag" / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["test_marker"] = "preserve"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            event = root / "var" / "lib" / "smartbag" / "alarm-events" / "event.json"
            event.parent.mkdir(parents=True, exist_ok=True)
            event.write_text("{}", encoding="utf-8")
            subprocess.run(command, cwd=ROOT, env=env, check=True, capture_output=True, text=True)
            self.assertEqual("preserve", json.loads(config_path.read_text(encoding="utf-8"))["test_marker"])
            self.assertTrue(event.is_file())

            subprocess.run(
                [str(bash), self.msys_path(DEPLOY / "uninstall.sh")],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertFalse((root / "root" / "smartbag").exists())
            self.assertTrue(config_path.is_file())
            self.assertTrue(event.is_file())

    def test_mock_full_install_without_model_fails_but_radar_only_succeeds(self) -> None:
        bash = self.bash_path()
        if bash is None:
            self.skipTest("POSIX shell unavailable")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "rootfs"
            shim_dir = Path(temp) / "bin"
            shim_dir.mkdir()
            shim = shim_dir / "python3"
            shim.write_text(f'#!/bin/sh\nexec "{self.msys_path(Path(sys.executable))}" "$@"\n', encoding="utf-8")
            shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
            env = dict(os.environ)
            env["SMARTBAG_ROOT_PREFIX"] = self.msys_path(root)
            env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")
            base = [str(bash), self.msys_path(ROOT / "install-on-ss928.sh"), "--offline", "--skip-optional", "--no-start", "--yes"]
            full = subprocess.run(base, cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertNotEqual(0, full.returncode)
            self.assertIn("full mode requires --model-source", full.stderr)
            radar = subprocess.run(base + ["--radar-only"], cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertEqual(0, radar.returncode, radar.stderr)

    def test_installer_enables_systemd_and_has_failure_safe_off(self) -> None:
        installer = (ROOT / "install-on-ss928.sh").read_text(encoding="utf-8")
        self.assertIn("systemctl enable smartbag.target", installer)
        self.assertIn('"$DEPLOY/safe-off.sh"', installer)
        self.assertIn("trap cleanup_on_failure", installer)


if __name__ == "__main__":
    unittest.main()
