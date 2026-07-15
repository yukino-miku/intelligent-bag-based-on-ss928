#!/usr/bin/env python3
"""Threshold + finite-state-machine IMU fall and impact detector.

Input units are g for acceleration and deg/s for gyro. The detector is pure
Python and has no third-party dependencies, so it can be embedded directly in
an SS928 Linux userspace program.
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple


class State(Enum):
    NORMAL = "NORMAL"
    POSSIBLE_FALL = "POSSIBLE_FALL"
    IMPACT = "IMPACT"
    POSTURE_CHANGED = "POSTURE_CHANGED"
    FALL_CONFIRMED = "FALL_CONFIRMED"
    IMPACT_ONLY = "IMPACT_ONLY"


@dataclass(frozen=True)
class ImuSample:
    """One IMU sample.

    t is seconds from any monotonic or wall-clock source. Acceleration is g,
    gyro is deg/s.
    """

    t: float
    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float


@dataclass
class DetectorConfig:
    sample_hz: float = 50.0
    filter_window_samples: int = 5

    low_g_threshold: float = 0.45
    low_g_min_s: float = 0.10
    possible_fall_gyro_dps: float = 220.0
    possible_fall_jerk_gps: float = 18.0

    impact_g_threshold: float = 2.7
    impact_jerk_gps: float = 45.0
    impact_gyro_dps: float = 360.0
    impact_window_s: float = 0.9
    impact_only_timeout_s: float = 0.75

    posture_delta_deg: float = 45.0
    posture_hold_s: float = 0.30
    fall_confirm_timeout_s: float = 2.5

    stationary_accel_tol_g: float = 0.08
    stationary_gyro_dps: float = 12.0
    stationary_jerk_gps: float = 2.0
    stationary_hold_s: float = 0.45

    terminal_hold_s: float = 1.5
    max_dt_s: float = 0.25

    @classmethod
    def from_dict(cls, values: Dict[str, Any]) -> "DetectorConfig":
        cfg = cls()
        valid = set(asdict(cfg).keys())
        for key, value in values.items():
            if key in valid:
                setattr(cfg, key, value)
        cfg.filter_window_samples = max(1, int(cfg.filter_window_samples))
        cfg.sample_hz = float(cfg.sample_hz)
        return cfg


class _VectorWindow:
    def __init__(self, size: int):
        self.size = max(1, int(size))
        self._values: Deque[Tuple[float, float, float]] = deque(maxlen=self.size)

    def append(self, item: Tuple[float, float, float]) -> Tuple[float, float, float]:
        self._values.append(item)
        sx = sy = sz = 0.0
        for x, y, z in self._values:
            sx += x
            sy += y
            sz += z
        n = float(len(self._values))
        return (sx / n, sy / n, sz / n)

    def clear(self) -> None:
        self._values.clear()


def norm3(v: Tuple[float, float, float]) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _unit(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    n = norm3(v)
    if n < 1e-9:
        return (0.0, 0.0, 1.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def _angle_between_deg(
    a: Tuple[float, float, float], b: Tuple[float, float, float]
) -> float:
    ua = _unit(a)
    ub = _unit(b)
    dot = max(-1.0, min(1.0, ua[0] * ub[0] + ua[1] * ub[1] + ua[2] * ub[2]))
    return math.degrees(math.acos(dot))


def _roll_pitch_deg(a: Tuple[float, float, float]) -> Tuple[float, float]:
    ax, ay, az = a
    roll = math.degrees(math.atan2(ay, az))
    pitch = math.degrees(math.atan2(-ax, math.sqrt(ay * ay + az * az)))
    return roll, pitch


def _round_float(value: float, digits: int = 3) -> float:
    if not math.isfinite(value):
        return 0.0
    return round(float(value), digits)


class FallImpactDetector:
    """Stateful IMU fall/impact detector.

    Call update() once per IMU frame. The method returns transition events; most
    normal frames return an empty list. last_features always contains the latest
    filtered metrics for logging or debugging.
    """

    def __init__(self, config: Optional[DetectorConfig] = None):
        self.config = config or DetectorConfig()
        self._accel_window = _VectorWindow(self.config.filter_window_samples)
        self._gyro_window = _VectorWindow(self.config.filter_window_samples)
        self.state = State.NORMAL
        self.state_since: Optional[float] = None
        self.last_features: Dict[str, Any] = {}
        self._last_t: Optional[float] = None
        self._prev_accel: Optional[Tuple[float, float, float]] = None
        self._prev_raw_accel: Optional[Tuple[float, float, float]] = None
        self._baseline_accel: Optional[Tuple[float, float, float]] = None
        self._low_g_time = 0.0
        self._posture_time = 0.0
        self._stationary_time = 0.0
        self._fall_started_t: Optional[float] = None
        self._impact_t: Optional[float] = None

    def reset(self) -> None:
        self._accel_window.clear()
        self._gyro_window.clear()
        self.state = State.NORMAL
        self.state_since = None
        self.last_features = {}
        self._last_t = None
        self._prev_accel = None
        self._prev_raw_accel = None
        self._baseline_accel = None
        self._low_g_time = 0.0
        self._posture_time = 0.0
        self._stationary_time = 0.0
        self._fall_started_t = None
        self._impact_t = None

    def update(self, sample: ImuSample) -> List[Dict[str, Any]]:
        features = self._compute_features(sample)
        self.last_features = features
        events: List[Dict[str, Any]] = []

        if self._leave_terminal_if_ready(features):
            self._update_baseline_if_safe(features)
            return events

        if self.state is State.NORMAL:
            self._update_baseline_if_safe(features)
            if self._is_impact(features):
                events.append(self._transition(State.IMPACT, "impact", "direct impact", features))
            elif self._is_possible_fall(features):
                self._low_g_time += features["dt_s"]
                if self._low_g_time >= self.config.low_g_min_s:
                    events.append(
                        self._transition(
                            State.POSSIBLE_FALL,
                            "possible_fall",
                            "low-g or fast rotation before impact",
                            features,
                        )
                    )
            else:
                self._low_g_time = 0.0

        elif self.state is State.POSSIBLE_FALL:
            if self._is_impact(features):
                events.append(self._transition(State.IMPACT, "impact", "impact after possible fall", features))
            elif self._state_age(features) > self.config.impact_window_s:
                self._set_state(State.NORMAL, features["t"])
                self._fall_started_t = None
                self._low_g_time = 0.0

        elif self.state is State.IMPACT:
            if self._posture_changed(features):
                self._posture_time += features["dt_s"]
                if self._posture_time >= self.config.posture_hold_s:
                    events.append(
                        self._transition(
                            State.POSTURE_CHANGED,
                            "posture_changed",
                            "posture angle changed after impact",
                            features,
                        )
                    )
            else:
                self._posture_time = 0.0
                if self._state_age(features) >= self.config.impact_only_timeout_s:
                    events.append(
                        self._transition(
                            State.IMPACT_ONLY,
                            "impact_only",
                            "impact did not become a fall posture",
                            features,
                        )
                    )

        elif self.state is State.POSTURE_CHANGED:
            if features["stationary"]:
                events.append(
                    self._transition(
                        State.FALL_CONFIRMED,
                        "fall_confirmed",
                        "posture changed and became stationary",
                        features,
                    )
                )
            elif self._state_age(features) >= self.config.fall_confirm_timeout_s:
                self._set_state(State.NORMAL, features["t"])
                self._fall_started_t = None
                self._impact_t = None
                self._posture_time = 0.0

        return events

    def _compute_features(self, sample: ImuSample) -> Dict[str, Any]:
        if self._last_t is None:
            dt = 1.0 / self.config.sample_hz
        else:
            dt = sample.t - self._last_t
            if dt <= 0.0 or dt > self.config.max_dt_s:
                dt = 1.0 / self.config.sample_hz
        self._last_t = sample.t

        raw_accel = (float(sample.ax), float(sample.ay), float(sample.az))
        raw_gyro = (float(sample.gx), float(sample.gy), float(sample.gz))
        accel = self._accel_window.append(raw_accel)
        gyro = self._gyro_window.append(raw_gyro)

        raw_accel_g = norm3(raw_accel)
        raw_gyro_dps = norm3(raw_gyro)
        accel_g = norm3(accel)
        gyro_dps = norm3(gyro)

        jerk_gps = 0.0
        if self._prev_accel is not None:
            jerk_gps = norm3(
                (
                    (accel[0] - self._prev_accel[0]) / dt,
                    (accel[1] - self._prev_accel[1]) / dt,
                    (accel[2] - self._prev_accel[2]) / dt,
                )
            )
        self._prev_accel = accel

        raw_jerk_gps = 0.0
        if self._prev_raw_accel is not None:
            raw_jerk_gps = norm3(
                (
                    (raw_accel[0] - self._prev_raw_accel[0]) / dt,
                    (raw_accel[1] - self._prev_raw_accel[1]) / dt,
                    (raw_accel[2] - self._prev_raw_accel[2]) / dt,
                )
            )
        self._prev_raw_accel = raw_accel

        if self._baseline_accel is None and accel_g > 0.2:
            self._baseline_accel = accel

        roll_deg, pitch_deg = _roll_pitch_deg(accel)
        baseline = self._baseline_accel or (0.0, 0.0, 1.0)
        posture_delta_deg = _angle_between_deg(baseline, accel)

        stationary_candidate = (
            abs(accel_g - 1.0) <= self.config.stationary_accel_tol_g
            and gyro_dps <= self.config.stationary_gyro_dps
            and jerk_gps <= self.config.stationary_jerk_gps
        )
        if stationary_candidate:
            self._stationary_time += dt
        else:
            self._stationary_time = 0.0
        stationary = self._stationary_time >= self.config.stationary_hold_s

        return {
            "t": float(sample.t),
            "dt_s": dt,
            "ax_g": raw_accel[0],
            "ay_g": raw_accel[1],
            "az_g": raw_accel[2],
            "gx_dps": raw_gyro[0],
            "gy_dps": raw_gyro[1],
            "gz_dps": raw_gyro[2],
            "filtered_ax_g": accel[0],
            "filtered_ay_g": accel[1],
            "filtered_az_g": accel[2],
            "filtered_gx_dps": gyro[0],
            "filtered_gy_dps": gyro[1],
            "filtered_gz_dps": gyro[2],
            "accel_g": accel_g,
            "gyro_dps": gyro_dps,
            "jerk_gps": jerk_gps,
            "raw_accel_g": raw_accel_g,
            "raw_gyro_dps": raw_gyro_dps,
            "raw_jerk_gps": raw_jerk_gps,
            "roll_deg": roll_deg,
            "pitch_deg": pitch_deg,
            "posture_delta_deg": posture_delta_deg,
            "stationary_candidate": stationary_candidate,
            "stationary": stationary,
            "stationary_time_s": self._stationary_time,
        }

    def _update_baseline_if_safe(self, features: Dict[str, Any]) -> None:
        if not features["stationary_candidate"]:
            return
        if not 0.75 <= features["accel_g"] <= 1.25:
            return
        self._baseline_accel = (
            features["filtered_ax_g"],
            features["filtered_ay_g"],
            features["filtered_az_g"],
        )

    def _is_possible_fall(self, features: Dict[str, Any]) -> bool:
        low_g = (
            features["raw_accel_g"] <= self.config.low_g_threshold
            or features["accel_g"] <= self.config.low_g_threshold
        )
        violent_motion = (
            max(features["raw_gyro_dps"], features["gyro_dps"])
            >= self.config.possible_fall_gyro_dps
            and max(features["raw_jerk_gps"], features["jerk_gps"])
            >= self.config.possible_fall_jerk_gps
        )
        return low_g or violent_motion

    def _is_impact(self, features: Dict[str, Any]) -> bool:
        accel_hit = max(features["raw_accel_g"], features["accel_g"]) >= self.config.impact_g_threshold
        jerk_hit = (
            max(features["raw_jerk_gps"], features["jerk_gps"]) >= self.config.impact_jerk_gps
            and max(features["raw_accel_g"], features["accel_g"]) >= 1.6
        )
        gyro_hit = (
            max(features["raw_gyro_dps"], features["gyro_dps"]) >= self.config.impact_gyro_dps
            and max(features["raw_accel_g"], features["accel_g"]) >= 1.3
        )
        return accel_hit or jerk_hit or gyro_hit

    def _posture_changed(self, features: Dict[str, Any]) -> bool:
        if not 0.65 <= features["accel_g"] <= 1.45:
            return False
        return features["posture_delta_deg"] >= self.config.posture_delta_deg

    def _state_age(self, features: Dict[str, Any]) -> float:
        if self.state_since is None:
            return 0.0
        return max(0.0, features["t"] - self.state_since)

    def _leave_terminal_if_ready(self, features: Dict[str, Any]) -> bool:
        if self.state not in (State.FALL_CONFIRMED, State.IMPACT_ONLY):
            return False
        if self._state_age(features) < self.config.terminal_hold_s:
            return False
        self._set_state(State.NORMAL, features["t"])
        self._fall_started_t = None
        self._impact_t = None
        self._posture_time = 0.0
        self._low_g_time = 0.0
        return True

    def _transition(
        self, new_state: State, event_name: str, reason: str, features: Dict[str, Any]
    ) -> Dict[str, Any]:
        self._set_state(new_state, features["t"])
        if new_state is State.POSSIBLE_FALL:
            self._fall_started_t = features["t"]
        elif new_state is State.IMPACT:
            self._impact_t = features["t"]
            self._posture_time = 0.0
        elif new_state in (State.FALL_CONFIRMED, State.IMPACT_ONLY):
            self._low_g_time = 0.0
        return self._build_event(new_state, event_name, reason, features)

    def _set_state(self, new_state: State, t: float) -> None:
        self.state = new_state
        self.state_since = t

    def _build_event(
        self, state: State, event_name: str, reason: str, features: Dict[str, Any]
    ) -> Dict[str, Any]:
        severity = {
            State.POSSIBLE_FALL: "info",
            State.IMPACT: "medium",
            State.POSTURE_CHANGED: "medium",
            State.FALL_CONFIRMED: "high",
            State.IMPACT_ONLY: "medium",
        }.get(state, "info")
        return {
            "type": "imu_fall_event",
            "event": event_name,
            "state": state.value,
            "severity": severity,
            "reason": reason,
            "t": _round_float(features["t"], 3),
            "sample_hz": float(self.config.sample_hz),
            "metrics": _event_metrics(features),
            "sample": {
                "accel_unit": "g",
                "gyro_unit": "deg/s",
                "a": [
                    _round_float(features["ax_g"], 4),
                    _round_float(features["ay_g"], 4),
                    _round_float(features["az_g"], 4),
                ],
                "g": [
                    _round_float(features["gx_dps"], 2),
                    _round_float(features["gy_dps"], 2),
                    _round_float(features["gz_dps"], 2),
                ],
            },
            "fsm": {
                "fall_started_t": None
                if self._fall_started_t is None
                else _round_float(self._fall_started_t, 3),
                "impact_t": None if self._impact_t is None else _round_float(self._impact_t, 3),
                "state_since_t": None
                if self.state_since is None
                else _round_float(self.state_since, 3),
            },
        }


def _event_metrics(features: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "accel_g": _round_float(features["accel_g"], 3),
        "gyro_dps": _round_float(features["gyro_dps"], 2),
        "jerk_gps": _round_float(features["jerk_gps"], 2),
        "raw_accel_g": _round_float(features["raw_accel_g"], 3),
        "raw_gyro_dps": _round_float(features["raw_gyro_dps"], 2),
        "raw_jerk_gps": _round_float(features["raw_jerk_gps"], 2),
        "roll_deg": _round_float(features["roll_deg"], 2),
        "pitch_deg": _round_float(features["pitch_deg"], 2),
        "posture_delta_deg": _round_float(features["posture_delta_deg"], 2),
        "stationary": bool(features["stationary"]),
        "stationary_time_s": _round_float(features["stationary_time_s"], 3),
    }


def event_to_json(event: Dict[str, Any]) -> str:
    """Serialize one detector event as compact JSONL-friendly text."""

    return json.dumps(event, separators=(",", ":"), ensure_ascii=True)


def events_to_json(events: Iterable[Dict[str, Any]]) -> List[str]:
    return [event_to_json(event) for event in events]


def load_config(path: str) -> DetectorConfig:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "detector" in data and isinstance(data["detector"], dict):
        data = data["detector"]
    return DetectorConfig.from_dict(data)
