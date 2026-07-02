from __future__ import annotations

import math
from dataclasses import dataclass, replace
from statistics import median

from calibration import GroundPoint


TARGET_CLASS_NAMES = {
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "bus",
    "truck",
    "traffic light",
    "stop sign",
    "parking meter",
    "bench",
}


@dataclass(frozen=True)
class DetectionObservation:
    track_id: int
    class_name: str
    confidence: float
    bbox_xyxy: tuple[float, float, float, float]
    ground_point: GroundPoint | None
    timestamp_s: float
    distance_source: str = "unknown"
    ground_distance_m: float | None = None
    size_distance_m: float | None = None
    distance_confidence: float = 1.0
    ground_confidence: float = 1.0
    size_confidence: float = 1.0
    quality_flags: tuple[str, ...] = ()
    observation_quality: float = 0.5


@dataclass(frozen=True)
class TrackedObject:
    track_id: int
    class_name: str
    confidence: float
    bbox_xyxy: tuple[float, float, float, float]
    ground_point: GroundPoint | None
    distance_m: float | None
    vx_mps: float
    vz_mps: float
    speed_mps: float
    timestamp_s: float
    distance_source: str = "unknown"
    ground_distance_m: float | None = None
    size_distance_m: float | None = None
    distance_confidence: float = 1.0
    ground_confidence: float = 1.0
    size_confidence: float = 1.0
    quality_flags: tuple[str, ...] = ()
    observation_quality: float = 0.5
    velocity_confidence: float = 1.0
    ego_motion_magnitude: float = 0.0
    motion_quality_flags: tuple[str, ...] = ()
    track_age_frames: int = 1
    velocity_stability: float = 1.0
    position_jitter_m: float = 0.0


@dataclass
class _StableTrackMemory:
    stable_id: int
    raw_track_id: int
    class_name: str
    ground_point: GroundPoint | None
    timestamp_s: float


class StableTrackIdManager:
    def __init__(
        self,
        max_match_distance_m: float = 2.5,
        max_time_gap_s: float = 1.0,
    ) -> None:
        self.max_match_distance_m = max_match_distance_m
        self.max_time_gap_s = max_time_gap_s
        self._next_stable_id = 1
        self._raw_to_stable: dict[int, int] = {}
        self._memory_by_stable: dict[int, _StableTrackMemory] = {}

    def assign(self, observations: list[DetectionObservation]) -> list[DetectionObservation]:
        assigned_this_frame: set[int] = set()
        stable_observations: list[DetectionObservation] = []

        for observation in observations:
            stable_id = self._stable_id_for_raw_track(observation)
            if stable_id is None or stable_id in assigned_this_frame:
                stable_id = self._match_recent_track(observation, assigned_this_frame)
            if stable_id is None:
                stable_id = self._allocate_stable_id()

            self._raw_to_stable[observation.track_id] = stable_id
            assigned_this_frame.add(stable_id)
            self._memory_by_stable[stable_id] = _StableTrackMemory(
                stable_id=stable_id,
                raw_track_id=observation.track_id,
                class_name=observation.class_name,
                ground_point=observation.ground_point,
                timestamp_s=observation.timestamp_s,
            )
            stable_observations.append(replace(observation, track_id=stable_id))

        self._prune_old_memory(observations)
        return stable_observations

    def _stable_id_for_raw_track(self, observation: DetectionObservation) -> int | None:
        stable_id = self._raw_to_stable.get(observation.track_id)
        if stable_id is None:
            return None
        memory = self._memory_by_stable.get(stable_id)
        if memory is None:
            return None
        if memory.class_name != observation.class_name:
            return None
        return stable_id

    def _match_recent_track(
        self,
        observation: DetectionObservation,
        assigned_this_frame: set[int],
    ) -> int | None:
        if observation.ground_point is None:
            return None

        best_stable_id = None
        best_distance = math.inf
        for stable_id, memory in self._memory_by_stable.items():
            if stable_id in assigned_this_frame:
                continue
            if memory.class_name != observation.class_name or memory.ground_point is None:
                continue
            time_gap = observation.timestamp_s - memory.timestamp_s
            if time_gap < 0.0 or time_gap > self.max_time_gap_s:
                continue

            distance = math.hypot(
                observation.ground_point.x_m - memory.ground_point.x_m,
                observation.ground_point.z_m - memory.ground_point.z_m,
            )
            if distance <= self.max_match_distance_m and distance < best_distance:
                best_distance = distance
                best_stable_id = stable_id

        return best_stable_id

    def _allocate_stable_id(self) -> int:
        stable_id = self._next_stable_id
        self._next_stable_id += 1
        return stable_id

    def _prune_old_memory(self, observations: list[DetectionObservation]) -> None:
        if not observations:
            return
        newest_timestamp = max(observation.timestamp_s for observation in observations)
        stale_before = newest_timestamp - self.max_time_gap_s * 4.0
        stale_ids = [
            stable_id
            for stable_id, memory in self._memory_by_stable.items()
            if memory.timestamp_s < stale_before
        ]
        for stable_id in stale_ids:
            del self._memory_by_stable[stable_id]
        stale_id_set = set(stale_ids)
        self._raw_to_stable = {
            raw_id: stable_id
            for raw_id, stable_id in self._raw_to_stable.items()
            if stable_id not in stale_id_set
        }


