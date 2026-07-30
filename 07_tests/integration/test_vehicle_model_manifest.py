import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class VehicleModelManifestTest(unittest.TestCase):
    def test_inventory_and_deployment_manifest_select_the_same_candidate(self) -> None:
        inventory = json.loads((ROOT / "00_admin" / "local-model-inventory.json").read_text(encoding="utf-8"))
        manifest = json.loads(
            (ROOT / "09_deliverables" / "board_deploy" / "models" / "vehicle-detector.manifest.json").read_text(encoding="utf-8")
        )
        selected = next(item for item in inventory["models"] if item["id"] == inventory["selected_candidate_id"])
        self.assertEqual("vehicle-detector.om", manifest["deployment_name"])
        self.assertEqual(selected["sha256"], manifest["sha256"])
        self.assertEqual(selected["path"], manifest["candidate_source"])
        self.assertEqual(["bicycle", "motorcycle", "car", "truck", "bus"], manifest["target_classes"])

    def test_manifest_does_not_claim_current_runner_compatibility(self) -> None:
        manifest = json.loads(
            (ROOT / "09_deliverables" / "board_deploy" / "models" / "vehicle-detector.manifest.json").read_text(encoding="utf-8")
        )
        self.assertTrue(manifest["runner_source_contract_compatible"])
        self.assertFalse(manifest["runner_compatible"])
        self.assertFalse(manifest["current_runner_compatible"])
        self.assertFalse(manifest["direct_deployment"])
        self.assertEqual("PENDING", manifest["board_acl_validation"])

    def test_runner_manifest_has_aarch64_hash_and_no_bundled_acl_runtime(self) -> None:
        manifest = json.loads(
            (ROOT / "09_deliverables" / "board_deploy" / "bin" / "aarch64" / "runner-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        runner = manifest["runner"]
        self.assertEqual("AArch64", runner["architecture"])
        self.assertEqual(64, len(runner["sha256"]))
        self.assertIn("libascendcl.so", runner["dynamic_dependencies"])
        self.assertNotIn("libsmartbag_ss928_acl.so", runner["dynamic_dependencies"])

    def test_install_preflight_and_configs_use_formal_model_name(self) -> None:
        paths = [
            ROOT / "09_deliverables" / "board_deploy" / "install.sh",
            ROOT / "09_deliverables" / "board_deploy" / "preflight.sh",
            ROOT / "09_deliverables" / "board_deploy" / "config.example.json",
            ROOT / "06_software" / "board_runtime" / "smartbag_alert_controller" / "config.example.json",
        ]
        for path in paths:
            self.assertIn("vehicle-detector", path.read_text(encoding="utf-8"), str(path))

    def test_install_never_implicitly_overwrites_model_from_ignored_media(self) -> None:
        install = (ROOT / "09_deliverables" / "board_deploy" / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("08_media/models/ss928_yolo11n/yolo11n_ss928.om", install)
        self.assertIn("MODEL_SOURCE=${SMARTBAG_MODEL_SOURCE:-}", install)
        self.assertIn('elif [ -f "$MODEL_DEST" ]', install)

    def test_inventory_accounts_for_every_local_ai_model_path(self) -> None:
        inventory = json.loads((ROOT / "00_admin" / "local-model-inventory.json").read_text(encoding="utf-8"))
        self.assertEqual(21, len(inventory["models"]))
        self.assertEqual(16, sum(item["count"] for item in inventory["excluded_binary_groups"]))


if __name__ == "__main__":
    unittest.main()
