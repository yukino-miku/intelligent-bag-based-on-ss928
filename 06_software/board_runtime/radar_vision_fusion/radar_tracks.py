from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median

from mr20_radar.mr20_radar import MR20Target, RadarConfig, RadarScan


@dataclass(frozen=True)
class RadarTrackManagerConfig:
    radar_track_timeout_s: float = 0.8
    radar_max_missed_scans: int = 3
    history_size: int = 12
    position_jump_m: float = 4.0
    velocity_jump_mps: float = 12.0
    corridor_half_width_m: float = 1.2
    corridor_depth_m: float = 5.0
    conflict_horizon_s: float = 6.0


@dataclass
class RadarTrack:
    track_key: str
    radar_name: str
    side: str
    target_id: int
    generation: int
    first_seen_mono_s: float
    last_seen_mono_s: float
    age_scans: int
    missed_scans: int
    x_m: float
    z_m: float
    vx_mps: float
    vz_mps: float
    distance_m: float
    speed_mps: float
    status: str
    measurement_count: int
    position_history: list[tuple[float, float, float]] = field(default_factory=list)
    velocity_history: list[tuple[float, float, float]] = field(default_factory=list)
    radar_quality: float = 0.0
    active: bool = True
    position_jitter_m: float = 0.0
    distance_trend_mps: float = 0.0
    approach_consistency: float = 0.0
    path_conflict_consistency: float = 0.0
    motion_quality_flags: tuple[str, ...] = ()


class RadarTrackManager:
    def __init__(self, config: RadarTrackManagerConfig | None = None) -> None:
        self.config = config or RadarTrackManagerConfig()
        self._tracks: dict[str, RadarTrack] = {}
        self._current_key: dict[tuple[str, int], str] = {}
        self._generation: dict[tuple[str, int], int] = {}
        self._last_measurement: dict[str, int] = {}

    def update(self, scan: RadarScan, radar_config: RadarConfig) -> tuple[tuple[RadarTrack, ...], tuple[str, ...]]:
        if scan.radar_name != radar_config.name or scan.side != radar_config.side:
            raise ValueError("RadarScan does not match RadarConfig")
        if self._last_measurement.get(scan.radar_name) == scan.measurement_count:
            return self.active_tracks(scan.side), ()
        self._last_measurement[scan.radar_name] = scan.measurement_count

        now_s = scan.captured_mono_s
        present_ids = {target.target_id for target in scan.targets}
        for track in self._tracks.values():
            if track.active and track.radar_name == scan.radar_name and track.target_id not in present_ids:
                track.missed_scans += 1

        for target in scan.targets:
            source_key = (scan.radar_name, target.target_id)
            track_key = self._current_key.get(source_key)
            track = self._tracks.get(track_key or "")
            if track is None or not track.active or now_s - track.last_seen_mono_s > self.config.radar_track_timeout_s:
                if track is not None:
                    self._retire(track)
                track = self._new_track(scan, target, radar_config)
            else:
                self._update_track(track, scan, target, radar_config)

        removed = self.prune(now_s)
        return self.active_tracks(scan.side), removed

    def prune(self, now_s: float) -> tuple[str, ...]:
        removed: list[str] = []
        for track in list(self._tracks.values()):
            if not track.active:
                continue
            timed_out = now_s - track.last_seen_mono_s > self.config.radar_track_timeout_s
            missed_out = track.missed_scans >= self.config.radar_max_missed_scans
            if timed_out or missed_out:
                removed.append(track.track_key)
                self._retire(track)
        return tuple(removed)

    def active_tracks(self, side: str | None = None) -> tuple[RadarTrack, ...]:
        tracks = [
            track for track in self._tracks.values()
            if track.active and (side is None or track.side == side)
        ]
        return tuple(sorted(tracks, key=lambda item: item.track_key))

    def get(self, track_key: str) -> RadarTrack | None:
        track = self._tracks.get(track_key)
        return track if track is not None and track.active else None

    def _new_track(self, scan: RadarScan, target: MR20Target, radar_config: RadarConfig) -> RadarTrack:
        source_key = (scan.radar_name, target.target_id)
        generation = self._generation.get(source_key, 0) + 1
        self._generation[source_key] = generation
        track_key = f"{scan.radar_name}:{target.target_id}:{generation}"
        x_m, z_m, vx_mps, vz_mps = transform_target(target, radar_config)
        track = RadarTrack(
            track_key=track_key,
            radar_name=scan.radar_name,
            side=scan.side,
            target_id=target.target_id,
            generation=generation,
            first_seen_mono_s=scan.captured_mono_s,
            last_seen_mono_s=scan.captured_mono_s,
            age_scans=1,
            missed_scans=0,
            x_m=x_m,
            z_m=z_m,
            vx_mps=vx_mps,
            vz_mps=vz_mps,
            distance_m=math.hypot(x_m, z_m),
            speed_mps=math.hypot(vx_mps, vz_mps),
            status=target.status,
            measurement_count=scan.measurement_count,
        )
        self._append_history(track, scan.captured_mono_s)
        self._refresh_quality(track)
        self._tracks[track_key] = track
        self._current_key[source_key] = track_key
        return track

    def _update_track(self, track: RadarTrack, scan: RadarScan, target: MR20Target, radar_config: RadarConfig) -> None:
        x_m, z_m, vx_mps, vz_mps = transform_target(target, radar_config)
        flags: list[str] = []
        if math.hypot(x_m - track.x_m, z_m - track.z_m) > self.config.position_jump_m:
            flags.append("position_jump")
        if math.hypot(vx_mps - track.vx_mps, vz_mps - track.vz_mps) > self.config.velocity_jump_mps:
            flags.append("velocity_jump")
        track.last_seen_mono_s = scan.captured_mono_s
        track.age_scans += 1
        track.missed_scans = 0
        track.x_m = x_m
        track.z_m = z_m
        track.vx_mps = vx_mps
        track.vz_mps = vz_mps
        track.distance_m = math.hypot(x_m, z_m)
        track.speed_mps = math.hypot(vx_mps, vz_mps)
        track.status = target.status
        track.measurement_count = scan.measurement_count
        track.motion_quality_flags = tuple(flags)
        self._append_history(track, scan.captured_mono_s)
        self._refresh_quality(track)

    def _append_history(self, track: RadarTrack, timestamp_s: float) -> None:
        track.position_history.append((timestamp_s, track.x_m, track.z_m))
        track.velocity_history.append((timestamp_s, track.vx_mps, track.vz_mps))
        del track.position_history[:-self.config.history_size]
        del track.velocity_history[:-self.config.history_size]

    def _refresh_quality(self, track: RadarTrack) -> None:
        trends: list[float] = []
        approach_hits = 0
        conflict_hits = 0
        residuals: list[float] = []
        segments = 0
        for previous, current in zip(track.position_history, track.position_history[1:]):
            dt_s = current[0] - previous[0]
            if dt_s <= 1e-6:
                continue
            previous_distance = math.hypot(previous[1], previous[2])
            current_distance = math.hypot(current[1], current[2])
            trend = (current_distance - previous_distance) / dt_s
            trends.append(trend)
            if trend < -0.05:
                approach_hits += 1
            segments += 1
            if _enters_corridor(
                current[1], current[2], track.vx_mps, track.vz_mps,
                self.config.corridor_half_width_m, self.config.corridor_depth_m,
                self.config.conflict_horizon_s,
            ):
                conflict_hits += 1
            predicted_x = previous[1] + track.vx_mps * dt_s
            predicted_z = previous[2] + track.vz_mps * dt_s
            residuals.append(math.hypot(current[1] - predicted_x, current[2] - predicted_z))

        track.distance_trend_mps = float(median(trends)) if trends else 0.0
        track.approach_consistency = approach_hits / segments if segments else 0.0
        track.path_conflict_consistency = conflict_hits / segments if segments else 0.0
        track.position_jitter_m = float(median(residuals)) if residuals else 0.0
        age_quality = min(1.0, track.age_scans / 3.0)
        jitter_quality = max(0.0, 1.0 - track.position_jitter_m / max(self.config.position_jump_m, 0.1))
        jump_penalty = 0.45 if track.motion_quality_flags else 1.0
        track.radar_quality = max(0.0, min(1.0, age_quality * jitter_quality * jump_penalty))

    def _retire(self, track: RadarTrack) -> None:
        track.active = False
        source_key = (track.radar_name, track.target_id)
        if self._current_key.get(source_key) == track.track_key:
            del self._current_key[source_key]