class TrackState:
    def __init__(
        self,
        history_seconds: float = 1.5,
        smoothing_alpha: float = 0.35,
        max_speed_mps: float = 40.0,
        speed_scale: float = 1.0,
    ) -> None:
        self.history_seconds = history_seconds
        self.smoothing_alpha = min(max(smoothing_alpha, 0.0), 1.0)
        self.max_speed_mps = max_speed_mps
        self.speed_scale = speed_scale
        self._history_by_id: dict[int, list[tuple[GroundPoint, float]]] = {}
        self._smoothed_ground_by_id: dict[int, GroundPoint] = {}
        self._track_age_by_id: dict[int, int] = {}
        self._previous_speed_by_id: dict[int, float] = {}

    def update(self, observation: DetectionObservation, ego_motion_magnitude: float = 0.0) -> TrackedObject:
        distance_m = observation.ground_point.distance_m if observation.ground_point is not None else None
        vx_mps = 0.0
        vz_mps = 0.0
        velocity_stability = 1.0
        position_jitter_m = 0.0
        output_point = observation.ground_point
        motion_quality_flags: list[str] = []
        track_age_frames = self._track_age_by_id.get(observation.track_id, 0) + 1
        self._track_age_by_id[observation.track_id] = track_age_frames

        if observation.ground_point is not None:
            output_point = self._smooth_point(observation.track_id, observation.ground_point)
            distance_m = output_point.distance_m
            history = self._history_by_id.setdefault(observation.track_id, [])
            history.append((output_point, observation.timestamp_s))
            min_time = observation.timestamp_s - self.history_seconds
            while len(history) > 2 and history[0][1] < min_time:
                del history[0]

            if len(history) >= 2:
                vx_mps, vz_mps, velocity_stability, position_jitter_m = self._estimate_velocity(history)
                if velocity_stability < 0.65:
                    motion_quality_flags.append("unstable_velocity")
                if position_jitter_m >= 0.50:
                    motion_quality_flags.append("position_jitter")

        speed_mps = math.hypot(vx_mps, vz_mps)
        if self.max_speed_mps > 0 and speed_mps > self.max_speed_mps:
            vx_mps = 0.0
            vz_mps = 0.0
            speed_mps = 0.0
            motion_quality_flags.append("speed_spike")

        velocity_confidence = self._velocity_confidence(
            observation,
            speed_mps,
            ego_motion_magnitude,
            motion_quality_flags,
            velocity_stability,
            position_jitter_m,
            track_age_frames,
        )
        self._previous_speed_by_id[observation.track_id] = speed_mps
        observation_quality = compute_observation_quality(
            detection_confidence=observation.confidence,
            distance_confidence=observation.distance_confidence,
            velocity_confidence=velocity_confidence,
            track_age_frames=track_age_frames,
            quality_flags=observation.quality_flags,
            motion_quality_flags=tuple(motion_quality_flags),
        )

        return TrackedObject(
            track_id=observation.track_id,
            class_name=observation.class_name,
            confidence=observation.confidence,
            bbox_xyxy=observation.bbox_xyxy,
            ground_point=output_point,
            distance_m=distance_m,
            vx_mps=vx_mps,
            vz_mps=vz_mps,
            speed_mps=speed_mps,
            timestamp_s=observation.timestamp_s,
            distance_source=observation.distance_source,
            ground_distance_m=observation.ground_distance_m,
            size_distance_m=observation.size_distance_m,
            distance_confidence=observation.distance_confidence,
            ground_confidence=observation.ground_confidence,
            size_confidence=observation.size_confidence,
            quality_flags=observation.quality_flags,
            observation_quality=observation_quality,
            velocity_confidence=velocity_confidence,
            ego_motion_magnitude=ego_motion_magnitude,
            motion_quality_flags=tuple(motion_quality_flags),
            track_age_frames=track_age_frames,
            velocity_stability=velocity_stability,
            position_jitter_m=position_jitter_m,
        )

    def _smooth_point(self, track_id: int, point: GroundPoint) -> GroundPoint:
        previous = self._smoothed_ground_by_id.get(track_id)
        if previous is None or self.smoothing_alpha >= 1.0:
            self._smoothed_ground_by_id[track_id] = point
            return point

        alpha = self.smoothing_alpha
        smoothed = GroundPoint(
            x_m=previous.x_m * (1.0 - alpha) + point.x_m * alpha,
            z_m=previous.z_m * (1.0 - alpha) + point.z_m * alpha,
        )
        self._smoothed_ground_by_id[track_id] = smoothed
        return smoothed

    def _estimate_velocity(self, history: list[tuple[GroundPoint, float]]) -> tuple[float, float, float, float]:
        segment_velocities: list[tuple[float, float]] = []
        for (previous_point, previous_time), (current_point, current_time) in zip(history, history[1:]):
            dt_s = current_time - previous_time
            if dt_s <= 1e-6:
                continue
            vx = (current_point.x_m - previous_point.x_m) / dt_s
            vz = (current_point.z_m - previous_point.z_m) / dt_s
            segment_velocities.append((vx, vz))

        if not segment_velocities:
            return 0.0, 0.0, 0.0, 0.0

        usable_velocities = segment_velocities
        if self.max_speed_mps > 0 and len(segment_velocities) >= 3:
            filtered = [
                (vx, vz)
                for vx, vz in segment_velocities
                if math.hypot(vx, vz) <= self.max_speed_mps
            ]
            if filtered:
                usable_velocities = filtered

        vx_mps = median(vx for vx, _vz in usable_velocities) * self.speed_scale
        vz_mps = median(vz for _vx, vz in usable_velocities) * self.speed_scale
        position_jitter_m = self._position_jitter_m(history, vx_mps / max(self.speed_scale, 1e-6), vz_mps / max(self.speed_scale, 1e-6))
        reversal_count = self._velocity_reversal_count(segment_velocities)

        stability = 1.0
        if len(history) < 3:
            stability *= 0.75
        if reversal_count:
            stability *= max(0.25, 1.0 - 0.35 * reversal_count)
        if position_jitter_m >= 1.0:
            stability *= 0.30
        elif position_jitter_m >= 0.50:
            stability *= 0.50
        elif position_jitter_m >= 0.25:
            stability *= 0.75
        return vx_mps, vz_mps, clamp(stability), position_jitter_m

    @staticmethod
    def _position_jitter_m(history: list[tuple[GroundPoint, float]], vx_mps: float, vz_mps: float) -> float:
        if len(history) < 3:
            return 0.0
        last_point, last_time = history[-1]
        residuals: list[float] = []
        for point, timestamp_s in history[:-1]:
            dt_s = timestamp_s - last_time
            expected_x = last_point.x_m + vx_mps * dt_s
            expected_z = last_point.z_m + vz_mps * dt_s
            residuals.append(math.hypot(point.x_m - expected_x, point.z_m - expected_z))
        return float(median(residuals)) if residuals else 0.0

    @staticmethod
    def _velocity_reversal_count(segment_velocities: list[tuple[float, float]]) -> int:
        reversals = 0
        for previous, current in zip(segment_velocities, segment_velocities[1:]):
            previous_speed = math.hypot(previous[0], previous[1])
            current_speed = math.hypot(current[0], current[1])
            if previous_speed <= 0.10 or current_speed <= 0.10:
                continue
            if previous[0] * current[0] + previous[1] * current[1] < 0.0:
                reversals += 1
        return reversals

    def _velocity_confidence(
        self,
        observation: DetectionObservation,
        speed_mps: float,
        ego_motion_magnitude: float,
        motion_quality_flags: list[str],
        velocity_stability: float,
        position_jitter_m: float,
        track_age_frames: int,
    ) -> float:
        confidence = clamp(observation.distance_confidence)
        if observation.ground_point is None:
            motion_quality_flags.append("no_ground_point")
            return 0.0

        strong_ego_motion = (
            ego_motion_magnitude >= 0.030
            if ego_motion_magnitude <= 1.0
            else ego_motion_magnitude >= 14.0
        )
        moderate_ego_motion = (
            ego_motion_magnitude >= 0.015
            if ego_motion_magnitude <= 1.0
            else ego_motion_magnitude >= 7.0
        )

        if strong_ego_motion:
            confidence *= 0.70
            motion_quality_flags.append("strong_ego_motion")
        elif moderate_ego_motion:
            confidence *= 0.85
            motion_quality_flags.append("ego_motion")

        previous_speed = self._previous_speed_by_id.get(observation.track_id)
        if previous_speed is not None and speed_mps - previous_speed > 8.0:
            confidence *= 0.50
            motion_quality_flags.append("speed_jump")

        if track_age_frames < 3:
            confidence *= 0.85
            motion_quality_flags.append("short_track")
        if velocity_stability < 0.45:
            confidence *= 0.45
        elif velocity_stability < 0.70:
            confidence *= 0.70
        if position_jitter_m >= 1.0:
            confidence *= 0.40
        elif position_jitter_m >= 0.50:
            confidence *= 0.60
        if "velocity_reversal" not in motion_quality_flags:
            history = self._history_by_id.get(observation.track_id, [])
            segment_velocities = []
            for (previous_point, previous_time), (current_point, current_time) in zip(history, history[1:]):
                dt_s = current_time - previous_time
                if dt_s > 1e-6:
                    segment_velocities.append(
                        (
                            (current_point.x_m - previous_point.x_m) / dt_s,
                            (current_point.z_m - previous_point.z_m) / dt_s,
                        )
                    )
            if self._velocity_reversal_count(segment_velocities):
                confidence *= 0.65
                motion_quality_flags.append("velocity_reversal")

        return clamp(confidence)


