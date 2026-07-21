from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from tools.calibration_workflow import calibrate_observations, collect_observations, expand_image_inputs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate SmartBag camera intrinsics with an error report.")
    parser.add_argument("--images", action="append", required=True, help="Directory or glob; repeatable.")
    parser.add_argument("--board-cols", type=int, default=9)
    parser.add_argument("--board-rows", type=int, default=6)
    parser.add_argument("--square-size-m", type=float, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", default="")
    parser.add_argument("--side", choices=("left", "right"), required=True)
    parser.add_argument("--camera-height-m", type=float, default=1.2)
    parser.add_argument("--camera-pitch-deg", type=float, default=5.0)
    parser.add_argument("--yaw-deg", type=float, default=0.0)
    parser.add_argument("--roll-deg", type=float, default=0.0)
    parser.add_argument("--mount-x-m", type=float, default=0.0)
    parser.add_argument("--mount-z-m", type=float, default=0.0)
    parser.add_argument("--distance-scale", type=float, default=1.0)
    parser.add_argument("--rotation-deg", type=int, choices=(0, 90, 180, 270), default=0)
    parser.add_argument("--flip-horizontal", action="store_true")
    parser.add_argument("--flip-vertical", action="store_true")
    parser.add_argument("--calibration-version", default="2")
    parser.add_argument("--mark-extrinsics-calibrated", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mark_extrinsics_calibrated:
        if args.side == "left" and args.mount_x_m >= 0.0:
            raise SystemExit("left calibrated mount_x_m must be negative")
        if args.side == "right" and args.mount_x_m <= 0.0:
            raise SystemExit("right calibrated mount_x_m must be positive")
    paths = expand_image_inputs(args.images)
    observations, rejected = collect_observations(paths, (args.board_cols, args.board_rows))
    result = calibrate_observations(
        observations,
        (args.board_cols, args.board_rows),
        args.square_size_m,
    )
    width, height = result["image_size"]
    payload = {
        "image_width": width,
        "image_height": height,
        "camera_matrix": result["camera_matrix"],
        "dist_coeffs": result["dist_coeffs"],
        "camera_height_m": args.camera_height_m,
        "camera_pitch_deg": args.camera_pitch_deg,
        "distance_scale": args.distance_scale,
        "calibration_version": args.calibration_version,
        "calibration_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "calibration_rms_px": result["rms_px"],
        "mean_reprojection_error_px": result["mean_reprojection_error_px"],
        "max_reprojection_error_px": result["max_reprojection_error_px"],
        "calibration_image_count": len(observations),
        "image_transform": {
            "rotation_deg": args.rotation_deg,
            "flip_horizontal": args.flip_horizontal,
            "flip_vertical": args.flip_vertical,
        },
        "extrinsics": {
            "mount_yaw_deg": args.yaw_deg,
            "mount_roll_deg": args.roll_deg,
            "mount_x_m": args.mount_x_m,
            "mount_z_m": args.mount_z_m,
            "calibrated": bool(args.mark_extrinsics_calibrated),
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path = Path(args.report) if args.report else output.with_suffix(".report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "side": args.side,
                "source_image_count": len(paths),
                "accepted_image_count": len(observations),
                "rejected": rejected,
                "coverage_bin_count": len(result["coverage_signatures"]),
                **result,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {output}; RMS={result['rms_px']:.4f}px "
        f"mean={result['mean_reprojection_error_px']:.4f}px images={len(observations)}"
    )
    if not args.mark_extrinsics_calibrated:
        print("extrinsics remain calibrated=false until physical mounting measurements are verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
