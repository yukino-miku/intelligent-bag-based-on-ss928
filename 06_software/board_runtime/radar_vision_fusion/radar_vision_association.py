from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

try:
    from .models import AssociationMatch, ClassificationFrame, ProjectedRadarTarget, VehicleDetection
    from .radar_camera_calibration import FusionCalibration, project_radar_track
    from .radar_tracks import RadarTrack
except ImportError:
    from models import AssociationMatch, ClassificationFrame, ProjectedRadarTarget, VehicleDetection
    from radar_camera_calibration import FusionCalibration, project_radar_track
    from radar_tracks import RadarTrack


@dataclass(frozen=True)
class AssociationConfig:
    max_time_delta_s: float = 0.20
    max_horizontal_error_px: float = 160.0
    max_horizontal_error_ratio: float = 0.15
    max_association_cost: float = 1.0
    bbox_horizontal_margin_ratio: float = 0.25
    weight_horizontal: float = 0.58
    weight_time: float = 0.14
    weight_history: float = 0.14
    weight_motion: float = 0.09
    weight_size: float = 0.05


@dataclass(frozen=True)
class AssociationResult:
    matches: tuple[AssociationMatch, ...]
    projections: tuple[ProjectedRadarTarget, ...]
    unmatched_track_keys: tuple[str, ...]
    unmatched_detection_ids: tuple[int, ...]


class RadarVisionAssociation:
    def __init__(self, config: AssociationConfig | None = None) -> None:
        self.config = config or AssociationConfig()
        self._last_detection_u: dict[str, float] = {}

    def associate(
        self,
        frame: ClassificationFrame,
        tracks: Sequence[RadarTrack],
        calibration: FusionCalibration,
        bound_classes: Mapping[str, str] | None = None,
    ) -> AssociationResult:
        bound_classes = bound_classes or {}
        side_tracks = [track for track in tracks if track.active and track.side == frame.side]
        projections = [
            project_radar_track(
                track,
                calibration,
                frame.captured_mono_s,
                frame.image_width,
                frame.image_height,
            )
            for track in side_tracks
        ]
        eligible: list[tuple[RadarTrack, ProjectedRadarTarget]] = []
        for track, projection in zip(side_tracks, projections):
            if abs(projection.time_delta_s) > self.config.max_time_delta_s:
                continue
            if not projection.projected_in_frame or projection.projected_u_px is None:
                continue
            eligible.append((track, projection))

        detections = list(frame.detections)
        if not eligible or not detections:
            return AssociationResult(
                matches=(),
                projections=tuple(projections),
                unmatched_track_keys=tuple(track.track_key for track in side_tracks),
                unmatched_detection_ids=tuple(item.detection_id for item in detections),
            )

        invalid_cost = self.config.max_association_cost + 1000.0
        costs: list[list[float]] = []
        details: dict[tuple[int, int], tuple[float, float]] = {}
        for track_index, (track, projection) in enumerate(eligible):
            row: list[float] = []
            assert projection.projected_u_px is not None
            for detection_index, detection in enumerate(detections):
                horizontal_error = abs(projection.projected_u_px - detection.bbox_center_x)
                bbox_width = max(1.0, detection.bbox_xyxy[2] - detection.bbox_xyxy[0])
                margin_px = bbox_width * self.config.bbox_horizontal_margin_ratio
                inside_expanded_box = (
                    detection.bbox_xyxy[0] - margin_px
                    <= projection.projected_u_px
                    <= detection.bbox_xyxy[2] + margin_px
                )
                horizontal_limit = min(
                    self.config.max_horizontal_error_px,
                    frame.image_width * self.config.max_horizontal_error_ratio,
                )
                if not inside_expanded_box and horizontal_error > horizontal_limit:
                    row.append(invalid_cost)
                    continue
                cost = self._cost(
                    track,
                    projection,
                    detection,
                    frame.image_width,
                    bound_classes.get(track.track_key),
                )
                row.append(cost)
                details[(track_index, detection_index)] = (horizontal_error, projection.time_delta_s)
            costs.append(row)

        pairs = _hungarian_square(costs, unmatched_cost=self.config.max_association_cost)
        matches: list[AssociationMatch] = []
        matched_tracks: set[str] = set()
        matched_detections: set[int] = set()
        for track_index, detection_index in pairs:
            if track_index >= len(eligible) or detection_index >= len(detections):
                continue
            cost = costs[track_index][detection_index]
            if not math.isfinite(cost) or cost > self.config.max_association_cost:
                continue
            track, projection = eligible[track_index]
            detection = detections[detection_index]
            horizontal_error, time_delta = details[(track_index, detection_index)]
            assert projection.projected_u_px is not None
            matches.append(
                AssociationMatch(
                    track_key=track.track_key,
                    detection_id=detection.detection_id,
                    side=frame.side,
                    class_name=detection.class_name,
                    class_confidence=detection.confidence,
                    association_score=cost,
                    projected_u_px=projection.projected_u_px,
                    horizontal_error_px=horizontal_error,
                    time_delta_s=time_delta,
                )
            )
            matched_tracks.add(track.track_key)
            matched_detections.add(detection.detection_id)
            self._last_detection_u[track.track_key] = detection.bbox_center_x

        return AssociationResult(
            matches=tuple(matches),
            projections=tuple(projections),
            unmatched_track_keys=tuple(track.track_key for track in side_tracks if track.track_key not in matched_tracks),
            unmatched_detection_ids=tuple(item.detection_id for item in detections if item.detection_id not in matched_detections),
        )

    def forget(self, track_keys: Sequence[str]) -> None:
        for track_key in track_keys:
            self._last_detection_u.pop(track_key, None)

    def _cost(
        self,
        track: RadarTrack,
        projection: ProjectedRadarTarget,
        detection: VehicleDetection,
        image_width: int,
        bound_class: str | None,
    ) -> float:
        assert projection.projected_u_px is not None
        horizontal = abs(projection.projected_u_px - detection.bbox_center_x) / max(1.0, image_width)
        time_cost = abs(projection.time_delta_s) / max(self.config.max_time_delta_s, 1e-6)
        history_cost = 0.0 if not bound_class or bound_class == detection.class_name else 1.0
        previous_u = self._last_detection_u.get(track.track_key)
        motion_cost = 0.0 if previous_u is None else min(1.0, abs(previous_u - detection.bbox_center_x) / max(1.0, image_width))
        bbox_width_ratio = max(0.0, detection.bbox_xyxy[2] - detection.bbox_xyxy[0]) / max(1.0, image_width)
        expected_width_ratio = min(0.8, max(0.02, 0.7 / max(track.distance_m, 0.5)))
        size_cost = min(1.0, abs(bbox_width_ratio - expected_width_ratio) / max(expected_width_ratio, 0.02))
        return (
            self.config.weight_horizontal * horizontal
            + self.config.weight_time * time_cost
            + self.config.weight_history * history_cost
            + self.config.weight_motion * motion_cost
            + self.config.weight_size * size_cost
        )


