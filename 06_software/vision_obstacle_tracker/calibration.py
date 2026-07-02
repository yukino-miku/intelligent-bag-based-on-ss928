from __future__ import annotations

import ast
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


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
    min_ground_angle_deg: float = 1.0
    max_reliable_ground_distance_m: float = 80.0
    max_reliable_distance_m: float = 120.0
    principal_x_px: float | None = None
    principal_y_px: float | None = None
    camera_matrix: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]] | None = None
    dist_coeffs: tuple[float, ...] | None = None

    @property
    def has_intrinsics(self) -> bool:
        return self.camera_matrix is not None

    @property
    def cx(self) -> float:
        if self.camera_matrix is not None:
            return self.camera_matrix[0][2]
        return self.principal_x_px if self.principal_x_px is not None else self.image_width / 2.0

    @property
    def cy(self) -> float:
        if self.camera_matrix is not None:
            return self.camera_matrix[1][2]
        return self.principal_y_px if self.principal_y_px is not None else self.image_height / 2.0

    @property
    def fx(self) -> float:
        if self.camera_matrix is not None:
            return self.camera_matrix[0][0]
        return self._focal_length_px()

    @property
    def fy(self) -> float:
        if self.camera_matrix is not None:
            return self.camera_matrix[1][1]
        return self._focal_length_px()

    def with_pitch(self, pitch_deg: float) -> "CameraCalibration":
        return replace(self, camera_pitch_deg=pitch_deg)

    def scaled_to_image_size(self, image_width: int, image_height: int) -> "CameraCalibration":
        if self.image_width == image_width and self.image_height == image_height:
            return self
        if self.camera_matrix is None or self.image_width <= 0 or self.image_height <= 0:
            return replace(self, image_width=image_width, image_height=image_height)

        sx = image_width / self.image_width
        sy = image_height / self.image_height
        matrix = (
            (self.camera_matrix[0][0] * sx, self.camera_matrix[0][1], self.camera_matrix[0][2] * sx),
            (self.camera_matrix[1][0], self.camera_matrix[1][1] * sy, self.camera_matrix[1][2] * sy),
            self.camera_matrix[2],
        )
        return replace(self, image_width=image_width, image_height=image_height, camera_matrix=matrix)

    def undistort_pixel(self, x_px: float, y_px: float) -> tuple[float, float]:
        if self.camera_matrix is None or not self.dist_coeffs:
            return x_px, y_px

        try:
            import cv2
            import numpy as np
        except Exception:
            return x_px, y_px

        points = np.array([[[x_px, y_px]]], dtype=np.float64)
        camera_matrix = np.array(self.camera_matrix, dtype=np.float64)
        dist_coeffs = np.array(self.dist_coeffs, dtype=np.float64).reshape(-1, 1)
        undistorted = cv2.undistortPoints(points, camera_matrix, dist_coeffs, P=camera_matrix)
        return float(undistorted[0, 0, 0]), float(undistorted[0, 0, 1])

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
    ground_confidence: float = 0.0
    size_confidence: float = 0.0
    fused_weight_ground: float = 0.0
    fused_weight_size: float = 0.0
    distance_confidence: float = 0.0
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class DistanceReliability:
    ground_confidence: float
    size_confidence: float
    distance_confidence_scale: float
    quality_flags: tuple[str, ...]


OBJECT_DIMENSIONS_BY_CLASS = {
    "bicycle": ObjectDimensions(width_m=0.6, height_m=1.4),
    "car": ObjectDimensions(width_m=1.8, height_m=1.5),
    "motorcycle": ObjectDimensions(width_m=0.8, height_m=1.3),
    "bus": ObjectDimensions(width_m=2.5, height_m=3.0),
    "truck": ObjectDimensions(width_m=2.5, height_m=3.2),
}


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(max(value, low), high)


def load_calibration_file(path: str | Path) -> dict[str, Any]:
    calibration_path = Path(path)
    if calibration_path.suffix.lower() == ".json":
        return json.loads(calibration_path.read_text(encoding="utf-8"))

    text = calibration_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    return _load_simple_yaml_mapping(text)


