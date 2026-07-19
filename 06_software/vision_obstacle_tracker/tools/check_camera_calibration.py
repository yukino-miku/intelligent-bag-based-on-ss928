from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REQUIRED_ROOT_FIELDS = (
    "camera_matrix",
    "dist_coeffs",
    "image_width",
    "image_height",
    "camera_height_m",
    "camera_pitch_deg",
    "distance_scale",
    "calibration_version",
)
REQUIRED_EXTRINSIC_FIELDS = (
    "mount_yaw_deg",
    "mount_roll_deg",
    "mount_x_m",
    "mount_z_m",
    "calibrated",
)


def validate_calibration(
    data: dict[str, object],
    *,
    side: str,
    production: bool,
) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_ROOT_FIELDS:
        if field not in data:
            errors.append(f"missing root field: {field}")
    matrix = data.get("camera_matrix")
    if not (
        isinstance(matrix, list)
        and len(matrix) == 3
        and all(isinstance(row, list) and len(row) == 3 for row in matrix)
    ):
        errors.append("camera_matrix must be a 3x3 array")
    if not isinstance(data.get("dist_coeffs"), list):
        errors.append("dist_coeffs must be an array")
    for field in ("image_width", "image_height"):
        try:
            if int(data.get(field, 0)) <= 0:
                errors.append(f"{field} must be positive")
        except (TypeError, ValueError):
            errors.append(f"{field} must be an integer")

    extrinsics = data.get("extrinsics")
    if not isinstance(extrinsics, dict):
        errors.append("extrinsics must be an object")
        extrinsics = {}
    for field in REQUIRED_EXTRINSIC_FIELDS:
        if field not in extrinsics:
            errors.append(f"missing extrinsics field: {field}")
    try:
        mount_x_m = float(extrinsics.get("mount_x_m", 0.0))
        if side == "left" and mount_x_m >= 0.0:
            errors.append("left mount_x_m must be negative")
        if side == "right" and mount_x_m <= 0.0:
            errors.append("right mount_x_m must be positive")
    except (TypeError, ValueError):
        errors.append("mount_x_m must be numeric")
    if production and not bool(extrinsics.get("calibrated", False)):
        errors.append("production mode requires extrinsics.calibrated=true")
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate SmartBag camera intrinsics/extrinsics JSON.")
    parser.add_argument("calibration_file")
    parser.add_argument("--side", choices=("left", "right"), required=True)
    parser.add_argument("--mode", choices=("diagnostic", "production"), default="diagnostic")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    path = Path(args.calibration_file)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL {path}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print(f"FAIL {path}: root must be an object", file=sys.stderr)
        return 1
    errors = validate_calibration(data, side=args.side, production=args.mode == "production")
    if errors:
        for error in errors:
            print(f"FAIL {path}: {error}", file=sys.stderr)
        return 1
    print(f"OK {args.side} calibration: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