def parse_target_classes(value: str) -> set[str] | None:
    cleaned = value.strip()
    if cleaned.lower() == "all":
        return None
    return {item.strip() for item in cleaned.split(",") if item.strip()}


def should_keep_class(class_name: str, target_classes: set[str] | None = TARGET_CLASS_NAMES) -> bool:
    return target_classes is None or class_name in target_classes


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(max(value, low), high)


def compute_observation_quality(
    detection_confidence: float,
    distance_confidence: float,
    velocity_confidence: float,
    track_age_frames: int,
    quality_flags: tuple[str, ...] = (),
    motion_quality_flags: tuple[str, ...] = (),
) -> float:
    detection_quality = clamp((detection_confidence - 0.05) / 0.45)
    track_quality = clamp(track_age_frames / 5.0)
    quality = (
        0.15 * detection_quality
        + 0.55 * clamp(distance_confidence)
        + 0.15 * clamp(velocity_confidence)
        + 0.15 * track_quality
    )
    if "truncated" in quality_flags:
        quality *= 0.80
    if "distance_disagreement" in quality_flags:
        quality *= 0.75
    if "strong_ego_motion" in motion_quality_flags:
        quality *= 0.70
    return clamp(quality)


def format_overlay_label(target: TrackedObject, verbosity: str = "normal") -> str:
    distance = f"{target.distance_m:.1f}m" if target.distance_m is not None else "unknown"
    if verbosity == "minimal":
        return f"{target.class_name} d={distance}"
    if verbosity == "debug":
        return (
            f"ID {target.track_id} {target.class_name} {target.confidence:.2f} "
            f"d={distance}({target.distance_source},q={target.distance_confidence:.2f}) "
            f"v={target.speed_mps:.1f}m/s qV={target.velocity_confidence:.2f} "
            f"vx={target.vx_mps:+.1f} vz={target.vz_mps:+.1f} "
            f"stab={target.velocity_stability:.2f} jitter={target.position_jitter_m:.2f}"
        )
    return f"ID {target.track_id} {target.class_name} d={distance} v={target.speed_mps:.1f}m/s"
