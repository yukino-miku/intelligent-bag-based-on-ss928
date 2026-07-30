from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any


def load_observations(path: Path, side: str, image_width: int) -> list[dict[str, float]]:
    records: list[dict[str, float]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("type") != "fusion_calibration_observation" or item.get("side") != side:
            continue
        if int(item.get("image_width", image_width)) != image_width:
            raise ValueError(f"observation line {line_number} uses a different image width")
        records.append({key: float(item[key]) for key in ("radar_x_m", "radar_z_m", "pixel_u")})
    if len(records) < 4:
        raise ValueError("at least four same-side observations are required")
    return records


def linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denominator = sum((value - x_mean) ** 2 for value in xs)
    if denominator <= 1e-12:
        return None
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator
    return slope, y_mean - slope * x_mean


def fit_horizontal_projection(
    observations: list[dict[str, float]],
    camera_mount_x_m: float,
    camera_mount_z_m: float,
    yaw_min_deg: float = -60.0,
    yaw_max_deg: float = 60.0,
    yaw_step_deg: float = 0.05,
) -> dict[str, float]:
    best: dict[str, float] | None = None
    steps = int(round((yaw_max_deg - yaw_min_deg) / yaw_step_deg))
    for index in range(steps + 1):
        yaw_deg = yaw_min_deg + index * yaw_step_deg
        angle = math.radians(-yaw_deg)
        cosine, sine = math.cos(angle), math.sin(angle)
        ratios: list[float] = []
        pixels: list[float] = []
        valid = True
        for item in observations:
            x = item["radar_x_m"] - camera_mount_x_m
            z = item["radar_z_m"] - camera_mount_z_m
            camera_x = cosine * x + sine * z
            camera_z = -sine * x + cosine * z
            if camera_z <= 0.1:
                valid = False
                break
            ratios.append(camera_x / camera_z)
            pixels.append(item["pixel_u"])
        if not valid:
            continue
        fit = linear_fit(ratios, pixels)
        if fit is None or fit[0] <= 0.0:
            continue
        fx, cx = fit
        errors = [fx * ratio + cx - pixel for ratio, pixel in zip(ratios, pixels)]
        rmse = math.sqrt(sum(value * value for value in errors) / len(errors))
        candidate = {
            "camera_yaw_deg": yaw_deg,
            "camera_fx": fx,
            "camera_cx": cx,
            "horizontal_rmse_px": rmse,
            "max_error_px": max(abs(value) for value in errors),
        }
        if best is None or rmse < best["horizontal_rmse_px"]:
            best = candidate
    if best is None:
        raise ValueError("could not fit a forward-facing horizontal projection")
    return best


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fit horizontal radar-camera projection from known target observations.")
    parser.add_argument("--side", choices=("left", "right"), required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image-width", type=int, required=True)
    parser.add_argument("--image-height", type=int, required=True)
    parser.add_argument("--camera-height", type=float, required=True)
    parser.add_argument("--radar-height", type=float, required=True)
    parser.add_argument("--camera-x", type=float, required=True)
    parser.add_argument("--radar-x", type=float, required=True)
    parser.add_argument("--camera-pitch", type=float, required=True)
    args = parser.parse_args()

    data = json.loads(args.base.read_text(encoding="utf-8"))
    observations = load_observations(args.observations, args.side, args.image_width)
    fit = fit_horizontal_projection(observations, args.camera_x, float(data.get("camera_mount_z_m", 0.0)))
    data.update(
        {
            "side": args.side,
            "calibration_status": "MEASURED_SIMPLIFIED_PROJECTION",
            "camera_mount_x_m": args.camera_x,
            "camera_mount_y_m": args.camera_height,
            "camera_pitch_deg": args.camera_pitch,
            "camera_yaw_deg": fit["camera_yaw_deg"],
            "radar_mount_x_m": args.radar_x,
            "radar_mount_y_m": args.radar_height,
            "camera_intrinsics": {
                **data.get("camera_intrinsics", {}),
                "fx": fit["camera_fx"],
                "cx": fit["camera_cx"],
                "cy": args.image_height * 0.5,
            },
            "fit_evidence": {
                "observation_count": len(observations),
                "image_width": args.image_width,
                "image_height": args.image_height,
                "horizontal_rmse_px": fit["horizontal_rmse_px"],
                "max_error_px": fit["max_error_px"],
                "observations_file": args.observations.name,
            },
        }
    )
    atomic_json(args.output, data)
    print(json.dumps({"output": str(args.output), **fit}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
