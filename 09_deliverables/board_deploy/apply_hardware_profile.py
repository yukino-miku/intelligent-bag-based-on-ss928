#!/usr/bin/env python3
"""Apply a JSON hardware-profile patch without replacing unrelated config."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def merge_patch(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(target)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_patch(result[key], value)
        else:
            result[key] = value
    return result


def apply_profile(config_path: Path, profile_path: Path) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(profile, dict):
        raise ValueError("config and profile must be JSON objects")
    patch = profile.get("config_patch")
    if not isinstance(patch, dict):
        raise ValueError("hardware profile requires a config_patch object")
    merged = merge_patch(config, patch)
    temporary = config_path.with_name(config_path.name + ".tmp")
    temporary.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(config_path)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("profile", type=Path)
    args = parser.parse_args()
    apply_profile(args.config, args.profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
