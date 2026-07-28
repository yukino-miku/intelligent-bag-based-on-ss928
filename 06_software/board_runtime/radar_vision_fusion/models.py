from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class VehicleDetection:
    detection_id: int
    class_id: int
    class_name: str
    confidence: float
    bbox_xyxy: tuple[float, float, float, float]
    bbox_center_x: float
    bbox_center_y: float
    bbox_bottom_x: float
    bbox_bottom_y: float

    @classmethod
    def from_bbox(
        cls,
        detection_id: int,
        class_id: int,
        class_name: str,
        confidence: float,
        bbox_xyxy: tuple[float, float, float, float],
    ) -> "VehicleDetection":
        x1, y1, x2, y2 = (float(value) for value in bbox_xyxy)
        return cls(
            detection_id=int(detection_id),
            class_id=int(class_id),
            class_name=str(class_name),
            confidence=float(confidence),
            bbox_xyxy=(x1, y1, x2, y2),
            bbox_center_x=(x1 + x2) * 0.5,
            bbox_center_y=(y1 + y2) * 0.5,
            bbox_bottom_x=(x1 + x2) * 0.5,
            bbox_bottom_y=y2,
        )


@dataclass(frozen=True)
class ClassificationFrame:
    side: str
    frame_id: int
    captured_mono_s: float
    image_width: int
    image_height: int
    detections: tuple[VehicleDetection, ...]
    camera_state: str
    capture_latency_ms: float
    inference_latency_ms: float
    image: object | None = field(default=None, repr=False, compare=False)
    streamon_latency_ms: float = 0.0
    first_frame_latency_ms: float = 0.0
    streamoff_latency_ms: float = 0.0
    association_latency_ms: float = 0.0


@dataclass(frozen=True)
class ProjectedRadarTarget:
    track_key: str
    side: str
    projected_u_px: float | None
    projected_v_px: float | None
    projected_in_frame: bool
    radar_bearing_deg: float
    camera_bearing_deg: float | None
    x_at_camera_time_m: float
    z_at_camera_time_m: float
    time_delta_s: float


@dataclass(frozen=True)
class AssociationMatch:
    track_key: str
    detection_id: int
    side: str
    class_name: str
    class_confidence: float
    association_score: float
    projected_u_px: float
    horizontal_error_px: float
    time_delta_s: float
    overlap_width_px: float = 0.0
    horizontal_overlap_cost: float = 0.0
    center_distance_cost: float = 0.0
    time_delta_cost: float = 0.0
    weak_size_cost: float = 0.0
    radar_region: tuple[float, float] = (0.0, 0.0)
    detection_region: tuple[float, float] = (0.0, 0.0)


@dataclass(frozen=True)
class VisualClassEntry:
    class_name: str = "unknown"
    confidence: float = 0.0
    detection_id: int | None = None
    association_score: float | None = None
    association_state: str = "unknown"


@dataclass(frozen=True)
class LatestVisualClassMap:
    side: str
    frame_id: int
    captured_mono_s: float
    mapping: dict[str, VisualClassEntry]

    def resolve(self, track_key: str, now_s: float, max_age_s: float) -> tuple[VisualClassEntry, float]:
        age_s = max(0.0, float(now_s) - self.captured_mono_s)
        if age_s > max(0.0, max_age_s):
            return VisualClassEntry(association_state="stale"), age_s
        return self.mapping.get(track_key, VisualClassEntry()), age_s


@dataclass(frozen=True)
class FusedRadarTarget:
    track_key: str
    radar_name: str
    radar_target_id: int
    side: str
    x_m: float
    z_m: float
    vx_mps: float
    vz_mps: float
    distance_m: float
    speed_mps: float
    radar_status: str
    radar_quality: float
    class_name: str
    class_confidence: float
    class_source: str
    class_age_s: float
    association_state: str
    association_score: float | None
    projected_u_px: float | None
    timestamp: float
    detection_id: int | None = None
