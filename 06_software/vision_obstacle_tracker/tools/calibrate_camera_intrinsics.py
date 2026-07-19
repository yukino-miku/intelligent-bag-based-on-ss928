from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate one camera from checkerboard JPEG images.")
    parser.add_argument("--images", required=True, help="Glob such as calibration/left/*.jpg")
    parser.add_argument("--board-cols", type=int, default=9, help="Inner checkerboard corners per row")
    parser.add_argument("--board-rows", type=int, default=6, help="Inner checkerboard corners per column")
    parser.add_argument("--square-size-m", type=float, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--yaw-deg", type=float, default=0.0)
    parser.add_argument("--roll-deg", type=float, default=0.0)
    parser.add_argument("--mount-x-m", type=float, required=True)
    parser.add_argument("--mount-z-m", type=float, default=0.0)
    parser.add_argument("--camera-height-m", type=float, required=True)
    parser.add_argument("--camera-pitch-deg", type=float, required=True)
    parser.add_argument("--distance-scale", type=float, default=1.0)
    parser.add_argument("--calibration-version", default="1")
    return parser.parse_args()


def main() -> int:
    import cv2
    import numpy as np

    args = parse_args()
    image_paths = [Path(path) for path in sorted(glob.glob(args.images))]
    if len(image_paths) < 8:
        raise SystemExit("at least 8 checkerboard images are required")
    pattern = (args.board_cols, args.board_rows)
    object_template = np.zeros((args.board_cols * args.board_rows, 3), dtype=np.float32)
    object_template[:, :2] = np.mgrid[0 : args.board_cols, 0 : args.board_rows].T.reshape(-1, 2)
    object_template *= args.square_size_m
    object_points = []
    image_points = []
    image_size = None
    accepted = []
    criteria = (
        cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
        30,
        0.001,
    )
    for path in image_paths:
        image = cv2.imread(str(path))
        if image is None:
            continue
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if image_size is not None and image_size != gray.shape[::-1]:
            raise SystemExit(f"mixed image dimensions: {path}")
        image_size = gray.shape[::-1]
        found, corners = cv2.findChessboardCorners(gray, pattern)
        if not found:
            continue
        refined = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        object_points.append(object_template.copy())
        image_points.append(refined)
        accepted.append(str(path))
    if image_size is None or len(image_points) < 8:
        raise SystemExit(f"only {len(image_points)} usable checkerboard images; need at least 8")
    rms, matrix, distortion, _rvecs, _tvecs = cv2.calibrateCamera(
        object_points,
        image_points,
        image_size,
        None,
        None,
    )
    payload = {
        "image_width": image_size[0],
        "image_height": image_size[1],
        "camera_matrix": matrix.tolist(),
        "dist_coeffs": distortion.reshape(-1).tolist(),
        "camera_height_m": args.camera_height_m,
        "camera_pitch_deg": args.camera_pitch_deg,
        "distance_scale": args.distance_scale,
        "calibration_version": args.calibration_version,
        "calibration_rms_px": float(rms),
        "calibration_image_count": len(accepted),
        "extrinsics": {
            "mount_yaw_deg": args.yaw_deg,
            "mount_roll_deg": args.roll_deg,
            "mount_x_m": args.mount_x_m,
            "mount_z_m": args.mount_z_m,
            "calibrated": False,
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output}; RMS={rms:.4f}px images={len(accepted)}")
    print("Measure mounting yaw/roll/translation, then set extrinsics.calibrated=true.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
