#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_COMMON = SCRIPT_DIR.parents[1] / "06_software" / "board_runtime" / "common"
DEPLOYED_COMMON = Path("/root/smartbag/common")
for candidate in (REPO_COMMON, DEPLOYED_COMMON):
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from config_migration import migrate_config  # noqa: E402
from hardware_profile import validate_hardware_profile  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate smartbag config to a hardware profile")
    parser.add_argument("config", type=Path)
    parser.add_argument(
        "--profile",
        choices=("legacy_pwm_haptics", "rev2_tm6605_mr20"),
        default="legacy_pwm_haptics",
    )
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    source = json.loads(args.config.read_text(encoding="utf-8"))
    migrated, report = migrate_config(source, new_profile=args.profile)
    validate_hardware_profile(migrated["hardware"])
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = args.config.with_name(args.config.name + f".bak.{timestamp}")
    output = report.as_dict()
    output["config"] = str(args.config)
    output["backup"] = None if args.check_only else str(backup)
    if not args.check_only:
        shutil.copy2(args.config, backup)
        args.config.write_text(
            json.dumps(migrated, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

