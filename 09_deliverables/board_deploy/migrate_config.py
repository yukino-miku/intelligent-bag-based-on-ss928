#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any


def merge_missing(current: dict[str, Any], defaults: dict[str, Any]) -> bool:
    changed = False
    for key, value in defaults.items():
        if key not in current:
            current[key] = value
            changed = True
        elif isinstance(current[key], dict) and isinstance(value, dict):
            changed = merge_missing(current[key], value) or changed
    return changed


def migrate(config_path: Path, defaults_path: Path) -> bool:
    current = json.loads(config_path.read_text(encoding="utf-8"))
    defaults = json.loads(defaults_path.read_text(encoding="utf-8"))
    if not isinstance(current, dict) or not isinstance(defaults, dict):
        raise ValueError("configuration roots must be JSON objects")
    if not merge_missing(current, defaults):
        return False
    backup = config_path.with_name(f"{config_path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(config_path, backup)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=config_path.name + ".", dir=config_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(current, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, config_path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Add new SmartBag defaults without overwriting local values.")
    parser.add_argument("config", type=Path)
    parser.add_argument("defaults", type=Path)
    args = parser.parse_args()
    changed = migrate(args.config, args.defaults)
    print("configuration migrated" if changed else "configuration already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
