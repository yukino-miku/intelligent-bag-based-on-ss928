from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import sys
import time
from pathlib import Path
from typing import Any

try:
    import serial
except ModuleNotFoundError:  # Keep pure helpers importable without the optional tool dependency.
    serial = None  # type: ignore[assignment]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transfer one file to or from a logged-in Linux serial console."
    )
    parser.add_argument("local_file", type=Path)
    parser.add_argument("remote_file")
    parser.add_argument(
        "--receive",
        action="store_true",
        help="download remote_file to local_file instead of uploading",
    )
    parser.add_argument("--port", default="COM3")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--timeout-s", type=float, default=180.0)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_until(port: Any, marker: bytes, timeout_s: float) -> bytes:
    deadline = time.monotonic() + timeout_s
    received = bytearray()
    while marker not in received:
        if time.monotonic() >= deadline:
            tail = bytes(received[-1000:]).decode("utf-8", "replace")
            raise TimeoutError(f"timed out waiting for {marker!r}; serial tail: {tail}")
        chunk = port.read(4096)
        if chunk:
            received.extend(chunk)
            if len(received) > 1024 * 1024:
                del received[:-65536]
    return bytes(received)


def read_marker_line(port: Any, marker: bytes, timeout_s: float) -> bytes:
    response = read_until(port, marker, timeout_s)
    tail = response.split(marker, 1)[1]
    if b"\n" not in tail:
        tail += read_until(port, b"\n", timeout_s)
    return tail.splitlines()[0].rstrip(b"\r")


def receiver_command(remote_file: str, size: int) -> str:
    receiver = """import hashlib
import os
import sys
import termios
import tty

path = sys.argv[1]
size = int(sys.argv[2])
part = path + ".part"
fd = sys.stdin.fileno()
old = termios.tcgetattr(fd)
print("__SMARTBAG_TRANSFER_READY__", flush=True)
try:
    tty.setraw(fd)
    remaining = size
    digest = hashlib.sha256()
    with open(part, "wb") as output:
        while remaining:
            chunk = sys.stdin.buffer.read(min(65536, remaining))
            if not chunk:
                raise EOFError("serial input ended before the declared file size")
            output.write(chunk)
            digest.update(chunk)
            remaining -= len(chunk)
    os.replace(part, path)
finally:
    termios.tcsetattr(fd, termios.TCSANOW, old)
print("__SMARTBAG_TRANSFER_DONE__ " + digest.hexdigest(), flush=True)
"""
    parent = os.path.dirname(remote_file) or "."
    return (
        f"mkdir -p {shlex.quote(parent)} && "
        f"python3 -c {shlex.quote(receiver)} {shlex.quote(remote_file)} {size}"
    )


def sender_command(remote_file: str) -> str:
    sender = """import hashlib
import os
import sys
import termios
import tty

path = sys.argv[1]
size = os.path.getsize(path)
digest = hashlib.sha256()
with open(path, "rb") as source:
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(chunk)
expected = digest.hexdigest()
fd = sys.stdin.fileno()
old = termios.tcgetattr(fd)
print(f"__SMARTBAG_DOWNLOAD_READY__ {size} {expected}", flush=True)
try:
    tty.setraw(fd)
    if sys.stdin.buffer.read(1) != b"G":
        raise RuntimeError("download acknowledgement was not received")
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(16384), b""):
            sys.stdout.buffer.write(chunk)
    sys.stdout.buffer.flush()
finally:
    termios.tcsetattr(fd, termios.TCSANOW, old)
print("__SMARTBAG_DOWNLOAD_DONE__ " + expected, flush=True)
"""
    return f"python3 -c {shlex.quote(sender)} {shlex.quote(remote_file)}"


def open_serial(args: argparse.Namespace) -> Any:
    if serial is None:
        raise RuntimeError(
            "pyserial is required; install it with: py -m pip install pyserial"
        )
    return serial.Serial(
        args.port,
        args.baud,
        timeout=0.2,
        write_timeout=max(10.0, args.timeout_s),
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    )