def _hungarian_square(costs: Sequence[Sequence[float]], unmatched_cost: float) -> tuple[tuple[int, int], ...]:
    row_count = len(costs)
    column_count = max((len(row) for row in costs), default=0)
    size = max(row_count, column_count)
    if size == 0:
        return ()
    matrix = [
        [
            float(costs[row][column]) if row < row_count and column < len(costs[row]) else float(unmatched_cost)
            for column in range(size)
        ]
        for row in range(size)
    ]

    u = [0.0] * (size + 1)
    v = [0.0] * (size + 1)
    p = [0] * (size + 1)
    way = [0] * (size + 1)
    for row in range(1, size + 1):
        p[0] = row
        column0 = 0
        minimum = [math.inf] * (size + 1)
        used = [False] * (size + 1)
        while True:
            used[column0] = True
            current_row = p[column0]
            delta = math.inf
            column1 = 0
            for column in range(1, size + 1):
                if used[column]:
                    continue
                current = matrix[current_row - 1][column - 1] - u[current_row] - v[column]
                if current < minimum[column]:
                    minimum[column] = current
                    way[column] = column0
                if minimum[column] < delta:
                    delta = minimum[column]
                    column1 = column
            for column in range(size + 1):
                if used[column]:
                    u[p[column]] += delta
                    v[column] -= delta
                else:
                    minimum[column] -= delta
            column0 = column1
            if p[column0] == 0:
                break
        while True:
            column1 = way[column0]
            p[column0] = p[column1]
            column0 = column1
            if column0 == 0:
                break
    assignment = [(p[column] - 1, column - 1) for column in range(1, size + 1) if p[column] > 0]
    return tuple(assignment)
