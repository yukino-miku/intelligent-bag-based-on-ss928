#!/usr/bin/env python3
"""Validate JSON, release placeholders, required assets, and tracked file policy."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ACTIVE_RELEASE_PATHS = (
    ROOT / "install-on-ss928.sh",
    ROOT / "validate-on-ss928.sh",
    ROOT / "09_deliverables" / "board_deploy",
)
FORBIDDEN = ("REPLACE_", "LICENSE_BLOCKED", "TODO", "BLOCKED")
REQUIRED = (
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "MODEL_LICENSES.md",
    "AUDIO_LICENSES.md",
    "install-on-ss928.sh",
    "validate-on-ss928.sh",
    "09_deliverables/board_deploy/models/vehicle-detector.om",
    "09_deliverables/board_deploy/models/vehicle-detector.manifest.json",
    "09_deliverables/board_deploy/bin/aarch64/ss928_detection_runner",
    "09_deliverables/board_deploy/bin/aarch64/om_inspect",
    "09_deliverables/board_deploy/bin/aarch64/runner-manifest.json",
)


def tracked(pattern: str | None = None) -> list[str]:
    command = ["git", "ls-files"]
    if pattern:
        command.append(pattern)
    return subprocess.check_output(command, cwd=ROOT, text=True).splitlines()


def main() -> int:
    failures: list[str] = []
    for relative in tracked("*.json"):
        try:
            json.loads((ROOT / relative).read_text(encoding="utf-8"))
        except Exception as exc:
            failures.append(f"invalid JSON {relative}: {exc}")

    for root in ACTIVE_RELEASE_PATHS:
        paths = [root] if root.is_file() else list(root.rglob("*"))
        for path in paths:
            if not path.is_file() or path.suffix.lower() in {".om", ".aac"} or path.name in {
                "ss928_detection_runner", "om_inspect"
            }:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for marker in FORBIDDEN:
                if marker in text:
                    failures.append(f"active release file contains {marker}: {path.relative_to(ROOT)}")

    tracked_files = set(tracked())
    for relative in REQUIRED:
        if relative not in tracked_files:
            failures.append(f"required release file is not tracked: {relative}")
        elif not (ROOT / relative).is_file():
            failures.append(f"required release file is missing: {relative}")

    windows_hits = subprocess.run(
        ["git", "grep", "-n", "C:\\\\Users\\\\a3200", "--", ":(exclude)00_admin/local-deployment-asset-inventory.*"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if windows_hits.returncode == 0:
        failures.append("developer absolute path found:\n" + windows_hits.stdout)

    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Validated {len(tracked('*.json'))} JSON files and {len(REQUIRED)} required release assets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