def prepare_console(port: Any) -> None:
    port.reset_input_buffer()
    port.write(b"\r")
    time.sleep(0.2)
    port.reset_input_buffer()
    port.write(b"stty -echo\r")
    time.sleep(0.3)
    port.reset_input_buffer()


def transfer(args: argparse.Namespace) -> None:
    local_file = args.local_file.resolve(strict=True)
    if not local_file.is_file():
        raise ValueError(f"not a regular file: {local_file}")
    size = local_file.stat().st_size
    expected_digest = sha256_file(local_file)
    command = receiver_command(args.remote_file, size)

    with open_serial(args) as port:
        prepare_console(port)
        # Suppress shell echo so marker text inside the command is not mistaken
        # for the receiver's actual readiness response.
        port.write(command.encode("utf-8") + b"\r")
        read_until(port, b"__SMARTBAG_TRANSFER_READY__\r\n", args.timeout_s)

        sent = 0
        next_report = 10
        with local_file.open("rb") as source:
            while True:
                chunk = source.read(16384)
                if not chunk:
                    break
                port.write(chunk)
                sent += len(chunk)
                percent = int(sent * 100 / max(1, size))
                if percent >= next_report:
                    print(
                        f"sent {sent}/{size} bytes ({percent}%)",
                        file=sys.stderr,
                        flush=True,
                    )
                    next_report += 10

        marker = b"__SMARTBAG_TRANSFER_DONE__ "
        remote_digest = (
            read_marker_line(port, marker, args.timeout_s).decode("ascii").strip()
        )
        port.write(b"stty echo\r")

    if remote_digest.lower() != expected_digest.lower():
        raise RuntimeError(
            f"SHA-256 mismatch: local={expected_digest}, remote={remote_digest}"
        )
    print(
        f"transferred {size} bytes to {args.remote_file}; sha256={expected_digest}",
        flush=True,
    )


def receive(args: argparse.Namespace) -> None:
    local_file = args.local_file.resolve()
    local_file.parent.mkdir(parents=True, exist_ok=True)
    part_file = local_file.with_name(local_file.name + ".part")
    command = sender_command(args.remote_file)

    try:
        with open_serial(args) as port:
            prepare_console(port)
            port.write(command.encode("utf-8") + b"\r")
            marker = b"__SMARTBAG_DOWNLOAD_READY__ "
            fields = read_marker_line(port, marker, args.timeout_s).decode("ascii").split()
            if len(fields) != 2:
                raise RuntimeError(f"malformed download header: {fields!r}")
            size = int(fields[0])
            expected_digest = fields[1].lower()

            port.write(b"G")
            received = 0
            next_report = 10
            digest = hashlib.sha256()
            with part_file.open("wb") as output:
                while received < size:
                    chunk = port.read(min(16384, size - received))
                    if not chunk:
                        continue
                    output.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    percent = int(received * 100 / max(1, size))
                    if percent >= next_report:
                        print(
                            f"received {received}/{size} bytes ({percent}%)",
                            file=sys.stderr,
                            flush=True,
                        )
                        next_report += 10

            done_digest = read_marker_line(
                port, b"__SMARTBAG_DOWNLOAD_DONE__ ", args.timeout_s
            ).decode("ascii").strip().lower()
            port.write(b"stty echo\r")

        actual_digest = digest.hexdigest().lower()
        if actual_digest != expected_digest or done_digest != expected_digest:
            raise RuntimeError(
                "SHA-256 mismatch: "
                f"received={actual_digest}, ready={expected_digest}, done={done_digest}"
            )
        os.replace(part_file, local_file)
        print(
            f"received {size} bytes from {args.remote_file} to {local_file}; "
            f"sha256={actual_digest}",
            flush=True,
        )
    except Exception:
        part_file.unlink(missing_ok=True)
        raise


def main() -> int:
    try:
        args = parse_args()
        if args.receive:
            receive(args)
        else:
            transfer(args)
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print(f"serial transfer failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
