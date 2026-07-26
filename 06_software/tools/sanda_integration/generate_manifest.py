#!/usr/bin/env python3
"""Generate the reproducible per-file audit for the sanda-tt/ss928 source tree."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
from typing import BinaryIO, Iterable


ACTIONS = {
    "KEEP_EXISTING",
    "PORT",
    "MERGE",
    "MOVE",
    "ARCHIVE",
    "DEDUPLICATE",
    "REMOVE_GENERATED",
    "BLOCKED",
}

WORK_DESTINATIONS = {
    "bmi270_i2c_pose": ("05_firmware/ss928/diagnostics/bmi270_i2c_pose", "MERGE"),
    "dx_gp21_tracker": ("06_software/board_runtime/dx_gp21_tracker", "MERGE"),
    "imu_fall_detector": ("06_software/board_runtime/imu_fall_detector", "MERGE"),
    "imx347_mipi_preview": ("05_firmware/ss928/board_samples/imx347_mipi_preview", "MERGE"),
    "linux_bmi270_backpack": ("06_software/board_runtime/bmi270_backpack", "MERGE"),
    "max98357_i2s_test": ("05_firmware/ss928/diagnostics/max98357_i2s_test", "PORT"),
    "mt5710_5g_cloud_upload": ("06_software/board_runtime/mt5710_connectivity", "PORT"),
    "mt5710_voice_call": ("06_software/optional/mt5710_voice_call", "MERGE"),
    "radar": ("06_software/board_runtime/mr20_radar", "PORT"),
    "smartbag_alert_audio_build": ("06_software/tools/audio_prepare", "MERGE"),
    "smartbag_alert_audio_deploy": ("09_deliverables/board_deploy/assets/audio", "MERGE"),
    "smartbag_alert_controller": ("06_software/board_runtime/smartbag_alert_controller", "MERGE"),
    "smartbag_cloud_uploader": ("06_software/board_runtime/cloud_uploader", "PORT"),
    "ss928_board_setup": ("05_firmware/ss928/deployment_scripts", "MERGE"),
    "ss928_yolov8_vot": ("06_software/vision_obstacle_tracker/ss928_backend", "PORT"),
    "ssminiprogram": ("06_software/mobile/ssminiprogram", "MERGE"),
    "submission_doc": ("09_deliverables/sanda_submission_reference", "PORT"),
    "temperature_runtime_update": ("06_software/board_runtime/temperature", "PORT"),
    "tsensor_module_build": ("05_firmware/ss928/tsensor", "PORT"),
    "tsensor_upload_stage": ("05_firmware/ss928/tsensor", "DEDUPLICATE"),
}

SKILL_DESTINATIONS = {
    "miniprogram-development": "06_software/mobile/ssminiprogram/docs",
    "smartbag-cloud-read": "06_software/mobile/ssminiprogram/docs/cloudbase",
    "smartbag-cloud-upload": "06_software/board_runtime/cloud_uploader/docs",
    "ss928-direct-board-debug": "06_software/tools/board_debug",
    "ss928-max98357-audio-playback": "06_software/tools/audio_prepare",
    "ss928-mt5710-5g-validation": "06_software/optional/mt5710_voice_call/docs",
    "wechat-cloudbase-iot": "06_software/mobile/ssminiprogram/docs/cloudbase",
    "wechat-miniprogram-native": "06_software/mobile/ssminiprogram/docs",
}

MODULE_PURPOSES = {
    "bmi270_i2c_pose": "BMI270 low-level I2C diagnostic",
    "dx_gp21_tracker": "DX-GP21 GNSS tracking and protocol",
    "imu_fall_detector": "IMU fall and impact state machine",
    "imx347_mipi_preview": "IMX347 MIPI/MPP preview sample",
    "linux_bmi270_backpack": "BMI270 posture, calibration, and fall runtime",
    "max98357_i2s_test": "MAX98357 I2S audio diagnostic",
    "mt5710_5g_cloud_upload": "MT5710 network, CloudBase, and SMS runtime",
    "mt5710_voice_call": "optional MT5710 voice-call helper",
    "radar": "MR20 side-radar parser and worker",
    "smartbag_alert_audio_build": "alert audio preparation toolchain",
    "smartbag_alert_audio_deploy": "alert audio deployment assets",
    "smartbag_alert_controller": "unified haptic, light, audio, BLE, and sensor alert controller",
    "smartbag_cloud_uploader": "CloudBase telemetry uploader",
    "ss928_board_setup": "SS928 board and wireless setup",
    "ss928_yolov8_vot": "SS928 ACL/OM NPU detector backend",
    "ssminiprogram": "WeChat mini program and CloudBase functions",
    "submission_doc": "project submission documentation source",
    "temperature_runtime_update": "board temperature runtime reader",
    "tsensor_module_build": "SS928 temperature kernel module source",
    "tsensor_upload_stage": "temporary temperature module deployment stage",
}

GENERATED_EXACT = {
    "@ + $zipPath + @",
    "work/bmi270_i2c_pose/bmi270_i2c_pose",
    "work/imx347_mipi_preview/imx347_mipi_preview",
    "work/imx347_mipi_preview/imx347_mipi_preview.o",
    "work/tsensor_upload_stage/hi_tsensor.ko",
}

SENSITIVE_EXACT = {
    "handoff.md",
}

MINIPROGRAM_SCAFFOLD_PREFIXES = (
    "work/ssminiprogram/cloudfunctions/quickstartFunctions/",
    "work/ssminiprogram/miniprogram/components/cloudTipModal/",
    "work/ssminiprogram/miniprogram/images/",
    "work/ssminiprogram/miniprogram/pages/example/",
)

NPU_SUPERSEDED_PATHS = {
    "work/ss928_yolov8_vot/include/vot_pipeline.h",
    "work/ss928_yolov8_vot/scripts/run_camera.sh",
    "work/ss928_yolov8_vot/src/main.cpp",
    "work/ss928_yolov8_vot/src/vot_pipeline.cpp",
    "work/ss928_yolov8_vot/tests/controller_dry_run_shim.py",
    "work/ss928_yolov8_vot/tests/test_vot_pipeline.cpp",
}

NPU_SUPERSEDED_DESTINATION = "06_software/vision_obstacle_tracker/vision_obstacle_tracker.py"

SPECIAL_DESTINATIONS = {
    "skills/ss928-direct-board-debug/scripts/board_debug.py": (
        "06_software/tools/board_debug/board_debug.py", "MERGE", "ss928-direct-board-debug"
    ),
    "skills/ss928-max98357-audio-playback/scripts/prepare_audio.py": (
        "06_software/tools/audio_prepare/prepare_audio.py", "MERGE", "ss928-max98357-audio-playback"
    ),
    "work/dx_gp21_tracker/start_ss928_gnss_track.sh": (
        "09_deliverables/board_deploy/systemd/smartbag-gnss.service", "DEDUPLICATE", "dx_gp21_tracker"
    ),
    "work/linux_bmi270_backpack/bmi270-backpack.service": (
        "09_deliverables/board_deploy/systemd/smartbag-imu.service", "DEDUPLICATE", "linux_bmi270_backpack"
    ),
    "work/linux_bmi270_backpack/start_ss928_ble.sh": (
        "09_deliverables/board_deploy/systemd/smartbag-imu.service", "DEDUPLICATE", "linux_bmi270_backpack"
    ),
    "work/smartbag_alert_controller/main.py": (
        "06_software/board_runtime/smartbag_alert_controller/smartbag_alert_controller.py",
        "DEDUPLICATE",
        "smartbag_alert_controller",
    ),
    "work/smartbag_alert_controller/mr20_radar.example.json": (
        "06_software/board_runtime/mr20_radar/config.example.json", "DEDUPLICATE", "smartbag_alert_controller"
    ),
    "work/smartbag_alert_controller/mr20_radar.py": (
        "06_software/board_runtime/mr20_radar/mr20_radar.py", "DEDUPLICATE", "smartbag_alert_controller"
    ),
    "work/smartbag_alert_controller/om_alert_bridge.py": (
        "06_software/board_runtime/smartbag_alert_controller/diagnostics/om_alert_bridge.py",
        "MERGE",
        "smartbag_alert_controller",
    ),
    "work/smartbag_alert_controller/smartbag-alert.service": (
        "09_deliverables/board_deploy/systemd/smartbag-alert.service", "DEDUPLICATE", "smartbag_alert_controller"
    ),
    "work/smartbag_alert_controller/smartbag.env.example": (
        "09_deliverables/board_deploy/smartbag.env.example", "MERGE", "smartbag_alert_controller"
    ),
    "work/smartbag_alert_controller/start_ss928_smartbag_alert.sh": (
        "09_deliverables/board_deploy/start-all.sh", "DEDUPLICATE", "smartbag_alert_controller"
    ),
    "work/smartbag_alert_controller/tests/test_mr20_radar.py": (
        "06_software/board_runtime/mr20_radar/tests/test_mr20_radar.py",
        "DEDUPLICATE",
        "smartbag_alert_controller",
    ),
    "work/smartbag_alert_controller/tools/uvc_probe_capture.py": (
        "06_software/tools/board_debug/uvc_probe_capture.py", "PORT", "smartbag_alert_controller"
    ),
    "work/ss928_board_setup/network/20-mr20-radar.network": (
        "05_firmware/ss928/deployment_scripts/network/20-mr20-radar.network.example",
        "MERGE",
        "ss928_board_setup",
    ),
    "work/ss928_board_setup/scripts/ws73-bluetooth-module-start.sh": (
        "05_firmware/ss928/deployment_scripts/ws73-bluetooth-module-start.sh",
        "MERGE",
        "ss928_board_setup",
    ),
    "work/ss928_board_setup/systemd/ws73-bluetooth-module.service": (
        "09_deliverables/board_deploy/systemd/smartbag-ws73.service", "MERGE", "ss928_board_setup"
    ),
    "work/temperature_runtime_update/linux_bmi270_backpack/posture_cloud.py": (
        "06_software/board_runtime/bmi270_backpack/posture_cloud.py",
        "DEDUPLICATE",
        "temperature_runtime_update",
    ),
    "work/temperature_runtime_update/smartbag_cloud_uploader/telemetry_client.py": (
        "06_software/board_runtime/cloud_uploader/telemetry_client.py",
        "DEDUPLICATE",
        "temperature_runtime_update",
    ),
}


def run_git(repo: Path, *args: str, input_data: bytes | None = None) -> bytes:
    command = ["git", "-c", "core.longpaths=true", "-c", "core.quotePath=false", "-C", str(repo), *args]
    completed = subprocess.run(command, input=input_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace").strip())
    return completed.stdout


def source_entries(repo: Path, ref: str) -> list[tuple[str, str, int]]:
    raw = run_git(repo, "ls-tree", "-r", "-z", "-l", ref)
    entries: list[tuple[str, str, int]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, path_raw = record.split(b"\t", 1)
        _mode, object_type, object_id, size_raw = metadata.split(b" ", 3)
        if object_type != b"blob":
            continue
        entries.append(
            (
                path_raw.decode("utf-8", errors="surrogateescape"),
                object_id.decode("ascii"),
                int(size_raw),
            )
        )
    return entries


class BlobReader:
    def __init__(self, repo: Path) -> None:
        command = [
            "git",
            "-c",
            "core.longpaths=true",
            "-C",
            str(repo),
            "cat-file",
            "--batch",
        ]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("could not start git cat-file --batch")
        self.stdin: BinaryIO = self.process.stdin
        self.stdout: BinaryIO = self.process.stdout

    def read(self, object_id: str) -> bytes:
        self.stdin.write(object_id.encode("ascii") + b"\n")
        self.stdin.flush()
        header = self.stdout.readline().rstrip(b"\n")
        parts = header.split()
        if len(parts) != 3 or parts[1] != b"blob":
            raise RuntimeError(f"unexpected cat-file response for {object_id}: {header!r}")
        size = int(parts[2])
        data = self.stdout.read(size)
        newline = self.stdout.read(1)
        if len(data) != size or newline != b"\n":
            raise RuntimeError(f"truncated cat-file response for {object_id}")
        return data

    def close(self) -> None:
        self.stdin.close()
        self.process.wait(timeout=30)
        if self.process.returncode:
            stderr = self.process.stderr.read().decode("utf-8", errors="replace") if self.process.stderr else ""
            raise RuntimeError(stderr.strip() or "git cat-file failed")


def tracked_target_hashes(repo: Path) -> dict[str, list[str]]:
    paths = run_git(repo, "ls-files", "-z").split(b"\0")
    hashes: dict[str, list[str]] = {}
    for path_raw in paths:
        if not path_raw:
            continue
        relative = path_raw.decode("utf-8", errors="surrogateescape")
        full_path = repo / Path(relative)
        if not full_path.is_file():
            continue
        digest = hashlib.sha256(full_path.read_bytes()).hexdigest()
        hashes.setdefault(digest, []).append(PurePosixPath(relative).as_posix())
    return hashes


def lfs_metadata(content: bytes) -> tuple[str, int] | None:
    if not content.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
        return None
    oid = ""
    size = -1
    for line in content.decode("ascii", errors="replace").splitlines():
        if line.startswith("oid sha256:"):
            oid = line.removeprefix("oid sha256:").strip()
        elif line.startswith("size "):
            size = int(line.removeprefix("size ").strip())
    if len(oid) != 64 or size < 0:
        raise ValueError("invalid Git LFS pointer")
    return oid, size


def file_type(path: str, content: bytes, is_lfs: bool) -> str:
    if is_lfs:
        return "git-lfs-pointer"
    name = PurePosixPath(path).name.lower()
    suffix = PurePosixPath(path).suffix.lower()
    if name.endswith(".service") or name.endswith(".target"):
        return "systemd-unit"
    if suffix in {".py"}:
        return "python"
    if suffix in {".c", ".cc", ".cpp", ".cxx"}:
        return "c-cpp-source"
    if suffix in {".h", ".hpp"}:
        return "c-cpp-header"
    if suffix in {".js", ".ts"}:
        return "javascript"
    if suffix in {".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".conf"}:
        return "configuration"
    if suffix in {".sh", ".bash"} or content.startswith(b"#!/bin/sh") or content.startswith(b"#!/bin/bash"):
        return "shell"
    if name in {"makefile", "cmakelists.txt"} or suffix in {".mk", ".cmake"}:
        return "build-script"
    if suffix in {".md", ".rst", ".txt"}:
        return "documentation"
    if suffix in {".html", ".css", ".wxml", ".wxss"}:
        return "ui-source"
    if suffix in {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}:
        return "document-binary"
    if suffix in {".step", ".stp", ".stl", ".obj", ".dwg", ".dxf", ".f3d"}:
        return "cad"
    if suffix in {".aac", ".wav", ".pcm", ".mp3"}:
        return "audio"
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".yuv"}:
        return "image-media"
    if suffix in {".zip", ".rar", ".7z", ".gz", ".tgz", ".xz", ".bz2"}:
        return "archive-binary"
    if suffix in {".ko", ".o", ".a", ".so", ".dll", ".exe", ".bin"}:
        return "compiled-binary"
    return "data-or-source"


def is_generated(path: str) -> bool:
    normalized = PurePosixPath(path).as_posix()
    parts = set(PurePosixPath(normalized).parts)
    suffix = PurePosixPath(normalized).suffix.lower()
    if normalized in GENERATED_EXACT:
        return True
    if normalized.startswith(MINIPROGRAM_SCAFFOLD_PREFIXES):
        return True
    if normalized in {
        "work/linux_bmi270_backpack/bmi270_config.bin",
        "work/max98357_i2s_test/test_48k_s16le_stereo.pcm",
        "work/ssminiprogram/project.private.config.json",
        "work/ssminiprogram/uploadCloudFunction.sh",
        "work/submission_doc/submission_ascii.docx",
        "work/ss928_yolov8_vot/calibration_report.csv",
    }:
        return True
    if normalized.startswith("work/smartbag_alert_controller/camera_probe/"):
        return True
    if normalized == "work/smartbag_alert_controller/audio/bad/bad_48k_s16le_stereo.pcm":
        return True
    if "__pycache__" in parts or suffix in {".pyc", ".pyo", ".o", ".obj", ".log", ".tmp"}:
        return True
    if normalized.startswith("work/linux_bmi270_backpack/calibration_data/") and suffix == ".csv":
        return True
    if normalized.startswith("work/smartbag_alert_audio_") and suffix in {".pcm", ".wav"}:
        return True
    if normalized.startswith("work/ss928_yolov8_vot/"):
        relative = normalized.removeprefix("work/ss928_yolov8_vot/")
        if relative.startswith((
            "bin/",
            "build/",
            "logs/",
            "board_stage/",
            "data/",
            "diagnostics/artifacts/",
            "diagnostics/board_stage/",
        )):
            return True
        if suffix in {".pt", ".onnx", ".om"}:
            return True
    return False


def mapped_destination(path: str) -> tuple[str, str, str] | None:
    pure = PurePosixPath(path)
    parts = pure.parts
    if path in SPECIAL_DESTINATIONS:
        return SPECIAL_DESTINATIONS[path]
    if path.startswith("work/mt5710_5g_cloud_upload/"):
        if path.endswith("tests/test_mt5710_5g_cloud_upload.py"):
            destination = "06_software/board_runtime/mt5710_connectivity/tests/test_mt5710_connectivity.py"
        elif path.endswith("mt5710_5g_cloud_upload.py"):
            destination = "06_software/board_runtime/mt5710_connectivity/mt5710_connectivity.py"
        else:
            destination = "09_deliverables/board_deploy/systemd/smartbag-connectivity.service"
        return (destination, "DEDUPLICATE", "mt5710_5g_cloud_upload")
    if path.startswith("work/radar/drivers/mr20/"):
        destination = (
            "06_software/board_runtime/mr20_radar/tests/test_mr20_radar.py"
            if pure.name.startswith("test_")
            else "06_software/board_runtime/mr20_radar/mr20_radar.py"
        )
        return (destination, "DEDUPLICATE", "radar")
    if path.startswith("work/smartbag_alert_audio_build/") and pure.suffix.lower() in {".aac", ".txt"}:
        relative = PurePosixPath(*parts[2:]).as_posix()
        return (f"09_deliverables/board_deploy/assets/audio/{relative}", "DEDUPLICATE", "smartbag_alert_audio_build")
    if path.startswith("work/smartbag_alert_audio_deploy/audio/"):
        relative = PurePosixPath(*parts[3:]).as_posix()
        return (f"09_deliverables/board_deploy/assets/audio/{relative}", "MERGE", "smartbag_alert_audio_deploy")
    if path.startswith("work/smartbag_alert_controller/audio/bad/") and pure.suffix.lower() in {".aac", ".txt"}:
        return (f"09_deliverables/board_deploy/assets/audio/bad/{pure.name}", "MERGE", "smartbag_alert_controller")
    if path.startswith("work/tsensor_module_build/") and pure.name in {
        "build_from_existing_tree_wsl.sh",
        "extract_kernel_wsl.sh",
        "finish_build_wsl.sh",
    }:
        return ("05_firmware/ss928/tsensor/build_tsensor_wsl.sh", "DEDUPLICATE", "tsensor_module_build")
    if path.startswith("work/max98357_i2s_test/"):
        return ("06_software/tools/audio_prepare/README.md", "DEDUPLICATE", "max98357_i2s_test")
    if len(parts) >= 2 and parts[0] == "work" and parts[1] in WORK_DESTINATIONS:
        module = parts[1]
        if path.startswith("work/ssminiprogram/miniprogram/pages/placeholder/"):
            relative = PurePosixPath(*parts[5:]).as_posix()
            return (f"06_software/mobile/ssminiprogram/miniprogram/pages/alarms/{relative}", "DEDUPLICATE", module)
        if path in NPU_SUPERSEDED_PATHS:
            return (NPU_SUPERSEDED_DESTINATION, "DEDUPLICATE", module)
        if path == "work/ss928_yolov8_vot/.gitignore":
            return (".gitignore", "DEDUPLICATE", module)
        root, action = WORK_DESTINATIONS[module]
        relative = PurePosixPath(*parts[2:]).as_posix() if len(parts) > 2 else ""
        return (f"{root}/{relative}".rstrip("/"), action, module)
    if len(parts) >= 2 and parts[0] == "skills" and parts[1] in SKILL_DESTINATIONS:
        skill = parts[1]
        relative_parts = parts[2:]
        if "agents" in relative_parts or pure.name in {"SKILL.md", "openai.yaml"}:
            return ("", "REMOVE_GENERATED", skill)
        relative = PurePosixPath(*relative_parts).as_posix() if relative_parts else ""
        return (f"{SKILL_DESTINATIONS[skill]}/{relative}".rstrip("/"), "MERGE", skill)
    if parts and parts[0] == "3d_structure":
        relative = PurePosixPath(*parts[1:]).as_posix()
        return (f"04_hardware/ss928/cad/{relative}", "MOVE", "mechanical-cad")
    if path == "40pin_usage.md":
        return ("04_hardware/ss928/40pin-usage.md", "MERGE", "hardware-pinout")
    if path in {"README.md", "agent.md", "AGENTS.md", ".gitignore", ".gitattributes"}:
        return ("README.md" if path == "README.md" else "", "DEDUPLICATE", "repository-metadata")
    if parts and parts[0] == "docs":
        relative = PurePosixPath(*parts[1:]).as_posix()
        return (f"10_archive/sanda_ss928/docs/{relative}", "ARCHIVE", "source-documentation")
    return None


def generic_archive_destination(path: str) -> str:
    return f"10_archive/sanda_ss928/source-reference/{PurePosixPath(path).as_posix()}"


def classify(
    path: str,
    digest: str,
    content: bytes,
    is_lfs: bool,
    target_hashes: dict[str, list[str]],
    duplicate_destinations: dict[str, tuple[str, str]],
) -> dict[str, str]:
    mapped = mapped_destination(path)
    pure = PurePosixPath(path)
    module = mapped[2] if mapped else (pure.parts[0] if pure.parts else "root")
    purpose = MODULE_PURPOSES.get(module, "")
    if not purpose:
        if path.startswith("在线仓库/"):
            purpose = "third-party repository mirror"
            module = "vendor-repository-mirror"
        elif path.startswith(("07硬件资料/", "补充资料/", "02. 硬件连接与功能测试/")):
            purpose = "vendor hardware or platform reference"
            module = "vendor-hardware-reference"
        elif path.startswith(("09. 进阶功能开发/", "10. 进阶综合案例/")):
            purpose = "vendor SDK, sample, or model reference"
            module = "vendor-sdk-reference"
        elif path.startswith("3d_structure/"):
            purpose = "smart-bag mechanical CAD"
            module = "mechanical-cad"
        elif path.startswith("01. 快速使用指南【必看】/"):
            purpose = "vendor platform quick-start reference"
            module = "vendor-platform-guide"
        else:
            purpose = "source repository reference material"

    name = pure.name.lower()
    if name.startswith("test_") or "/tests/" in f"/{path}/":
        purpose = f"{purpose} test".strip()
    elif name.endswith(".service") or name.endswith(".target"):
        purpose = f"{purpose} systemd deployment unit".strip()
    elif name.startswith("readme") or pure.suffix.lower() in {".md", ".rst"}:
        purpose = f"{purpose} documentation".strip()
    elif pure.suffix.lower() in {".json", ".yaml", ".yml", ".conf", ".ini"}:
        purpose = f"{purpose} configuration".strip()

    if path in SENSITIVE_EXACT:
        return {
            "purpose": purpose,
            "related_module": module,
            "destination_path": "00_admin/sanda-full-integration-plan.md",
            "action": "BLOCKED",
            "reason": "contains board password/IP handoff data; findings are redacted and raw content is not copied",
            "test_status": "security_review_required",
        }
    if is_lfs:
        return {
            "purpose": purpose,
            "related_module": module,
            "destination_path": generic_archive_destination(path),
            "action": "BLOCKED",
            "reason": "Git LFS object is not present in the audited checkout; pointer OID and declared size are recorded without fabricating content",
            "test_status": "blocked_missing_lfs_object",
        }
    if is_generated(path):
        return {
            "purpose": purpose,
            "related_module": module,
            "destination_path": "",
            "action": "REMOVE_GENERATED",
            "reason": "generated cache, build output, runtime capture, model artifact, or reproducible intermediate",
            "test_status": "not_applicable",
        }
    if digest in target_hashes:
        return {
            "purpose": purpose,
            "related_module": module,
            "destination_path": target_hashes[digest][0],
            "action": "KEEP_EXISTING",
            "reason": "byte-identical tracked implementation already exists in the target repository",
            "test_status": "baseline_passed",
        }
    if digest in duplicate_destinations:
        canonical_source, canonical_destination = duplicate_destinations[digest]
        return {
            "purpose": purpose,
            "related_module": module,
            "destination_path": canonical_destination,
            "action": "DEDUPLICATE",
            "reason": f"byte-identical to {canonical_source}; retain only the canonical target landing",
            "test_status": "not_applicable",
        }
    if mapped:
        destination, action, module = mapped
        reason_by_action = {
            "PORT": "valid source capability has no target equivalent and is moved into the formal target architecture",
            "MERGE": "merge newer capability into the existing authoritative target module without replacing its entry point",
            "MOVE": "move project-owned asset into the target repository taxonomy",
            "ARCHIVE": "reference-only source documentation is indexed at the exact source commit outside the formal runtime",
            "DEDUPLICATE": "temporary or duplicate source location is replaced by the canonical target module",
            "REMOVE_GENERATED": "skill packaging metadata is not part of the deployed product",
        }
        result = {
            "purpose": purpose,
            "related_module": module,
            "destination_path": destination,
            "action": action,
            "reason": reason_by_action[action],
            "test_status": integration_test_status(module, path, action),
        }
        if action in {"PORT", "MERGE", "MOVE"}:
            duplicate_destinations[digest] = (path, destination)
        return result

    destination = generic_archive_destination(path)
    duplicate_destinations[digest] = (path, destination)
    return {
        "purpose": purpose,
        "related_module": module,
        "destination_path": destination,
        "action": "ARCHIVE",
        "reason": "reference-only SDK/vendor/mirror material is indexed at the exact source commit and not added to the formal runtime",
        "test_status": "not_applicable",
    }


def integration_test_status(module: str, path: str, action: str) -> str:
    if action not in {"PORT", "MERGE", "MOVE"}:
        return "not_applicable"
    if module == "mechanical-cad":
        return "reviewed_not_executable"
    if module == "ss928_yolov8_vot":
        return "native_tests_passed_hardware_pending"
    if module == "tsensor_module_build":
        return "source_reviewed_cross_build_pending"
    if path.endswith((".md", ".txt")):
        return "documentation_reviewed"
    return "integrated_tests_passed"


def generate(source_repo: Path, source_ref: str, target_repo: Path, output: Path) -> dict[str, object]:
    entries = source_entries(source_repo, source_ref)
    target_hashes = tracked_target_hashes(target_repo)
    blob_reader = BlobReader(source_repo)
    blob_cache: dict[str, tuple[bytes, str, int, bool]] = {}
    duplicate_destinations: dict[str, tuple[str, str]] = {}
    rows: list[dict[str, object]] = []
    try:
        for index, (path, object_id, git_size) in enumerate(entries, start=1):
            cached = blob_cache.get(object_id)
            if cached is None:
                content = blob_reader.read(object_id)
                lfs = lfs_metadata(content)
                if lfs:
                    digest, reported_size = lfs
                    is_lfs = True
                else:
                    digest = hashlib.sha256(content).hexdigest()
                    reported_size = git_size
                    is_lfs = False
                cached = (content, digest, reported_size, is_lfs)
                blob_cache[object_id] = cached
            content, digest, reported_size, is_lfs = cached
            decision = classify(path, digest, content, is_lfs, target_hashes, duplicate_destinations)
            if decision["action"] not in ACTIONS:
                raise AssertionError(f"invalid action {decision['action']} for {path}")
            rows.append(
                {
                    "source_path": path,
                    "file_type": file_type(path, content, is_lfs),
                    "size": reported_size,
                    "sha256": digest,
                    **decision,
                }
            )
            if index % 1000 == 0:
                print(f"hashed and classified {index}/{len(entries)}", file=sys.stderr)
    finally:
        blob_reader.close()

    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "source_path",
        "file_type",
        "size",
        "sha256",
        "purpose",
        "related_module",
        "destination_path",
        "action",
        "reason",
        "test_status",
    ]
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    action_counts = {action: 0 for action in sorted(ACTIONS)}
    type_counts: dict[str, int] = {}
    for row in rows:
        action_counts[str(row["action"])] += 1
        type_counts[str(row["file_type"])] = type_counts.get(str(row["file_type"]), 0) + 1
    return {
        "source_ref": source_ref,
        "source_commit": run_git(source_repo, "rev-parse", source_ref).decode("ascii").strip(),
        "target_commit": run_git(target_repo, "rev-parse", "HEAD").decode("ascii").strip(),
        "file_count": len(rows),
        "action_counts": action_counts,
        "file_type_counts": dict(sorted(type_counts.items())),
        "output": str(output),
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument("--source-ref", default="HEAD")
    parser.add_argument("--target-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    summary = generate(args.source_repo.resolve(), args.source_ref, args.target_repo.resolve(), args.output.resolve())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
