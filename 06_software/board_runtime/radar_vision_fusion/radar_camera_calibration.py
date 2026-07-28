from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

try:
    from .models import ProjectedRadarTarget
    from .radar_tracks import RadarTrack
except ImportError:
    from models import ProjectedRadarTarget
    from radar_tracks import RadarTrack


@dataclass(frozen=True)
class FusionCalibration:
    side: str
    camera_fx: float | None = None
    camera_fy: float | None = None
    camera_cx: float | None = None
    camera_cy: float | None = None
    camera_distortion: tuple[float, float, float, float, float] = (0.0, 0.0, 0.0, 0.0, 0.0)
    camera_rotation_deg: int = 0
    camera_flip_horizontal: bool = False
    camera_flip_vertical: bool = False
    camera_horizontal_fov_deg: float = 90.0
    camera_mount_x_m: float = 0.0
    camera_mount_y_m: float = 1.2
    camera_mount_z_m: float = 0.0
    camera_yaw_deg: float = 0.0
    camera_pitch_deg: float = 0.0
    camera_roll_deg: float = 0.0
    radar_mount_x_m: float = 0.0
    radar_mount_y_m: float = 0.0
    radar_mount_z_m: float = 0.0
    radar_yaw_deg: float = 0.0
    radar_to_camera_rotation: tuple[tuple[float, float, float], ...] | None = None
    radar_to_camera_translation: tuple[float, float, float] | None = None
    nominal_target_height_m: float = 0.8

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> "FusionCalibration":
        intrinsics = data.get("camera_intrinsics", {})
        intrinsics = intrinsics if isinstance(intrinsics, Mapping) else {}
        distortion = data.get("camera_distortion", (0.0,) * 5)
        if not isinstance(distortion, Sequence) or isinstance(distortion, (str, bytes)):
            distortion = (0.0,) * 5
        distortion_values = tuple(float(value) for value in distortion)
        distortion_values = (distortion_values + (0.0,) * 5)[:5]
        rotation = _matrix3(data.get("radar_to_camera_rotation"))
        translation = _vector3(data.get("radar_to_camera_translation"))
        return cls(
            side=str(data.get("side", "")),
            camera_fx=_optional_float(intrinsics.get("fx")),
            camera_fy=_optional_float(intrinsics.get("fy")),
            camera_cx=_optional_float(intrinsics.get("cx")),
            camera_cy=_optional_float(intrinsics.get("cy")),
            camera_distortion=distortion_values,
            camera_rotation_deg=int(data.get("camera_rotation_deg", 0)),
            camera_flip_horizontal=bool(data.get("camera_flip_horizontal", data.get("camera_flip", False))),
            camera_flip_vertical=bool(data.get("camera_flip_vertical", False)),
            camera_horizontal_fov_deg=float(data.get("camera_horizontal_fov_deg", 90.0)),
            camera_mount_x_m=float(data.get("camera_mount_x_m", 0.0)),
            camera_mount_y_m=float(data.get("camera_mount_y_m", 1.2)),
            camera_mount_z_m=float(data.get("camera_mount_z_m", 0.0)),
            camera_yaw_deg=float(data.get("camera_yaw_deg", 0.0)),
            camera_pitch_deg=float(data.get("camera_pitch_deg", 0.0)),
            camera_roll_deg=float(data.get("camera_roll_deg", 0.0)),
            radar_mount_x_m=float(data.get("radar_mount_x_m", 0.0)),
            radar_mount_y_m=float(data.get("radar_mount_y_m", 0.0)),
            radar_mount_z_m=float(data.get("radar_mount_z_m", 0.0)),
            radar_yaw_deg=float(data.get("radar_yaw_deg", 0.0)),
            radar_to_camera_rotation=rotation,
            radar_to_camera_translation=translation,
            nominal_target_height_m=float(data.get("nominal_target_height_m", 0.8)),
        )

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.side not in {"left", "right"}:
            errors.append("side must be left or right")
        if not 10.0 <= self.camera_horizontal_fov_deg < 180.0:
            errors.append("camera_horizontal_fov_deg must be in [10, 180)")
        if self.camera_fx is not None and self.camera_fx <= 0.0:
            errors.append("camera_intrinsics.fx must be positive")
        if self.camera_fy is not None and self.camera_fy <= 0.0:
            errors.append("camera_intrinsics.fy must be positive")
        if self.camera_rotation_deg % 90 != 0:
            errors.append("camera_rotation_deg must be a multiple of 90")
        return tuple(errors)


def load_fusion_calibration(path: str | Path) -> FusionCalibration:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("fusion calibration must be a JSON object")
    calibration = FusionCalibration.from_mapping(data)
    errors = calibration.validate()
    if errors:
        raise ValueError("; ".join(errors))
    return calibration


