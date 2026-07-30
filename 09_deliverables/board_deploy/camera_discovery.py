#!/usr/bin/env python3
"""Discover and assign fixed USB camera ports without opening both streams together."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import glob
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


def udev_properties(device: str) -> dict[str, str]:
    try:
        output = subprocess.check_output(
            ["udevadm", "info", "--query=property", f"--name={device}"], text=True, stderr=subprocess.DEVNULL
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return {}
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    return values


def discover() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    candidates = sorted(glob.glob("/dev/v4l/by-path/*-video-index0"))
    if not candidates:
        candidates = sorted(glob.glob("/dev/video*"))
    physical_ids: set[str] = set()
    for candidate in candidates:
        real_device = os.path.realpath(candidate)
        props = udev_properties(real_device)
        index_path = Path("/sys/class/video4linux") / Path(real_device).name / "index"
        try:
            capture_index = int(index_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            capture_index = int(props.get("ID_V4L_CAPABILITIES", "0") == "")
        if capture_index != 0:
            continue
        id_path = props.get("ID_PATH", Path(candidate).name.removesuffix("-video-index0"))
        physical_key = f"{id_path}|{props.get('ID_SERIAL_SHORT', '')}"
        if physical_key in physical_ids:
            continue
        physical_ids.add(physical_key)
        records.append(
            {
                "by_path": candidate,
                "real_device": real_device,
                "id_path": id_path,
                "serial": props.get("ID_SERIAL_SHORT", ""),
                "vendor_id": props.get("ID_VENDOR_ID", ""),
                "model_id": props.get("ID_MODEL_ID", ""),
                "model": props.get("ID_MODEL", ""),
            }
        )
    return records


def validate_assignment(left: dict[str, Any], right: dict[str, Any]) -> None:
    if os.path.realpath(str(left["real_device"])) == os.path.realpath(str(right["real_device"])):
        raise ValueError("left and right camera resolve to the same video device")
    if str(left.get("id_path", "")) == str(right.get("id_path", "")):
        raise ValueError("left and right camera have the same physical ID_PATH")


def test_snapshot(device: str) -> None:
    command = [
        "v4l2-ctl", "--device", device, "--stream-mmap=3", "--stream-count=1", "--stream-to=/dev/null"
    ]
    try:
        subprocess.run(command, check=True, timeout=8, stdout=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise RuntimeError("v4l2-ctl is required for sequential camera validation") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"camera snapshot failed: {device}") from exc


def select_record(records: list[dict[str, Any]], path: str) -> dict[str, Any]:
    requested = os.path.realpath(path)
    for record in records:
        if record["by_path"] == path or os.path.realpath(str(record["real_device"])) == requested:
            return record
    raise ValueError(f"camera is not a discovered by-path capture node: {path}")


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def update_config(config_path: Path) -> None:
    if not config_path.is_file():
        return
    data = json.loads(config_path.read_text(encoding="utf-8"))
    data["cameras"]["left"]["camera_device"] = "/dev/smartbag-camera-left"
    data["cameras"]["right"]["camera_device"] = "/dev/smartbag-camera-right"
    data["snapshot_classifier"]["left_device"] = "/dev/smartbag-camera-left"
    data["snapshot_classifier"]["right_device"] = "/dev/smartbag-camera-right"
    atomic_json(config_path, data)


def validate_saved_assignment(
    discovery_path: Path,
    *,
    skip_snapshot_test: bool = False,
) -> dict[str, Any]:
    data = json.loads(discovery_path.read_text(encoding="utf-8"))
    records = discover()
    current_by_id = {str(record.get("id_path", "")): record for record in records}
    resolved: dict[str, dict[str, Any]] = {}
    for side in ("left", "right"):
        saved = data.get(side)
        if not isinstance(saved, dict):
            raise ValueError(f"saved assignment is missing {side}")
        current = current_by_id.get(str(saved.get("id_path", "")))
        if current is None:
            raise ValueError(f"saved {side} camera is not currently connected")
        for identity_key in ("serial", "vendor_id", "model_id"):
            expected = str(saved.get(identity_key, ""))
            actual = str(current.get(identity_key, ""))
            if expected and actual and expected != actual:
                raise ValueError(f"saved {side} camera {identity_key} changed")
        if not skip_snapshot_test:
            test_snapshot(str(current["by_path"]))
        resolved[side] = current
    validate_assignment(resolved["left"], resolved["right"])
    return {
        "valid": True,
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "left": resolved["left"],
        "right": resolved["right"],
    }


def rules_text(data: dict[str, Any]) -> str:
    lines = ["# Generated by SmartBag camera-udev-install.sh; match physical USB port and capture index 0."]
    for side in ("left", "right"):
        id_path = str(data[side].get("id_path", ""))
        if not id_path:
            raise ValueError(f"missing ID_PATH for {side} camera")
        if '"' in id_path or "\n" in id_path:
            raise ValueError("unsafe ID_PATH in hardware discovery data")
        lines.append(
            f'SUBSYSTEM=="video4linux", ATTR{{index}}=="0", ENV{{ID_PATH}}=="{id_path}", '
            f'SYMLINK+="smartbag-camera-{side}"'
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    discover_parser = subparsers.add_parser("discover")
    discover_parser.add_argument("--output", type=Path)
    assign_parser = subparsers.add_parser("assign")
    assign_parser.add_argument("--left", required=True)
    assign_parser.add_argument("--right", required=True)
    assign_parser.add_argument("--output", type=Path, default=Path("/etc/smartbag/hardware-discovery.json"))
    assign_parser.add_argument("--config", type=Path, default=Path("/etc/smartbag/config.json"))
    assign_parser.add_argument("--skip-snapshot-test", action="store_true")
    rules_parser = subparsers.add_parser("rules")
    rules_parser.add_argument("--discovery", type=Path, default=Path("/etc/smartbag/hardware-discovery.json"))
    rules_parser.add_argument("--output", type=Path, default=Path("/etc/udev/rules.d/99-smartbag-cameras.rules"))
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--discovery", type=Path, default=Path("/etc/smartbag/hardware-discovery.json"))
    validate_parser.add_argument("--skip-snapshot-test", action="store_true")
    args = parser.parse_args()

    try:
        records = discover()
        if args.command == "discover":
            result = {"generated_at": datetime.now(timezone.utc).isoformat(), "cameras": records}
            if args.output:
                atomic_json(args.output, result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "assign":
            left = select_record(records, args.left)
            right = select_record(records, args.right)
            validate_assignment(left, right)
            if not args.skip_snapshot_test:
                test_snapshot(str(left["by_path"]))
                test_snapshot(str(right["by_path"]))
            result = {
                "schema_version": 1,
                "assigned_at": datetime.now(timezone.utc).isoformat(),
                "capture_policy": "alternating; never STREAMON both devices together",
                "left": left,
                "right": right,
            }
            atomic_json(args.output, result)
            update_config(args.config)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "validate":
            print(json.dumps(
                validate_saved_assignment(args.discovery, skip_snapshot_test=args.skip_snapshot_test),
                ensure_ascii=False,
                indent=2,
            ))
            return 0
        data = json.loads(args.discovery.read_text(encoding="utf-8"))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rules_text(data), encoding="utf-8", newline="\n")
        print(args.output)
        return 0
    except (KeyError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
