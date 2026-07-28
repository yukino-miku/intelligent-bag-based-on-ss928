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
    projection_half_width_px: float = 80.0
    projection_half_width_ratio: float = 0.04
    bbox_expand_ratio: float = 0.25
    association_max_time_delta_s: float = 0.20
    max_center_distance_px: float = 180.0
    max_association_cost: float = 1.0
    ambiguity_cost_gap: float = 0.05
    weight_overlap: float = 0.45
    weight_center: float = 0.30
    weight_time: float = 0.20
    weight_size: float = 0.05


@dataclass(frozen=True)
class AssociationResult:
    matches: tuple[AssociationMatch, ...]
    projections: tuple[ProjectedRadarTarget, ...]
    unmatched_track_keys: tuple[str, ...]
    unmatched_detection_ids: tuple[int, ...]
    ambiguous_track_keys: tuple[str, ...] = ()


class RadarVisionAssociation:
    def __init__(self, config: AssociationConfig | None = None) -> None:
        self.config = config or AssociationConfig()

    def associate(
        self,
        frame: ClassificationFrame,
        tracks: Sequence[RadarTrack],
        calibration: FusionCalibration,
        bound_classes: Mapping[str, str] | None = None,
    ) -> AssociationResult:
        # Kept only for source compatibility. Formal association never uses
        # historical classes or previous visual positions.
        del bound_classes
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
            if abs(projection.time_delta_s) > self.config.association_max_time_delta_s:
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
        details: dict[
            tuple[int, int],
            tuple[float, float, float, float, float, float, tuple[float, float], tuple[float, float]],
        ] = {}
        for track_index, (track, projection) in enumerate(eligible):
            row: list[float] = []
            assert projection.projected_u_px is not None
            for detection_index, detection in enumerate(detections):
                horizontal_error = abs(projection.projected_u_px - detection.bbox_center_x)
                bbox_width = max(1.0, detection.bbox_xyxy[2] - detection.bbox_xyxy[0])
                radar_half_width = (
                    self.config.projection_half_width_px
                    + frame.image_width * self.config.projection_half_width_ratio
                )
                radar_region = (
                    projection.projected_u_px - radar_half_width,
                    projection.projected_u_px + radar_half_width,
                )
                detection_margin = bbox_width * self.config.bbox_expand_ratio
                detection_region = (
                    detection.bbox_xyxy[0] - detection_margin,
                    detection.bbox_xyxy[2] + detection_margin,
                )
                overlap_width = _interval_overlap_width(radar_region, detection_region)
                if overlap_width <= 0.0 or horizontal_error > self.config.max_center_distance_px:
                    row.append(invalid_cost)
                    continue
                cost, overlap_cost, center_cost, time_cost, size_cost = self._cost(
                    track,
                    projection,
                    detection,
                    overlap_width,
                    radar_region,
                    detection_region,
                )
                row.append(cost)
                details[(track_index, detection_index)] = (
                    horizontal_error,
                    overlap_width,
                    overlap_cost,
                    center_cost,
                    time_cost,
                    size_cost,
                    radar_region,
                    detection_region,
                )
            costs.append(row)

        ambiguous_indices: set[int] = set()
        for track_index, row in enumerate(costs):
            valid = sorted(value for value in row if value <= self.config.max_association_cost)
            if len(valid) >= 2 and valid[1] - valid[0] < self.config.ambiguity_cost_gap:
                ambiguous_indices.add(track_index)
                costs[track_index] = [invalid_cost] * len(row)

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
            (
                horizontal_error,
                overlap_width,
                overlap_cost,
                center_cost,
                time_cost,
                size_cost,
                radar_region,
                detection_region,
            ) = details[(track_index, detection_index)]
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
                    time_delta_s=projection.time_delta_s,
                    overlap_width_px=overlap_width,
                    horizontal_overlap_cost=overlap_cost,
                    center_distance_cost=center_cost,
                    time_delta_cost=time_cost,
                    weak_size_cost=size_cost,
                    radar_region=radar_region,
                    detection_region=detection_region,
                )
            )
            matched_tracks.add(track.track_key)
            matched_detections.add(detection.detection_id)

        return AssociationResult(
            matches=tuple(matches),
            projections=tuple(projections),
            unmatched_track_keys=tuple(track.track_key for track in side_tracks if track.track_key not in matched_tracks),
            unmatched_detection_ids=tuple(item.detection_id for item in detections if item.detection_id not in matched_detections),
            ambiguous_track_keys=tuple(eligible[index][0].track_key for index in sorted(ambiguous_indices)),
        )

    def forget(self, track_keys: Sequence[str]) -> None:
        del track_keys

    def _cost(
        self,
        track: RadarTrack,
        projection: ProjectedRadarTarget,
        detection: VehicleDetection,
        overlap_width: float,
        radar_region: tuple[float, float],
        detection_region: tuple[float, float],
    ) -> tuple[float, float, float, float, float]:
        assert projection.projected_u_px is not None
        radar_width = max(1.0, radar_region[1] - radar_region[0])
        detection_width = max(1.0, detection_region[1] - detection_region[0])
        overlap_cost = 1.0 - min(1.0, overlap_width / min(radar_width, detection_width))
        center_cost = min(
            1.0,
            abs(projection.projected_u_px - detection.bbox_center_x)
            / max(self.config.max_center_distance_px, 1.0),
        )
        time_cost = min(
            1.0,
            abs(projection.time_delta_s) / max(self.config.association_max_time_delta_s, 1e-6),
        )
        bbox_width = max(1.0, detection.bbox_xyxy[2] - detection.bbox_xyxy[0])
        expected_width_px = max(8.0, 360.0 / max(track.distance_m, 0.5))
        size_cost = min(1.0, abs(bbox_width - expected_width_px) / expected_width_px)
        total = (
            self.config.weight_overlap * overlap_cost
            + self.config.weight_center * center_cost
            + self.config.weight_time * time_cost
            + self.config.weight_size * size_cost
        )
        return total, overlap_cost, center_cost, time_cost, size_cost


def _interval_overlap_width(left: tuple[float, float], right: tuple[float, float]) -> float:
    return max(0.0, min(left[1], right[1]) - max(left[0], right[0]))


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
