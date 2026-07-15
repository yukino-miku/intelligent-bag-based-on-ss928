#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import posixpath
from pathlib import Path

import paramiko


DEFAULT_HOST = os.environ.get("SS928_BOARD_HOST", "ss928")
DEFAULT_USER = os.environ.get("SS928_BOARD_USER", "root")
DEFAULT_REMOTE_ROOT = "/root/smartbag"
SKIP_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "dist_onefile",
    "third_party",
    "08_media",
    "10_archive",
}
SKIP_SUFFIXES = {".avi", ".mp4", ".om", ".onnx", ".pt", ".pyc"}


def connect(args: argparse.Namespace) -> paramiko.SSHClient:
    password = args.password or os.environ.get("SS928_BOARD_PASSWORD", "")
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    connect_kwargs = {
        "hostname": args.host,
        "username": args.user,
        "timeout": 10,
        "banner_timeout": 10,
        "auth_timeout": 10,
    }
    if password:
        connect_kwargs["password"] = password
    client.connect(**connect_kwargs)
    return client


def run(client: paramiko.SSHClient, command: str, timeout: int = 30) -> int:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    print(f"$ {command}\n[rc={rc}]")
    if out.strip():
        print(out.rstrip())
    if err.strip():
        print("[stderr]")
        print(err.rstrip())
    return rc


def ensure_remote_dir(sftp: paramiko.SFTPClient, path: str) -> None:
    current = ""
    for part in [item for item in path.split("/") if item]:
        current += "/" + part
        try:
            sftp.stat(current)
        except OSError:
            sftp.mkdir(current)


def upload_folder(client: paramiko.SSHClient, local_dir: Path, remote_dir: str) -> None:
    local_dir = local_dir.resolve()
    if not local_dir.is_dir():
        raise SystemExit(f"Local folder not found: {local_dir}")
    sftp = client.open_sftp()
    try:
        ensure_remote_dir(sftp, remote_dir)
        for path in sorted(local_dir.rglob("*")):
            relative = path.relative_to(local_dir)
            if any(part in SKIP_NAMES for part in relative.parts):
                continue
            if path.is_file() and (path.suffix.lower() in SKIP_SUFFIXES or path.name.startswith("risk_log")):
                continue
            remote_path = posixpath.join(remote_dir, *relative.parts)
            if path.is_dir():
                ensure_remote_dir(sftp, remote_path)
                continue
            ensure_remote_dir(sftp, posixpath.dirname(remote_path))
            sftp.put(str(path), remote_path)
            if path.suffix == ".sh":
                sftp.chmod(remote_path, 0o755)
    finally:
        sftp.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SS928 SmartBag SSH/SFTP debug helper")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default="", help="Prefer SS928_BOARD_PASSWORD instead of command history")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("probe")
    upload = sub.add_parser("upload")
    upload.add_argument("--local", required=True)
    upload.add_argument("--remote", default=DEFAULT_REMOTE_ROOT)
    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("command")
    run_cmd.add_argument("--timeout", type=int, default=30)
    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("status")
    logs = sub.add_parser("logs")
    logs.add_argument("--lines", type=int, default=100)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    client = connect(args)
    try:
        if args.action == "probe":
            return run(client, "hostname; uname -a; python3 --version; ls -l /dev/video* /dev/i2c-* /dev/ttyAMA4 2>/dev/null || true")
        if args.action == "upload":
            upload_folder(client, Path(args.local), args.remote)
            return run(client, f"find {args.remote} -maxdepth 3 -type f | sort | sed -n '1,160p'")
        if args.action == "run":
            return run(client, args.command, timeout=args.timeout)
        if args.action == "start":
            return run(client, "systemctl start smartbag.target && systemctl --no-pager --full status smartbag.target")
        if args.action == "stop":
            return run(client, "systemctl stop smartbag.target")
        if args.action == "status":
            return run(client, "systemctl --no-pager --full status smartbag.target smartbag-vision smartbag-alert smartbag-gnss smartbag-imu")
        if args.action == "logs":
            return run(client, f"journalctl -u 'smartbag-*' -n {args.lines} --no-pager")
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
