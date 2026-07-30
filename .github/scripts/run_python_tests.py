#!/usr/bin/env python3
"""Run every unittest suite from the import root expected by that module."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEST_ROOTS = (
    ROOT / "06_software" / "vision_obstacle_tracker",
    ROOT / "06_software" / "usb_camera_recorder",
    ROOT / "06_software" / "board_runtime" / "bmi270_backpack",
    ROOT / "06_software" / "board_runtime" / "cloud_uploader",
    ROOT / "06_software" / "board_runtime" / "dx_gp21_tracker",
    ROOT / "06_software" / "board_runtime" / "imu_fall_detector",
    ROOT / "06_software" / "board_runtime" / "mr20_radar",
    ROOT / "06_software" / "board_runtime" / "mt5710_connectivity",
    ROOT / "06_software" / "board_runtime" / "radar_vision_fusion",
    ROOT / "06_software" / "board_runtime" / "smartbag_alert_controller",
    ROOT / "06_software" / "board_runtime" / "temperature",
)


def main() -> int:
    for root in TEST_ROOTS:
        if not (root / "tests").is_dir():
            raise SystemExit(f"missing test directory: {root / 'tests'}")
        print(f"\n== unittest: {root.relative_to(ROOT)} ==", flush=True)
        subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test*.py", "-v"],
            cwd=root,
            check=True,
        )
    print("\n== unittest: 07_tests/integration ==", flush=True)
    subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "07_tests/integration", "-p", "test*.py", "-v"],
        cwd=ROOT,
        check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
