from __future__ import annotations

import glob
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class CheckerboardObservation:
    path: Path
    image_size: tuple[int, int]
    corners: object
    signature: tuple[int, int, int, int]


def checkerboard_signature(corners, image_size: tuple[int, int]) -> tuple[int, int, int, int]:
    import numpy as np

    points = np.asarray(corners, dtype=np.float64).reshape(-1, 2)
    width, height = image_size
    center = points.mean(axis=0)
    span_x = float(points[:, 0].max() - points[:, 0].min()) / max(width, 1)
    span_y = float(points[:, 1].max() - points[:, 1].min()) / max(height, 1)
    span = math.sqrt(max(span_x * span_y, 0.0))
    direction = points[-1] - points[0]
    angle_deg = math.degrees(math.atan2(float(direction[1]), float(direction[0]))) % 180.0
    return (
        min(4, max(0, int(center[0] / max(width, 1) * 5))),
        min(3, max(0, int(center[1] / max(height, 1) * 4))),
        min(5, max(0, int(span * 10))),
        min(7, max(0, int(angle_deg / 22.5))),
    )


def find_checkerboard(image, board_size: tuple[int, int]):
    import cv2

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if hasattr(cv2, "findChessboardCornersSB"):
        found, corners = cv2.findChessboardCornersSB(
            gray,
            board_size,
            flags=(
                getattr(cv2, "CALIB_CB_EXHAUSTIVE", 0)
                | getattr(cv2, "CALIB_CB_ACCURACY", 0)
            ),
        )
        if found:
            return corners
    found, corners = cv2.findChessboardCorners(
        gray,
        board_size,
        cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE,
    )
    if not found:
        return None
    return cv2.cornerSubPix(
        gray,
        corners,
        (11, 11),
        (-1, -1),
        (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001),
    )


def expand_image_inputs(patterns: Iterable[str]) -> list[Path]:
    paths: set[Path] = set()
    for pattern in patterns:
        candidate = Path(pattern)
        if candidate.is_dir():
            for suffix in ("*.jpg", "*.jpeg", "*.png"):
                paths.update(candidate.glob(suffix))
        else:
            paths.update(Path(value) for value in glob.glob(pattern))
    return sorted(path.resolve() for path in paths if path.is_file())


def collect_observations(
    paths: Iterable[Path],
    board_size: tuple[int, int],
) -> tuple[list[CheckerboardObservation], list[dict[str, str]]]:
    import cv2

    observations: list[CheckerboardObservation] = []
    rejected: list[dict[str, str]] = []
    image_size: tuple[int, int] | None = None
    for path in paths:
        image = cv2.imread(str(path))
        if image is None:
            rejected.append({"path": str(path), "reason": "decode_failed"})
            continue
        current_size = (int(image.shape[1]), int(image.shape[0]))
        if image_size is not None and current_size != image_size:
            rejected.append({"path": str(path), "reason": "mixed_resolution"})
            continue
        corners = find_checkerboard(image, board_size)
        if corners is None:
            rejected.append({"path": str(path), "reason": "checkerboard_not_found"})
            continue
        image_size = current_size
        observations.append(
            CheckerboardObservation(
                path=path,
                image_size=current_size,
                corners=corners,
                signature=checkerboard_signature(corners, current_size),
            )
        )
    return observations, rejected


def calibrate_observations(
    observations: list[CheckerboardObservation],
    board_size: tuple[int, int],
    square_size_m: float,
) -> dict[str, object]:
    import cv2
    import numpy as np

    if len(observations) < 8:
        raise ValueError(f"at least 8 usable checkerboard images are required; got {len(observations)}")
    object_template = np.zeros((board_size[0] * board_size[1], 3), dtype=np.float32)
    object_template[:, :2] = np.mgrid[0 : board_size[0], 0 : board_size[1]].T.reshape(-1, 2)
    object_template *= float(square_size_m)
    object_points = [object_template.copy() for _observation in observations]
    image_points = [observation.corners for observation in observations]
    rms, matrix, distortion, rvecs, tvecs = cv2.calibrateCamera(
        object_points,
        image_points,
        observations[0].image_size,
        None,
        None,
    )
    per_image_errors: list[dict[str, object]] = []
    for observation, object_point, image_point, rvec, tvec in zip(
        observations,
        object_points,
        image_points,
        rvecs,
        tvecs,
    ):
        projected, _jacobian = cv2.projectPoints(object_point, rvec, tvec, matrix, distortion)
        error = cv2.norm(image_point, projected, cv2.NORM_L2) / max(len(projected), 1) ** 0.5
        per_image_errors.append({"path": str(observation.path), "reprojection_error_px": float(error)})
    errors = [float(row["reprojection_error_px"]) for row in per_image_errors]
    return {
        "image_size": observations[0].image_size,
        "camera_matrix": matrix.tolist(),
        "dist_coeffs": distortion.reshape(-1).tolist(),
        "rms_px": float(rms),
        "mean_reprojection_error_px": float(sum(errors) / len(errors)),
        "max_reprojection_error_px": float(max(errors)),
        "per_image_errors": per_image_errors,
        "coverage_signatures": sorted({observation.signature for observation in observations}),
    }
