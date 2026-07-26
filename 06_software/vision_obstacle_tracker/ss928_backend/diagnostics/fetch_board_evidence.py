#!/usr/bin/env python3
"""Fetch the fixed Stage G evidence without embedding board credentials here."""

import argparse
import importlib.util
from pathlib import Path


REMOTE_DIR = "/root/ss928_yolov8_vot_diag"
FILES = [
    "model_desc_full.json",
    "model_desc_full.txt",
    "reference_runner.log",
    "current_runner.log",
    "reference.output0.bin",
    "current.output0.bin",
    "comparison.json",
    "comparison.txt",
    "postprocess_audit.json",
    "postprocess_audit.txt",
]


def load_board_debug(repo_root):
    path = repo_root / "06_software" / "tools" / "board_debug" / "board_debug.py"
    spec = importlib.util.spec_from_file_location("ss928_board_debug", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default=REMOTE_DIR)
    args = parser.parse_args()
    diagnostics = Path(__file__).resolve().parent
    repo_root = diagnostics.parents[3]
    destination = diagnostics / "artifacts"
    destination.mkdir(parents=True, exist_ok=True)
    board_debug = load_board_debug(repo_root)
    connection_args = argparse.Namespace(
        host=board_debug.DEFAULT_HOST,
        user=board_debug.DEFAULT_USER,
        password="",
    )
    client = board_debug.connect(connection_args)
    try:
        sftp = client.open_sftp()
        try:
            for name in FILES:
                remote_path = f"{args.remote}/{name}"
                local_path = destination / name
                sftp.get(remote_path, str(local_path))
                print(f"fetched {remote_path} -> {local_path}")
        finally:
            sftp.close()
    finally:
        client.close()


if __name__ == "__main__":
    main()
