#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable


PHASES = (
    "preflight", "i2c", "haptics", "lights", "audio", "gnss", "imu",
    "radar", "camera", "vision", "ble", "integration", "boot",
)


class Validation:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.script_dir = Path(__file__).resolve().parent
        repo_root = self.script_dir.parents[1]
        session_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        if (repo_root / "08_media").is_dir():
            self.output_dir = repo_root / "08_media" / "rev2-autonomous" / session_id
        else:
            self.output_dir = Path(args.output_dir or "/var/log/smartbag/rev2-validation") / session_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results: dict[str, dict[str, object]] = {}
        self.python = Path("/root/smartbag/venv/bin/python")
        if not self.python.is_file():
            self.python = Path(sys.executable)

    def command(self, phase: str, argv: list[str], timeout_s: float = 60.0) -> bool:
        started = time.monotonic()
        try:
            completed = subprocess.run(
                argv,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout_s,
            )
            output = completed.stdout
            returncode = completed.returncode
            error = ""
        except Exception as exc:
            output = ""
            returncode = -1
            error = f"{type(exc).__name__}: {exc}"
        (self.output_dir / f"{phase}.log").write_text(output + ("\n" + error if error else ""), encoding="utf-8")
        self.results[phase] = {
            "status": "passed" if returncode == 0 else "failed",
            "returncode": returncode,
            "duration_s": round(time.monotonic() - started, 3),
            "command": argv,
            "error": error,
        }
        return returncode == 0

    def safe_off(self) -> None:
        subprocess.run(
            [str(self.python), str(self.script_dir / "safe_off.py"), "--hardware", self.args.hardware],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10.0,
        )

    def preflight(self) -> bool:
        return self.command("preflight", [str(self.script_dir / "preflight.sh"), self.args.config], 120)

    def i2c(self) -> bool:
        return self.command("i2c", [str(self.script_dir / "i2c-mux-test.sh")], 60)

    def haptics(self) -> bool:
        return self.live_sequence("haptics", "tm6605-test.sh", (1, 2, 3, 4))

    def lights(self) -> bool:
        return self.live_sequence("lights", "light-test.sh", (1, 2, 3, 4))

    def live_sequence(self, phase: str, script: str, levels: tuple[int, ...]) -> bool:
        if not self.args.allow_live_output:
            self.results[phase] = {"status": "blocked", "reason": "--allow-live-output is required"}
            return False
        self.safe_off()
        commands = [
            f"{self.script_dir / script} {side} {level} --confirm-live-output"
            for side in ("left", "right") for level in levels
        ]
        shell = "set -eu; trap '" + str(self.python) + " " + str(self.script_dir / "safe_off.py") + " --hardware " + self.args.hardware + " >/dev/null 2>&1 || true' EXIT INT TERM; " + "; ".join(commands)
        return self.command(phase, ["sh", "-c", shell], 180)

    def audio(self) -> bool:
        if not self.args.allow_live_output:
            self.results["audio"] = {"status": "blocked", "reason": "--allow-live-output is required"}
            return False
        script = """
import sys,time
from pathlib import Path
sys.path[:0]=['/root/smartbag/controller','/root/smartbag/common']
from smartbag_alert_controller import AudioPlayer
p=AudioPlayer(Path('/root/smartbag/audio'))
try:
 p.setup(); p.start()
 for clip in ('L3','R3','L4','R4'):
  p.request(clip); time.sleep(1.0); p.clear()
 print(p.status())
finally: p.stop()
"""
        return self.command("audio", [str(self.python), "-c", script], 45)

    def gnss(self) -> bool:
        return self.command("gnss", [str(self.python), str(self.script_dir / "wait_for_hardware.py"), "--profile", "gnss", "--config", self.args.config, "--timeout-s", "15"], 25)

    def imu(self) -> bool:
        return self.command("imu", [str(self.python), str(self.script_dir / "wait_for_hardware.py"), "--profile", "imu", "--config", self.args.config, "--timeout-s", "15"], 25)

    def radar(self) -> bool:
        return self.command("radar", [str(self.script_dir / "mr20-network-preflight.sh")], 45)

    def camera(self) -> bool:
        config = json.loads(Path(self.args.config).read_text(encoding="utf-8"))
        commands = [str(self.script_dir / "camera-test.sh") + " " + str(config["cameras"][side]["camera_device"]) for side in ("left", "right")]
        return self.command("camera", ["sh", "-c", "set -eu; " + "; ".join(commands)], 45)

    def vision(self) -> bool:
        return self.command("vision", ["sh", "-c", "systemctl is-active smartbag-controller.service && curl -fsS http://127.0.0.1:8080/api/v1/status"], 20)

    def ble(self) -> bool:
        return self.command("ble", ["sh", "-c", "systemctl is-active bluetooth.service && bluetoothctl show"], 20)

    def integration(self) -> bool:
        return self.command("integration", ["sh", "-c", "systemctl is-active smartbag.target smartbag-controller.service && test -s /run/smartbag/controller-status.json"], 20)

    def boot(self) -> bool:
        return self.command("boot", [str(self.python), str(self.script_dir / "boot_selftest.py"), "--config", self.args.config, "--hardware", self.args.hardware], 90)

    def run(self, phases: list[str]) -> int:
        methods: dict[str, Callable[[], bool]] = {phase: getattr(self, phase) for phase in PHASES}
        for phase in phases:
            if phase in ("haptics", "lights", "audio"):
                self.safe_off()
            methods[phase]()
            if phase in ("haptics", "lights", "audio"):
                self.safe_off()
        failed = [name for name, result in self.results.items() if result.get("status") != "passed"]
        summary = {
            "type": "rev2_board_validation",
            "ts": time.time(),
            "phases": phases,
            "results": self.results,
            "final": "passed" if not failed else "failed",
            "failed_phases": failed,
            "physical_note": "Actuator electrical exercise is not physical amplitude verification.",
        }
        (self.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with (self.output_dir / "summary.md").open("w", encoding="utf-8") as handle:
            handle.write("# Rev2 board validation\n\n")
            handle.write(f"- final: `{summary['final']}`\n")
            for name, result in self.results.items():
                handle.write(f"- `{name}`: `{result.get('status')}`\n")
        print(json.dumps(summary, ensure_ascii=True, separators=(",", ":")))
        return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="SS928 Rev2 board validation orchestrator")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--phase", choices=PHASES)
    group.add_argument("--all", action="store_true")
    parser.add_argument("--config", default="/etc/smartbag/config.json")
    parser.add_argument("--hardware", default="/etc/smartbag/hardware.json")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--allow-live-output", action="store_true")
    args = parser.parse_args()
    return Validation(args).run(list(PHASES) if args.all else [args.phase])


if __name__ == "__main__":
    raise SystemExit(main())
