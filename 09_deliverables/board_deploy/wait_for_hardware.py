#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


@dataclass
class WaitResult:
    name: str
    required: bool
    attempts: int = 0
    wait_started_ts: float = 0.0
    wait_duration_s: float = 0.0
    final_state: str = "waiting"
    last_error: str = ""


def load_json(path: str) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def path_check(path: str) -> Callable[[], tuple[bool, str]]:
    def check() -> tuple[bool, str]:
        exists = Path(path).exists()
        return exists, "" if exists else f"missing {path}"

    return check


def build_checks(profile: str, config: dict[str, object]) -> list[tuple[str, bool, Callable[[], tuple[bool, str]]]]:
    paths = config.get("paths") if isinstance(config.get("paths"), dict) else {}
    cameras = config.get("cameras") if isinstance(config.get("cameras"), dict) else {}
    audio = config.get("audio") if isinstance(config.get("audio"), dict) else {}
    checks: list[tuple[str, bool, Callable[[], tuple[bool, str]]]] = []

    def add(name: str, required: bool, path: object) -> None:
        checks.append((name, required, path_check(str(path))))

    if profile in ("controller", "vision"):
        add("model", True, paths.get("model", "/root/smartbag/models/yolo11n.pt"))
        for side in ("left", "right"):
            camera = cameras.get(side) if isinstance(cameras.get(side), dict) else {}
            add(f"camera_{side}", True, camera.get("camera_device", f"/dev/video{side == 'right'}"))
    if profile in ("controller", "imu"):
        add("i2c0", True, "/dev/i2c-0")
    if profile in ("controller", "gnss"):
        add("uart4", profile == "gnss", "/dev/ttyAMA4")
    if profile in ("controller", "lights"):
        add("pwm", False, "/sys/class/pwm")
    if profile in ("controller", "ble"):
        add("bluetooth", False, "/sys/class/bluetooth/hci0")
    if profile in ("controller", "radar"):
        add("eth1", False, "/sys/class/net/eth1")
    if profile in ("controller", "audio") and bool(audio.get("enabled", False)):
        add("sample_audio", False, "/opt/sample/audio/sample_audio")
        root = Path(str(audio.get("root", "/root/smartbag/audio")))
        for clip in ("L3", "R3", "L4", "R4"):
            add(f"audio_{clip}", False, root / clip / "audio_chn0.aac")
    return checks


def atomic_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded SS928 device-node wait")
    parser.add_argument("--profile", choices=("controller", "vision", "imu", "gnss", "lights", "ble", "radar", "audio"), default="controller")
    parser.add_argument("--config", default="/etc/smartbag/config.json")
    parser.add_argument("--timeout-s", type=float, default=20.0)
    parser.add_argument("--interval-s", type=float, default=0.25)
    parser.add_argument("--optional-grace-s", type=float, default=3.0)
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    started_wall = time.time()
    started = time.monotonic()
    try:
        config = load_json(args.config)
    except Exception as exc:
        print(json.dumps({"profile": args.profile, "final": "failed", "last_error": str(exc)}))
        return 1
    checks = build_checks(args.profile, config)
    results = {
        name: WaitResult(name=name, required=required, wait_started_ts=started_wall)
        for name, required, _check in checks
    }
    deadline = started + max(0.0, args.timeout_s)
    optional_deadline = started + min(max(0.0, args.optional_grace_s), max(0.0, args.timeout_s))
    while True:
        all_required_ready = True
        all_ready = True
        for name, required, check in checks:
            result = results[name]
            if result.final_state == "ready":
                continue
            result.attempts += 1
            try:
                ready, error = check()
            except Exception as exc:
                ready, error = False, f"{type(exc).__name__}: {exc}"
            result.last_error = error
            if ready:
                result.final_state = "ready"
            else:
                all_ready = False
                if required:
                    all_required_ready = False
        now = time.monotonic()
        if all_ready or (all_required_ready and now >= optional_deadline) or now >= deadline:
            break
        time.sleep(max(0.01, args.interval_s))

    elapsed = time.monotonic() - started
    required_failed = False
    for result in results.values():
        result.wait_duration_s = round(elapsed, 3)
        if result.final_state != "ready":
            result.final_state = "failed" if result.required else "degraded"
            required_failed = required_failed or result.required
    report = {
        "profile": args.profile,
        "wait_started_ts": started_wall,
        "wait_duration_s": round(elapsed, 3),
        "final": "failed" if required_failed else "ready" if all(r.final_state == "ready" for r in results.values()) else "degraded",
        "checks": {name: asdict(result) for name, result in results.items()},
    }
    destination = Path(args.report or f"/run/smartbag/waits/{args.profile}.json")
    atomic_write(destination, report)
    print(json.dumps(report, ensure_ascii=True, separators=(",", ":")))
    return 1 if required_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
