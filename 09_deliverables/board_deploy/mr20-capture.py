#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import socket
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture raw MR20 UDP datagrams without interpreting risk")
    parser.add_argument("--bind", default="192.168.1.102")
    parser.add_argument("--port", type=int, default=2368)
    parser.add_argument("--source-ip", default="192.168.1.200")
    parser.add_argument("--source-port", type=int, default=2369)
    parser.add_argument("--duration-s", type=float, default=30.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.5)
    sock.bind((args.bind, args.port))
    deadline = time.monotonic() + args.duration_s
    count = 0
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("received_monotonic_s", "source_ip", "source_port", "bytes", "hex"))
        while time.monotonic() < deadline:
            try:
                payload, source = sock.recvfrom(65535)
            except socket.timeout:
                continue
            if source != (args.source_ip, args.source_port):
                continue
            writer.writerow((time.monotonic(), source[0], source[1], len(payload), payload.hex()))
            count += 1
    print(f"captured_datagrams={count} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
