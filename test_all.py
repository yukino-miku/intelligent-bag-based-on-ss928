from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent
TEST_ROOTS = (
    ROOT / "06_software" / "vision_obstacle_tracker" / "tests",
    ROOT / "06_software" / "board_runtime" / "smartbag_alert_controller" / "tests",
    ROOT / "06_software" / "board_runtime" / "dx_gp21_tracker" / "tests",
    ROOT / "06_software" / "board_runtime" / "bmi270_backpack" / "tests",
    ROOT / "06_software" / "board_runtime" / "imu_fall_detector" / "tests",
    ROOT / "07_tests" / "integration",
)


def load_tests(loader: unittest.TestLoader, _tests: unittest.TestSuite, pattern: str | None):
    suite = unittest.TestSuite()
    for test_root in TEST_ROOTS:
        if test_root.is_dir():
            module_root = str(test_root.parent)
            if module_root not in sys.path:
                sys.path.insert(0, module_root)
            suite.addTests(
                unittest.TestLoader().discover(
                    str(test_root),
                    pattern=pattern or "test*.py",
                    top_level_dir=str(test_root),
                )
            )
    return suite
