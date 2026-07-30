#!/usr/bin/env python3
"""Verify packaged SS928 runner and optional vehicle model before installation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys


EM_AARCH64 = 183


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_elf_aarch64(path: Path) -> None:
    header = path.read_bytes()[:64]
    if len(header) < 20 or header[:4] != b"\x7fELF":
        raise ValueError(f"not an ELF executable: {path}")
    if header[4] != 2 or header[5] != 1:
        raise ValueError(f"runner must be 64-bit little-endian ELF: {path}")
    machine = struct.unpack_from("<H", header, 18)[0]
    if machine != EM_AARCH64:
        raise ValueError(f"runner architecture mismatch: e_machine={machine}, expected AArch64/{EM_AARCH64}")


def verify_runner(path: Path, manifest_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = str(manifest["runner"]["sha256"]).lower()
    if not path.is_file():
        raise FileNotFoundError(f"runner missing: {path}")
    verify_elf_aarch64(path)
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f"runner SHA256 mismatch: expected={expected} actual={actual}")
    return {"runner": str(path), "sha256": actual, "architecture": "AArch64", "valid": True}


def verify_model(path: Path, manifest_path: Path, require_compatible: bool) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not path.is_file():
        raise FileNotFoundError(f"model missing: {path}")
    expected = str(manifest.get("sha256", "")).lower()
    actual = sha256(path)
    if not expected or actual != expected:
        raise ValueError(f"model SHA256 mismatch: expected={expected or 'missing'} actual={actual}")
    if require_compatible and manifest.get("runner_compatible") is not True:
        raise ValueError(
            "model manifest blocks full deployment: static runner/model contract is not compatible"
        )
    if manifest.get("output_shape") != [1, 84, 8400]:
        raise ValueError("model output contract must be [1,84,8400]")
    if manifest.get("class_table") != "COCO80":
        raise ValueError("model class table must be COCO80")
    return {
        "model": str(path),
        "sha256": actual,
        "runner_compatible": bool(manifest.get("runner_compatible")),
        "valid": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", type=Path)
    parser.add_argument("--runner-manifest", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--model-manifest", type=Path)
    parser.add_argument("--allow-unvalidated-model", action="store_true")
    args = parser.parse_args()
    results: dict[str, object] = {}
    try:
        if args.runner or args.runner_manifest:
            if not args.runner or not args.runner_manifest:
                parser.error("--runner and --runner-manifest must be used together")
            results["runner"] = verify_runner(args.runner, args.runner_manifest)
        if args.model or args.model_manifest:
            if not args.model or not args.model_manifest:
                parser.error("--model and --model-manifest must be used together")
            results["model"] = verify_model(
                args.model,
                args.model_manifest,
                require_compatible=not args.allow_unvalidated_model,
            )
        if not results:
            parser.error("at least one asset must be selected")
        if "runner" in results and "model" in results:
            model_manifest = json.loads(args.model_manifest.read_text(encoding="utf-8"))
            runner_manifest = json.loads(args.runner_manifest.read_text(encoding="utf-8"))
            if model_manifest.get("runner_sha256") != results["runner"]["sha256"]:
                raise ValueError("model manifest runner_sha256 does not match packaged runner")
            if model_manifest.get("runner_contract_version") != runner_manifest["runner"].get("contract_version"):
                raise ValueError("model and runner contract versions do not match")
    except (FileNotFoundError, KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    print(json.dumps(results, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