def calibration_from_mapping(mapping: dict[str, Any], fallback: CameraCalibration) -> CameraCalibration:
    image_width = int(mapping.get("image_width", fallback.image_width))
    image_height = int(mapping.get("image_height", fallback.image_height))
    camera_matrix = _parse_camera_matrix(mapping.get("camera_matrix"))
    dist_coeffs = _parse_dist_coeffs(mapping.get("dist_coeffs"))

    return CameraCalibration(
        image_width=image_width,
        image_height=image_height,
        fov_deg=float(mapping.get("fov_deg", fallback.fov_deg)),
        fov_type=str(mapping.get("fov_type", fallback.fov_type)),
        horizontal_fov_deg=_optional_float(mapping.get("horizontal_fov_deg", fallback.horizontal_fov_deg)),
        camera_height_m=float(mapping.get("camera_height_m", fallback.camera_height_m)),
        camera_pitch_deg=float(mapping.get("camera_pitch_deg", fallback.camera_pitch_deg)),
        distance_scale=float(mapping.get("distance_scale", fallback.distance_scale)),
        min_ground_angle_deg=float(mapping.get("min_ground_angle_deg", fallback.min_ground_angle_deg)),
        max_reliable_ground_distance_m=float(
            mapping.get("max_reliable_ground_distance_m", fallback.max_reliable_ground_distance_m)
        ),
        max_reliable_distance_m=float(mapping.get("max_reliable_distance_m", fallback.max_reliable_distance_m)),
        principal_x_px=_optional_float(mapping.get("principal_x_px", fallback.principal_x_px)),
        principal_y_px=_optional_float(mapping.get("principal_y_px", fallback.principal_y_px)),
        camera_matrix=camera_matrix,
        dist_coeffs=dist_coeffs,
    )


def _load_simple_yaml_mapping(text: str) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    lines = text.splitlines()
    line_index = 0
    while line_index < len(lines):
        line = lines[line_index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            line_index += 1
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        raw_value = _strip_yaml_comment(raw_value.strip())
        if raw_value:
            mapping[key] = _parse_simple_yaml_value(raw_value)
            line_index += 1
            continue

        block_values: list[Any] = []
        line_index += 1
        while line_index < len(lines):
            block_line = lines[line_index]
            if not block_line.startswith((" ", "\t")):
                break
            block_item = block_line.strip()
            if block_item and not block_item.startswith("#") and block_item.startswith("- "):
                block_values.append(_parse_simple_yaml_value(block_item[2:].strip()))
            line_index += 1
        if block_values:
            mapping[key] = block_values
    return mapping


def _strip_yaml_comment(value: str) -> str:
    return value.split("#", 1)[0].strip()


def _parse_simple_yaml_value(value: str) -> Any:
    cleaned = _strip_yaml_comment(value)
    try:
        return ast.literal_eval(cleaned)
    except (SyntaxError, ValueError):
        return cleaned.strip("\"'")


def _parse_camera_matrix(value) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]] | None:
    if value is None:
        return None
    if isinstance(value, dict) and "data" in value:
        value = value["data"]
    rows = value
    if isinstance(value, list) and len(value) == 9 and not isinstance(value[0], list):
        rows = [value[0:3], value[3:6], value[6:9]]
    if not isinstance(rows, list) or len(rows) != 3:
        return None
    return tuple(tuple(float(item) for item in row[:3]) for row in rows[:3])  # type: ignore[return-value]


def _parse_dist_coeffs(value) -> tuple[float, ...] | None:
    if value is None:
        return None
    if isinstance(value, dict) and "data" in value:
        value = value["data"]
    if isinstance(value, list) and value and isinstance(value[0], list):
        flattened: list[float] = []
        for row in value:
            flattened.extend(float(item) for item in row)
        return tuple(flattened)
    if isinstance(value, list):
        return tuple(float(item) for item in value)
    return None


def _optional_float(value) -> float | None:
    return None if value is None else float(value)


def pixel_to_ground(x_px: float, y_px: float, calibration: CameraCalibration) -> GroundPoint | None:
    undistorted_x, undistorted_y = calibration.undistort_pixel(x_px, y_px)
    horizontal_angle = math.atan((undistorted_x - calibration.cx) / calibration.fx)
    ground_angle_down = math.radians(ground_angle_down_deg(x_px, y_px, calibration))

    if ground_angle_down <= 0:
        return None

    z_m = calibration.camera_height_m / math.tan(ground_angle_down)
    if z_m <= 0 or not math.isfinite(z_m):
        return None

    z_m *= calibration.distance_scale
    x_m = z_m * math.tan(horizontal_angle)
    return GroundPoint(x_m=x_m, z_m=z_m)


def ground_angle_down_deg(x_px: float, y_px: float, calibration: CameraCalibration) -> float:
    _undistorted_x, undistorted_y = calibration.undistort_pixel(x_px, y_px)
    vertical_angle_down = math.atan((undistorted_y - calibration.cy) / calibration.fy)
    return calibration.camera_pitch_deg + math.degrees(vertical_angle_down)


