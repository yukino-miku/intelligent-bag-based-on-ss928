#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
for candidate in (
    Path("/root/smartbag/common"),
    Path("/root/smartbag/controller"),
    SCRIPT_DIR.parents[1] / "06_software" / "board_runtime" / "common",
    SCRIPT_DIR.parents[1] / "06_software" / "board_runtime" / "smartbag_alert_controller",
):
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from i2c_mux import I2cMuxTransaction  # noqa: E402
from haptics import TM6605_PLAY_REGISTER  # noqa: E402
from lights import LinuxSysfsPwm  # noqa: E402


def as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def integer(value: object) -> int:
    return int(str(value), 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Best-effort Rev2 actuator safe-off")
    parser.add_argument("--hardware", default="/etc/smartbag/hardware.json")
    parser.add_argument("--pwm-root", default="/sys/class/pwm")
    parser.add_argument("--sample-audio", default="/opt/sample/audio/sample_audio")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    report: dict[str, object] = {
        "type": "safe_off",
        "ts": time.time(),
        "pid": os.getpid(),
        "haptics": {},
        "lights": {},
        "audio": "not_attempted",
        "errors": [],
    }
    errors: list[str] = report["errors"]  # type: ignore[assignment]
    try:
        hardware = json.loads(Path(args.hardware).read_text(encoding="utf-8"))
    except Exception as exc:
        hardware = {}
        errors.append(f"hardware_config: {type(exc).__name__}: {exc}")

    mux = as_mapping(hardware.get("i2c_mux"))
    haptics = as_mapping(hardware.get("haptics"))
    if bool(haptics.get("backend") == "tm6605_lra"):
        for side, channel_key in (("left", "left_channel"), ("right", "right_channel")):
            try:
                if args.dry_run:
                    report["haptics"][side] = "dry_run"  # type: ignore[index]
                    continue
                transaction = I2cMuxTransaction(
                    str(mux.get("device", "/dev/i2c-0")),
                    integer(haptics.get("address", "0x2d")),
                    mux_address=integer(mux.get("address", "0x70")),
                    mux_channel=int(haptics[channel_key]),
                    lock_file=str(mux.get("lock_file", "/run/lock/smartbag-i2c0-mux.lock")),
                )
                transaction.execute(
                    lambda device: device.write(bytes((TM6605_PLAY_REGISTER, 0)))
                )
                report["haptics"][side] = "stopped"  # type: ignore[index]
            except Exception as exc:
                message = f"haptics.{side}: {type(exc).__name__}: {exc}"
                errors.append(message)
                report["haptics"][side] = "error"  # type: ignore[index]

    lights = as_mapping(hardware.get("lights"))
    if bool(lights.get("enabled", False)):
        pwm = LinuxSysfsPwm(Path(args.pwm_root), dry_run=args.dry_run)
        period_ns = int(lights.get("period_ns", 1_000_000))
        for side in ("left", "right"):
            try:
                spec = as_mapping(lights.get(side))
                channel = int(spec["channel"])
                chip = pwm.resolve_chip(spec.get("chip", "auto"), channel)
                pwm.set_output(chip, channel, period_ns, 0, False)
                report["lights"][side] = "off"  # type: ignore[index]
            except Exception as exc:
                message = f"lights.{side}: {type(exc).__name__}: {exc}"
                errors.append(message)
                report["lights"][side] = "error"  # type: ignore[index]

    try:
        if args.dry_run:
            report["audio"] = "dry_run"
        else:
            process_name = Path(args.sample_audio).name
            completed = subprocess.run(
                ["pkill", "-TERM", "-x", process_name],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2.0,
            )
            report["audio"] = "stopped" if completed.returncode == 0 else "not_running"
    except Exception as exc:
        errors.append(f"audio: {type(exc).__name__}: {exc}")
        report["audio"] = "error"

    report["final"] = "error" if errors else "safe"
    print(json.dumps(report, ensure_ascii=True, separators=(",", ":")))
    return 1 if args.strict and errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
