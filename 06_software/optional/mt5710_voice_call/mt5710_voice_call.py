#!/usr/bin/env python3
"""Small MT5710 voice-call helper for the SS928 board."""

from __future__ import annotations

import argparse
import os
import re
import select
import sys
import termios
import time


OK_TOKENS = ("OK", "ERROR", "COMMAND NOT SUPPORT", "NO CARRIER", "BUSY", "NO ANSWER")


def configure_serial(fd: int, baud: int) -> None:
    attrs = termios.tcgetattr(fd)
    iflag, oflag, cflag, lflag, ispeed, ospeed, cc = attrs
    iflag = 0
    oflag = 0
    lflag = 0
    cflag |= termios.CLOCAL | termios.CREAD | termios.CS8
    cflag &= ~(termios.PARENB | termios.CSTOPB | termios.CRTSCTS)
    speed = getattr(termios, f"B{baud}", termios.B115200)
    termios.tcsetattr(fd, termios.TCSANOW, [iflag, oflag, cflag, lflag, speed, speed, cc])
    termios.tcflush(fd, termios.TCIOFLUSH)


def open_port(path: str, baud: int) -> int:
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    configure_serial(fd, baud)
    return fd


def read_lines(fd: int, timeout: float) -> list[str]:
    deadline = time.monotonic() + timeout
    data = bytearray()
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        readable, _, _ = select.select([fd], [], [], min(0.2, remaining))
        if not readable:
            continue
        try:
            chunk = os.read(fd, 4096)
        except BlockingIOError:
            continue
        if not chunk:
            break
        data.extend(chunk)
    text = data.decode("utf-8", errors="replace")
    return [line.strip() for line in re.split(r"[\r\n]+", text) if line.strip()]


def send_command(fd: int, command: str, timeout: float = 3.0, quiet: bool = False) -> list[str]:
    if not quiet:
        print(f"> {command}", flush=True)
    os.write(fd, (command + "\r\n").encode("ascii"))
    lines: list[str] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        new_lines = read_lines(fd, min(0.5, max(0.0, deadline - time.monotonic())))
        for line in new_lines:
            if line == command:
                continue
            lines.append(line)
            if not quiet:
                print(line, flush=True)
        if any(line in OK_TOKENS for line in lines):
            break
    return lines


def run_probe(fd: int) -> int:
    commands = [
        "ATE0",
        "AT",
        "AT+CPIN?",
        "AT+CFUN?",
        "AT+COPS?",
        "AT+CEREG?",
        "AT+C5GREG?",
        "AT+CGATT?",
        "AT+CLCC",
        "AT+CMUT?",
        "AT+CLVL?",
        "AT^SYSINFOEX",
    ]
    for command in commands:
        send_command(fd, command, timeout=4.0)
        time.sleep(0.2)
    return 0


def clcc_has_call(lines: list[str]) -> bool:
    return any(line.startswith("+CLCC:") for line in lines)


def call_state_label(lines: list[str]) -> str:
    for line in lines:
        if line.startswith("+CLCC:"):
            parts = line.split(":", 1)[1].split(",")
            if len(parts) >= 3:
                state = parts[2].strip()
                return {
                    "0": "active",
                    "1": "held",
                    "2": "dialing",
                    "3": "alerting/ringing",
                    "4": "incoming",
                    "5": "waiting",
                }.get(state, f"state={state}")
    if any(line in ("NO CARRIER", "BUSY", "NO ANSWER") for line in lines):
        return "ended"
    return "no-call"


def dial_and_monitor(fd: int, number: str, poll_seconds: float, max_seconds: float) -> int:
    send_command(fd, "ATE0", timeout=2.0)
    print(f"> ATD{number};", flush=True)
    os.write(fd, f"ATD{number};\r\n".encode("ascii"))
    start = time.monotonic()
    last_had_call = False
    last_state = ""

    while True:
        unsolicited = read_lines(fd, poll_seconds)
        for line in unsolicited:
            print(line, flush=True)

        clcc_lines = send_command(fd, "AT+CLCC", timeout=3.0, quiet=True)
        for line in clcc_lines:
            print(line, flush=True)

        state = call_state_label(clcc_lines + unsolicited)
        had_call = clcc_has_call(clcc_lines) or any(line.startswith("^CCALLSTATE:") for line in unsolicited)
        if state != last_state:
            print(f"# call_state={state}", flush=True)
            last_state = state
        if had_call:
            last_had_call = True
        elif last_had_call and state == "no-call":
            print("# call ended by network/remote side; no ATH was sent", flush=True)
            return 0

        if max_seconds > 0 and time.monotonic() - start >= max_seconds:
            print("# max monitor time reached; no ATH was sent", flush=True)
            return 124


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="/dev/ttyUSB1")
    parser.add_argument("--baud", type=int, default=115200)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("probe")
    dial = sub.add_parser("dial")
    dial.add_argument("number")
    dial.add_argument("--poll-seconds", type=float, default=2.0)
    dial.add_argument("--max-seconds", type=float, default=0.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    fd = open_port(args.port, args.baud)
    try:
        if args.action == "probe":
            return run_probe(fd)
        if args.action == "dial":
            return dial_and_monitor(fd, args.number, args.poll_seconds, args.max_seconds)
    finally:
        os.close(fd)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
