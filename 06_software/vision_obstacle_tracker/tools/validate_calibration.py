from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from tools.check_camera_calibration import validate_calibration


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate production SmartBag calibration and report quality.")
    parser.add_argument("calibration_file")
    parser.add_argument("--side", choices=("left", "right"), required=True)
    parser.add_argument("--mode", choices=("diagnostic", "production"), default="production")
    parser.add_argument("--expected-width", type=int)
    parser.add_argument("--expected-height", type=int)
    parser.add_argument("--expected-rotation-deg", type=int, choices=(0, 90, 180, 270))
    parser.add_argument("--max-rms-px", type=float, default=1.5)
    return parser.parse_args(argv)


def validation_errors(data: dict[str, object], args: argparse.Namespace) -> list[str]:
    errors = validate_calibration(data, side=args.side, production=args.mode == "production")
    if args.expected_width is not None and int(data.get("image_width", 0)) != args.expected_width:
        errors.append("image_width does not match runtime processed width")
    if args.expected_height is not None and int(data.get("image_height", 0)) != args.expected_height:
        errors.append("image_height does not match runtime processed height")
    if args.expected_rotation_deg is not None:
        transform = data.get("image_transform")
        actual_rotation = transform.get("rotation_deg") if isinstance(transform, dict) else None
        if actual_rotation != args.expected_rotation_deg:
            errors.append("image_transform.rotation_deg does not match runtime")
    try:
        if float(data.get("calibration_rms_px", float("inf"))) > args.max_rms_px:
            errors.append(f"calibration_rms_px exceeds {args.max_rms_px}")
    except (TypeError, ValueError):
        errors.append("calibration_rms_px must be numeric")
    return errors


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    path = Path(args.calibration_file)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL {path}: {exc}", file=sys.stderr)
        return 1
    errors = validation_errors(data, args)
    if errors:
        for error in errors:
            print(f"FAIL {path}: {error}", file=sys.stderr)
        return 1
    print(
        f"OK {args.side}: {path} resolution={data['image_width']}x{data['image_height']} "
        f"RMS={float(data['calibration_rms_px']):.4f}px"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
