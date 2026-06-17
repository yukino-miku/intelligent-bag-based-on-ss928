from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CameraCalibration:
    image_width: int = 2560
    image_height: int = 1440
    fov_deg: float = 120.0
    fov_type: str = "diagonal"
    horizontal_fov_deg: float | None = None
    camera_height_m: float = 1.1
    camera_pitch_deg: float = 5.0
    distance_scale: float = 1.0
    principal_x_px: float | None = None
    principal_y_px: float | None = None

    @property
    def cx(self) -> float:
        return self.principal_x_px if self.principal_x_px is not None else self.image_width / 2.0

    @property
    def cy(self) -> float:
        return self.principal_y_px if self.principal_y_px is not None else self.image_height / 2.0

    @property
    def fx(self) -> float:
        return self._focal_length_px()

    @property
    def fy(self) -> float:
        return self._focal_length_px()

    def _focal_length_px(self) -> float:
        fov_type = self.fov_type.lower()
        if self.horizontal_fov_deg is not None:
            fov_type = "horizontal"
            fov_deg = self.horizontal_fov_deg
        else:
            fov_deg = self.fov_deg

        half_fov = math.radians(fov_deg / 2.0)
        if fov_type == "horizontal":
            sensor_px = float(self.image_width)
        elif fov_type == "vertical":
            sensor_px = float(self.image_height)
        elif fov_type == "diagonal":
            sensor_px = math.hypot(float(self.image_width), float(self.image_height))
        else:
            raise ValueError(f"Unsupported fov_type: {self.fov_type}")
        return sensor_px / (2.0 * math.tan(half_fov))


@dataclass(frozen=True)
class GroundPoint:
    x_m: float
    z_m: float

    @property
    def distance_m(self) -> float:
        return math.hypot(self.x_m, self.z_m)


@dataclass(frozen=True)
class ObjectDimensions:
    width_m: float
    height_m: float


@dataclass(frozen=True)
class DistanceEstimate:
    point: GroundPoint
    source: str
    ground_distance_m: float | None = None
    size_distance_m: float | None = None


OBJECT_DIMENSIONS_BY_CLASS = {
    "bicycle": ObjectDimensions(width_m=0.6, height_m=1.4),
    "car": ObjectDimensions(width_m=1.8, height_m=1.5),
    "motorcycle": ObjectDimensions(width_m=0.8, height_m=1.3),
    "bus": ObjectDimensions(width_m=2.5, height_m=3.0),
    "truck": ObjectDimensions(width_m=2.5, height_m=3.2),
}


def pixel_to_ground(x_px: float, y_px: float, calibration: CameraCalibration) -> GroundPoint | None:
    horizontal_angle = math.atan((x_px - calibration.cx) / calibration.fx)
    vertical_angle_down = math.atan((y_px - calibration.cy) / calibration.fy)
    ground_angle_down = math.radians(calibration.camera_pitch_deg) + vertical_angle_down

    if ground_angle_down <= 0:
        return None

    z_m = calibration.camera_height_m / math.tan(ground_angle_down)
    if z_m <= 0 or not math.isfinite(z_m):
        return None

    z_m *= calibration.distance_scale
    x_m = z_m * math.tan(horizontal_angle)
    return GroundPoint(x_m=x_m, z_m=z_m)


def bbox_bottom_center(bbox_xyxy: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, _y1, x2, y2 = bbox_xyxy
    return (x1 + x2) / 2.0, y2


def bbox_center_x(bbox_xyxy: tuple[float, float, float, float]) -> float:
    x1, _y1, x2, _y2 = bbox_xyxy
    return (x1 + x2) / 2.0


def bbox_size_px(bbox_xyxy: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox_xyxy
    return max(0.0, x2 - x1), max(0.0, y2 - y1)


def estimate_size_distance_m(
    bbox_xyxy: tuple[float, float, float, float],
    class_name: str,
    calibration: CameraCalibration,
) -> float | None:
    dimensions = OBJECT_DIMENSIONS_BY_CLASS.get(class_name)
    if dimensions is None:
        return None

    bbox_width_px, bbox_height_px = bbox_size_px(bbox_xyxy)
    candidates: list[float] = []
    if bbox_height_px >= 8.0:
        candidates.append(dimensions.height_m * calibration.fy / bbox_height_px)
    if bbox_width_px >= 8.0:
        candidates.append(dimensions.width_m * calibration.fx / bbox_width_px)
    if not candidates:
        return None

    candidates.sort()
    if len(candidates) == 1:
        distance_m = candidates[0]
    else:
        distance_m = sum(candidates) / len(candidates)

    distance_m *= calibration.distance_scale
    if distance_m <= 0 or not math.isfinite(distance_m):
        return None
    return distance_m


def point_from_forward_distance(
    x_px: float,
    z_m: float,
    calibration: CameraCalibration,
) -> GroundPoint | None:
    if z_m <= 0 or not math.isfinite(z_m):
        return None
    horizontal_angle = math.atan((x_px - calibration.cx) / calibration.fx)
    return GroundPoint(x_m=z_m * math.tan(horizontal_angle), z_m=z_m)


def estimate_ground_point_from_bbox(
    bbox_xyxy: tuple[float, float, float, float],
    class_name: str,
    calibration: CameraCalibration,
    mode: str = "fused",
    size_weight: float = 0.75,
) -> DistanceEstimate | None:
    bottom_x, bottom_y = bbox_bottom_center(bbox_xyxy)
    center_x = bbox_center_x(bbox_xyxy)
    ground_point = pixel_to_ground(bottom_x, bottom_y, calibration)
    size_distance_m = estimate_size_distance_m(bbox_xyxy, class_name, calibration)

    mode = mode.lower()
    if mode == "ground":
        if ground_point is None:
            return None
        return DistanceEstimate(
            point=ground_point,
            source="ground",
            ground_distance_m=ground_point.distance_m,
            size_distance_m=size_distance_m,
        )

    size_point = point_from_forward_distance(center_x, size_distance_m, calibration) if size_distance_m is not None else None
    if mode == "size":
        if size_point is None:
            return None
        return DistanceEstimate(
            point=size_point,
            source="size",
            ground_distance_m=ground_point.distance_m if ground_point is not None else None,
            size_distance_m=size_distance_m,
        )

    if mode != "fused":
        raise ValueError(f"Unsupported distance mode: {mode}")

    if ground_point is not None and size_point is not None:
        clamped_size_weight = min(max(size_weight, 0.0), 1.0)
        z_m = ground_point.z_m * (1.0 - clamped_size_weight) + size_point.z_m * clamped_size_weight
        point = point_from_forward_distance(center_x, z_m, calibration)
        if point is None:
            return None
        return DistanceEstimate(
            point=point,
            source="fused",
            ground_distance_m=ground_point.distance_m,
            size_distance_m=size_distance_m,
        )

    if size_point is not None:
        return DistanceEstimate(
            point=size_point,
            source="size",
            ground_distance_m=None,
            size_distance_m=size_distance_m,
        )
    if ground_point is not None:
        return DistanceEstimate(
            point=ground_point,
            source="ground",
            ground_distance_m=ground_point.distance_m,
            size_distance_m=None,
        )
    return None