def transform_target(target: MR20Target, config: RadarConfig) -> tuple[float, float, float, float]:
    x_local = -target.lateral_distance_m if config.invert_lateral else target.lateral_distance_m
    z_local = -target.longitudinal_distance_m if config.invert_longitudinal else target.longitudinal_distance_m
    vx_local = -target.lateral_velocity_mps if config.invert_lateral_velocity else target.lateral_velocity_mps
    vz_local = -target.longitudinal_velocity_mps if config.invert_longitudinal_velocity else target.longitudinal_velocity_mps
    yaw = math.radians(config.mount_yaw_deg)
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)
    x_m = config.mount_x_m + cos_yaw * x_local + sin_yaw * z_local
    z_m = config.mount_z_m - sin_yaw * x_local + cos_yaw * z_local
    vx_mps = cos_yaw * vx_local + sin_yaw * vz_local
    vz_mps = -sin_yaw * vx_local + cos_yaw * vz_local
    return x_m, z_m, vx_mps, vz_mps


def _enters_corridor(
    x_m: float,
    z_m: float,
    vx_mps: float,
    vz_mps: float,
    half_width_m: float,
    depth_m: float,
    horizon_s: float,
) -> bool:
    def interval(position: float, velocity: float, low: float, high: float) -> tuple[float, float] | None:
        if abs(velocity) <= 1e-6:
            return (-math.inf, math.inf) if low <= position <= high else None
        first = (low - position) / velocity
        second = (high - position) / velocity
        return min(first, second), max(first, second)

    x_interval = interval(x_m, vx_mps, -half_width_m, half_width_m)
    z_interval = interval(z_m, vz_mps, 0.0, depth_m)
    if x_interval is None or z_interval is None:
        return False
    enter_s = max(0.0, x_interval[0], z_interval[0])
    exit_s = min(horizon_s, x_interval[1], z_interval[1])
    return enter_s <= exit_s