def project_radar_track(
    track: RadarTrack,
    calibration: FusionCalibration,
    camera_timestamp_s: float,
    image_width: int,
    image_height: int,
) -> ProjectedRadarTarget:
    nearest_position = min(
        track.position_history,
        key=lambda item: abs(camera_timestamp_s - item[0]),
        default=(track.last_seen_mono_s, track.x_m, track.z_m),
    )
    nearest_velocity = min(
        track.velocity_history,
        key=lambda item: abs(camera_timestamp_s - item[0]),
        default=(track.last_seen_mono_s, track.vx_mps, track.vz_mps),
    )
    dt_s = camera_timestamp_s - nearest_position[0]
    x_m = nearest_position[1] + nearest_velocity[1] * dt_s
    z_m = nearest_position[2] + nearest_velocity[2] * dt_s
    radar_bearing_deg = math.degrees(math.atan2(x_m, z_m))
    camera_x, camera_y, camera_z = _bag_to_camera(x_m, calibration.nominal_target_height_m, z_m, calibration)
    if camera_z <= 1e-5:
        return ProjectedRadarTarget(
            track.track_key, track.side, None, None, False, radar_bearing_deg, None,
            x_m, z_m, dt_s,
        )

    fx = calibration.camera_fx
    if fx is None:
        fx = image_width / (2.0 * math.tan(math.radians(calibration.camera_horizontal_fov_deg) * 0.5))
    fy = calibration.camera_fy if calibration.camera_fy is not None else fx
    cx = calibration.camera_cx if calibration.camera_cx is not None else image_width * 0.5
    cy = calibration.camera_cy if calibration.camera_cy is not None else image_height * 0.5
    normalized_x = camera_x / camera_z
    normalized_y = camera_y / camera_z
    distorted_x, distorted_y = _distort(normalized_x, normalized_y, calibration.camera_distortion)
    u_px = fx * distorted_x + cx
    v_px = cy - fy * distorted_y
    u_px, v_px = _apply_image_transform(u_px, v_px, image_width, image_height, calibration)
    # MR20 has no reliable target height, so vertical projection is diagnostic only.
    in_frame = 0.0 <= u_px < image_width
    return ProjectedRadarTarget(
        track_key=track.track_key,
        side=track.side,
        projected_u_px=u_px,
        projected_v_px=v_px,
        projected_in_frame=in_frame,
        radar_bearing_deg=radar_bearing_deg,
        camera_bearing_deg=math.degrees(math.atan2(camera_x, camera_z)),
        x_at_camera_time_m=x_m,
        z_at_camera_time_m=z_m,
        time_delta_s=dt_s,
    )


def _bag_to_camera(x_m: float, y_m: float, z_m: float, calibration: FusionCalibration) -> tuple[float, float, float]:
    if calibration.radar_to_camera_rotation is not None:
        rotated = _matrix_vector(calibration.radar_to_camera_rotation, (x_m, y_m, z_m))
        if calibration.radar_to_camera_translation is None:
            return rotated
        return tuple(
            rotated[index] + calibration.radar_to_camera_translation[index]
            for index in range(3)
        )  # type: ignore[return-value]

    point = (
        x_m - calibration.camera_mount_x_m,
        y_m - calibration.camera_mount_y_m,
        z_m - calibration.camera_mount_z_m,
    )
    yaw = math.radians(-calibration.camera_yaw_deg)
    pitch = math.radians(-calibration.camera_pitch_deg)
    roll = math.radians(-calibration.camera_roll_deg)
    result = _rotate_y(point, yaw)
    result = _rotate_x(result, pitch)
    return _rotate_z(result, roll)


def _distort(x: float, y: float, coefficients: tuple[float, float, float, float, float]) -> tuple[float, float]:
    k1, k2, p1, p2, k3 = coefficients
    radius_sq = x * x + y * y
    radial = 1.0 + k1 * radius_sq + k2 * radius_sq * radius_sq + k3 * radius_sq * radius_sq * radius_sq
    return (
        x * radial + 2.0 * p1 * x * y + p2 * (radius_sq + 2.0 * x * x),
        y * radial + p1 * (radius_sq + 2.0 * y * y) + 2.0 * p2 * x * y,
    )


def _apply_image_transform(
    u_px: float,
    v_px: float,
    width: int,
    height: int,
    calibration: FusionCalibration,
) -> tuple[float, float]:
    rotation = calibration.camera_rotation_deg % 360
    if rotation == 90:
        u_px, v_px = height - 1.0 - v_px, u_px
    elif rotation == 180:
        u_px, v_px = width - 1.0 - u_px, height - 1.0 - v_px
    elif rotation == 270:
        u_px, v_px = v_px, width - 1.0 - u_px
    if calibration.camera_flip_horizontal:
        u_px = width - 1.0 - u_px
    if calibration.camera_flip_vertical:
        v_px = height - 1.0 - v_px
    return u_px, v_px


def _rotate_x(point: tuple[float, float, float], angle: float) -> tuple[float, float, float]:
    x, y, z = point
    cosine, sine = math.cos(angle), math.sin(angle)
    return x, cosine * y - sine * z, sine * y + cosine * z


def _rotate_y(point: tuple[float, float, float], angle: float) -> tuple[float, float, float]:
    x, y, z = point
    cosine, sine = math.cos(angle), math.sin(angle)
    return cosine * x + sine * z, y, -sine * x + cosine * z


def _rotate_z(point: tuple[float, float, float], angle: float) -> tuple[float, float, float]:
    x, y, z = point
    cosine, sine = math.cos(angle), math.sin(angle)
    return cosine * x - sine * y, sine * x + cosine * y, z


def _matrix_vector(matrix: tuple[tuple[float, float, float], ...], point: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(sum(matrix[row][column] * point[column] for column in range(3)) for row in range(3))  # type: ignore[return-value]


def _matrix3(value: object) -> tuple[tuple[float, float, float], ...] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 3:
        return None
    rows = []
    for row in value:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) != 3:
            return None
        rows.append(tuple(float(item) for item in row))
    return tuple(rows)


def _vector3(value: object) -> tuple[float, float, float] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 3:
        return None
    return tuple(float(item) for item in value)  # type: ignore[return-value]


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)