def bbox_bottom_center(bbox_xyxy: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, _y1, x2, y2 = bbox_xyxy
    return (x1 + x2) / 2.0, y2


def bbox_center_x(bbox_xyxy: tuple[float, float, float, float]) -> float:
    x1, _y1, x2, _y2 = bbox_xyxy
    return (x1 + x2) / 2.0


def bbox_size_px(bbox_xyxy: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox_xyxy
    return max(0.0, x2 - x1), max(0.0, y2 - y1)


def bbox_is_truncated(bbox_xyxy: tuple[float, float, float, float], calibration: CameraCalibration, margin_px: float = 2.0) -> bool:
    x1, y1, x2, y2 = bbox_xyxy
    return (
        x1 <= margin_px
        or y1 <= margin_px
        or x2 >= calibration.image_width - margin_px
        or y2 >= calibration.image_height - margin_px
    )


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
    undistorted_x, _undistorted_y = calibration.undistort_pixel(x_px, calibration.cy)
    horizontal_angle = math.atan((undistorted_x - calibration.cx) / calibration.fx)
    return GroundPoint(x_m=z_m * math.tan(horizontal_angle), z_m=z_m)


def estimate_distance_reliability(
    bbox_xyxy: tuple[float, float, float, float],
    class_name: str,
    calibration: CameraCalibration,
    ground_distance_m: float | None,
    size_distance_m: float | None,
) -> DistanceReliability:
    x1, y1, x2, y2 = bbox_xyxy
    bbox_width_px, bbox_height_px = bbox_size_px(bbox_xyxy)
    center_x = (x1 + x2) / 2.0
    bottom_y = y2
    bottom_x = center_x
    flags: list[str] = []

    truncated = bbox_is_truncated(bbox_xyxy, calibration)
    if truncated:
        flags.append("truncated")

    edge_margin_ratio = min(center_x, calibration.image_width - center_x) / max(calibration.image_width, 1)
    edge_quality = clamp(edge_margin_ratio / 0.12)
    if edge_quality < 0.5:
        flags.append("edge")

    ground_region_quality = clamp((bottom_y - calibration.image_height * 0.32) / max(calibration.image_height * 0.35, 1.0))
    if ground_region_quality < 0.3:
        flags.append("high_bbox")

    ground_angle = ground_angle_down_deg(bottom_x, bottom_y, calibration)
    ground_is_unreliable = False
    if ground_distance_m is not None and ground_angle < calibration.min_ground_angle_deg:
        ground_is_unreliable = True
        flags.append("near_horizon")
    if (
        ground_distance_m is not None
        and ground_distance_m > calibration.max_reliable_ground_distance_m
    ):
        ground_is_unreliable = True
        flags.append("ground_too_far")

    ground_confidence = 0.0
    if ground_distance_m is not None and not ground_is_unreliable:
        ground_confidence = 0.30 + 0.45 * ground_region_quality + 0.25 * edge_quality
        if truncated:
            ground_confidence *= 0.55

    dimensions = OBJECT_DIMENSIONS_BY_CLASS.get(class_name)
    size_confidence = 0.0
    size_is_unreliable = size_distance_m is not None and size_distance_m > calibration.max_reliable_distance_m
    if size_is_unreliable:
        flags.append("distance_clamped")

    if size_distance_m is not None and dimensions is not None and not size_is_unreliable:
        area_ratio = (bbox_width_px * bbox_height_px) / max(calibration.image_width * calibration.image_height, 1)
        pixel_size_quality = clamp(math.sqrt(max(area_ratio, 0.0) * 300.0))
        aspect_ratio = bbox_width_px / max(bbox_height_px, 1.0)
        expected_aspect = dimensions.width_m / max(dimensions.height_m, 1e-6)
        aspect_ratio_quality = clamp(1.0 - abs(math.log(max(aspect_ratio, 1e-3) / expected_aspect)) / math.log(4.0))
        size_confidence = 0.25 + 0.45 * pixel_size_quality + 0.30 * aspect_ratio_quality
        if truncated:
            size_confidence *= 0.50
        if pixel_size_quality < 0.35:
            flags.append("small_bbox")
        if aspect_ratio_quality < 0.35:
            flags.append("aspect")

    distance_confidence_scale = 1.0
    if ground_distance_m is not None and size_distance_m is not None:
        relative_diff = abs(ground_distance_m - size_distance_m) / max(min(ground_distance_m, size_distance_m), 1.0)
        if relative_diff > 0.55:
            flags.append("distance_disagreement")
            distance_confidence_scale = clamp(1.0 - min(relative_diff, 1.5) * 0.35, 0.35, 1.0)

    return DistanceReliability(
        ground_confidence=clamp(ground_confidence),
        size_confidence=clamp(size_confidence),
        distance_confidence_scale=distance_confidence_scale,
        quality_flags=tuple(dict.fromkeys(flags)),
    )


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
    ground_distance_m = ground_point.distance_m if ground_point is not None else None
    size_distance_m = estimate_size_distance_m(bbox_xyxy, class_name, calibration)
    size_point = point_from_forward_distance(center_x, size_distance_m, calibration) if size_distance_m is not None else None
    reliability = estimate_distance_reliability(
        bbox_xyxy,
        class_name,
        calibration,
        ground_distance_m,
        size_distance_m,
    )
    flags = reliability.quality_flags
    invalid_ground = "near_horizon" in flags or "ground_too_far" in flags
    invalid_size = "distance_clamped" in flags
    if invalid_ground:
        ground_point = None
        ground_distance_m = None
    if invalid_size:
        size_point = None
        size_distance_m = None

    mode = mode.lower()
    if mode == "ground":
        if ground_point is None:
            return None
        return DistanceEstimate(
            point=ground_point,
            source="ground",
            ground_distance_m=ground_distance_m,
            size_distance_m=size_distance_m,
            ground_confidence=reliability.ground_confidence,
            size_confidence=reliability.size_confidence,
            fused_weight_ground=1.0,
            distance_confidence=clamp(reliability.ground_confidence * 0.85),
            quality_flags=reliability.quality_flags,
        )

    if mode == "size":
        if size_point is None:
            return None
        return DistanceEstimate(
            point=size_point,
            source="size",
            ground_distance_m=ground_distance_m,
            size_distance_m=size_distance_m,
            ground_confidence=reliability.ground_confidence,
            size_confidence=reliability.size_confidence,
            fused_weight_size=1.0,
            distance_confidence=clamp(reliability.size_confidence * 0.85),
            quality_flags=reliability.quality_flags,
        )

    if mode != "fused":
        raise ValueError(f"Unsupported distance mode: {mode}")

    if ground_point is not None and size_point is not None:
        ground_weight = reliability.ground_confidence
        size_weight_adaptive = reliability.size_confidence
        if ground_weight + size_weight_adaptive <= 1e-6:
            clamped_size_weight = clamp(size_weight)
            ground_weight = 1.0 - clamped_size_weight
            size_weight_adaptive = clamped_size_weight

        total_weight = max(ground_weight + size_weight_adaptive, 1e-6)
        fused_weight_ground = ground_weight / total_weight
        fused_weight_size = size_weight_adaptive / total_weight
        z_m = ground_point.z_m * fused_weight_ground + size_point.z_m * fused_weight_size
        point = point_from_forward_distance(center_x, z_m, calibration)
        if point is None:
            return None
        base_confidence = max(reliability.ground_confidence, reliability.size_confidence)
        agreement_bonus = min(reliability.ground_confidence, reliability.size_confidence) * 0.25
        distance_confidence = clamp((base_confidence + agreement_bonus) * reliability.distance_confidence_scale)
        return DistanceEstimate(
            point=point,
            source="fused",
            ground_distance_m=ground_distance_m,
            size_distance_m=size_distance_m,
            ground_confidence=reliability.ground_confidence,
            size_confidence=reliability.size_confidence,
            fused_weight_ground=fused_weight_ground,
            fused_weight_size=fused_weight_size,
            distance_confidence=distance_confidence,
            quality_flags=reliability.quality_flags,
        )

    if size_point is not None:
        return DistanceEstimate(
            point=size_point,
            source="size",
            ground_distance_m=ground_distance_m,
            size_distance_m=size_distance_m,
            ground_confidence=reliability.ground_confidence,
            size_confidence=reliability.size_confidence,
            fused_weight_size=1.0,
            distance_confidence=clamp(reliability.size_confidence * 0.75),
            quality_flags=("single_source", *reliability.quality_flags),
        )
    if ground_point is not None:
        return DistanceEstimate(
            point=ground_point,
            source="ground",
            ground_distance_m=ground_distance_m,
            size_distance_m=size_distance_m,
            ground_confidence=reliability.ground_confidence,
            size_confidence=reliability.size_confidence,
            fused_weight_ground=1.0,
            distance_confidence=clamp(reliability.ground_confidence * 0.75),
            quality_flags=("single_source", *reliability.quality_flags),
        )
    return None
