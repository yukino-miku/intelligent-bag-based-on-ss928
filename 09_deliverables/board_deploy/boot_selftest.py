#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path


def digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def read_text(path: Path, default: str = "unknown") -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return default


def unit_state(unit: str) -> str:
    completed = subprocess.run(
        ["systemctl", "is-active", unit],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=5.0,
    )
    return completed.stdout.strip() or "unknown"


def atomic_write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Write one SS928 SmartBag boot self-test report")
    parser.add_argument("--config", default="/etc/smartbag/config.json")
    parser.add_argument("--hardware", default="/etc/smartbag/hardware.json")
    parser.add_argument("--output-dir", default="/var/log/smartbag/boot-selftest")
    args = parser.parse_args()

    config_path = Path(args.config)
    hardware_path = Path(args.hardware)
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        config = {}
        config_error = f"{type(exc).__name__}: {exc}"
    else:
        config_error = ""
    paths = config.get("paths") if isinstance(config.get("paths"), dict) else {}
    cameras = config.get("cameras") if isinstance(config.get("cameras"), dict) else {}
    filesystem = {
        "config": config_path.is_file(),
        "hardware": hardware_path.is_file(),
        "python": Path(str(paths.get("python", "/root/smartbag/venv/bin/python"))).is_file(),
        "model": Path(str(paths.get("model", "/root/smartbag/models/yolo11n.pt"))).is_file(),
    }
    for side in ("left", "right"):
        camera = cameras.get(side) if isinstance(cameras.get(side), dict) else {}
        filesystem[f"camera_{side}"] = Path(str(camera.get("camera_device", ""))).exists()
    waits = {}
    wait_root = Path("/run/smartbag/waits")
    for path in sorted(wait_root.glob("*.json")) if wait_root.exists() else ():
        try:
            waits[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            waits[path.stem] = {"final": "invalid", "error": str(exc)}
    services = {
        unit: unit_state(unit)
        for unit in ("smartbag.target", "smartbag-controller.service", "bluetooth.service")
    }
    controller_status_path = Path("/run/smartbag/controller-status.json")
    try:
        controller_status = json.loads(controller_status_path.read_text(encoding="utf-8"))
    except Exception as exc:
        controller_status = {"error": f"{type(exc).__name__}: {exc}"}
    core_ready = (
        not config_error
        and all(filesystem.values())
        and services["smartbag.target"] == "active"
        and services["smartbag-controller.service"] == "active"
    )
    optional_degraded = services["bluetooth.service"] != "active" or any(
        isinstance(value, dict) and value.get("final") == "degraded" for value in waits.values()
    )
    final = "ready" if core_ready and not optional_degraded else "degraded" if core_ready else "failed"
    report = {
        "type": "boot_selftest",
        "ts": time.time(),
        "boot_id": read_text(Path("/proc/sys/kernel/random/boot_id")),
        "code_commit": read_text(Path("/root/smartbag/REVISION")),
        "config_sha256": digest(config_path),
        "hardware_sha256": digest(hardware_path),
        "config_error": config_error,
        "services": services,
        "filesystem": filesystem,
        "wait_reports": waits,
        "controller_status": controller_status,
        "final": final,
    }
    output_dir = Path(args.output_dir)
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    atomic_write(output_dir / f"{timestamp}.json", report)
    atomic_write(output_dir / "latest.json", report)
    print(json.dumps(report, ensure_ascii=True, separators=(",", ":")))
    return 0 if core_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
