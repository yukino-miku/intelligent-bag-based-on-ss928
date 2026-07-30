#!/usr/bin/env python3
"""Validate MR20 network reachability, UDP frames, and complete scan assembly."""

from __future__ import annotations

import argparse
import json
import select
import socket
import subprocess
import sys
import time
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[2] / "06_software" / "board_runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from mr20_radar.mr20_radar import (  # noqa: E402
    MR20FrameError,
    MR20ObjectListStatus,
    MR20ScanAssembler,
    MR20Target,
    load_radar_configs,
    parse_mr20_frame,
)


def command_ok(command: list[str]) -> bool:
    try:
        return subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except FileNotFoundError:
        return False


def command_has_output(command: list[str]) -> bool:
    try:
        result = subprocess.run(command, text=True, capture_output=True)
        return result.returncode == 0 and bool(result.stdout.strip())
    except FileNotFoundError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="/etc/smartbag/mr20.json")
    parser.add_argument("--duration", type=float, default=8.0)
    parser.add_argument("--skip-network-check", action="store_true")
    args = parser.parse_args()
    radars, _risk = load_radar_configs(args.config)
    if not radars:
        raise SystemExit("FAIL no enabled MR20 radar is configured")

    sockets: dict[socket.socket, object] = {}
    state: dict[str, dict[str, object]] = {}
    try:
        for config in radars:
            if not args.skip_network_check:
                route_ok = command_ok(["ip", "route", "get", config.radar_ip])
                ping_ok = command_ok(["ping", "-c", "1", "-W", "1", config.radar_ip])
                arp_ok = command_has_output(["ip", "neigh", "show", "to", config.radar_ip])
                if not route_ok or (not ping_ok and not arp_ok):
                    raise RuntimeError(f"network route/reachability check failed for {config.name} {config.radar_ip}")
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((config.bind_host, config.port))
            sock.setblocking(False)
            sockets[sock] = config
            state[config.name] = {
                "assembler": MR20ScanAssembler(
                    config.name,
                    config.side,
                    timeout_s=config.scan_timeout_ms / 1000.0,
                    max_targets=config.max_targets_per_scan,
                ),
                "valid_frames": 0,
                "status_frames": 0,
                "target_frames": 0,
                "complete_scans": 0,
                "zero_target_scans": 0,
                "source_mismatch": 0,
            }

        deadline = time.monotonic() + max(1.0, args.duration)
        while time.monotonic() < deadline:
            readable, _, _ = select.select(list(sockets), [], [], 0.2)
            now_s = time.monotonic()
            for sock in readable:
                config = sockets[sock]
                payload, source = sock.recvfrom(2048)
                record = state[config.name]
                if source[0] != config.radar_ip:
                    record["source_mismatch"] = int(record["source_mismatch"]) + 1
                    continue
                try:
                    message = parse_mr20_frame(payload)
                except MR20FrameError:
                    continue
                record["valid_frames"] = int(record["valid_frames"]) + 1
                key = "status_frames" if isinstance(message, MR20ObjectListStatus) else "target_frames"
                record[key] = int(record[key]) + 1
                assembler = record["assembler"]
                for scan in assembler.push(message, now_s):
                    if scan.complete:
                        record["complete_scans"] = int(record["complete_scans"]) + 1
                        if not scan.targets:
                            record["zero_target_scans"] = int(record["zero_target_scans"]) + 1
            for config in radars:
                record = state[config.name]
                for scan in record["assembler"].flush_timeout(now_s):
                    if scan.complete:
                        record["complete_scans"] = int(record["complete_scans"]) + 1

        result = {"duration_s": args.duration, "radars": {}}
        failed = False
        for config in radars:
            record = state[config.name]
            statistics = record.pop("assembler").statistics.as_dict(time.monotonic())
            public = {**record, **statistics}
            public["healthy"] = bool(
                public["valid_frames"] > 0
                and public["status_frames"] > 0
                and public["complete_scans"] > 0
            )
            failed = failed or not public["healthy"]
            result["radars"][config.name] = public
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if failed else 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    finally:
        for sock in sockets:
            sock.close()


if __name__ == "__main__":
    raise SystemExit(main())
