from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum

from vision_core import TrackedObject


DEFAULT_VEHICLE_RISK_MULTIPLIERS = {
    "bicycle": 0.92,
    "motorcycle": 0.96,
    "car": 1.00,
    "truck": 1.10,
    "bus": 1.10,
}


class RiskLevel(IntEnum):
    SAFE = 0
    ATTENTION = 1
    CAUTION = 2
    DANGER = 3
    EMERGENCY = 4


RISK_LEVEL_SCORE_THRESHOLDS = {
    RiskLevel.SAFE: 0.0,
    RiskLevel.ATTENTION: 0.40,
    RiskLevel.CAUTION: 0.60,
    RiskLevel.DANGER: 0.70,
    RiskLevel.EMERGENCY: 0.80,
}


@dataclass(frozen=True)
class RiskWeights:
    trajectory: float = 4.0
    ttc: float = 2.0
    drac: float = 1.5
    closing: float = 1.5


@dataclass(frozen=True)
class RiskModelConfig:
    bicycle_safe_trajectory_distance_m: float = 1.5
    motor_vehicle_safe_trajectory_distance_m: float = 3.0
    emergency_ttc_s: float = 1.50
    danger_ttc_s: float = 2.50
    caution_ttc_s: float = 3.50
    attention_ttc_s: float = 4.50
    safe_ttc_s: float = 5.00
    comfortable_decel_mps2: float = 3.5
    emergency_decel_mps2: float = 7.0
    max_closing_speed_mps: float = 12.0
    trajectory_risk_exponent: float = 2.0
    ttc_risk_exponent: float = 2.0
    vehicle_risk_multipliers: dict[str, float] = field(
        default_factory=lambda: DEFAULT_VEHICLE_RISK_MULTIPLIERS.copy()
    )
    weights: RiskWeights = field(default_factory=RiskWeights)


@dataclass(frozen=True)
class RiskAssessment:
    track_id: int
    score: float
    level: RiskLevel
    ttc_s: float | None
    trajectory_distance_m: float | None
    drac_mps2: float
    closing_speed_mps: float


MOTOR_VEHICLE_CLASSES = {"car", "motorcycle", "truck", "bus"}


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(max(value, low), high)


def risk_score_threshold_for_level(level: RiskLevel) -> float:
    return RISK_LEVEL_SCORE_THRESHOLDS[level]


def risk_level_from_score(score: float) -> RiskLevel:
    if score >= risk_score_threshold_for_level(RiskLevel.EMERGENCY):
        return RiskLevel.EMERGENCY
    if score >= risk_score_threshold_for_level(RiskLevel.DANGER):
        return RiskLevel.DANGER
    if score >= risk_score_threshold_for_level(RiskLevel.CAUTION):
        return RiskLevel.CAUTION
    if score >= risk_score_threshold_for_level(RiskLevel.ATTENTION):
        return RiskLevel.ATTENTION
    return RiskLevel.SAFE


def trajectory_safe_distance_threshold_m(class_name: str, config: RiskModelConfig) -> float:
    if class_name == "bicycle":
        return config.bicycle_safe_trajectory_distance_m
    if class_name in MOTOR_VEHICLE_CLASSES:
        return config.motor_vehicle_safe_trajectory_distance_m
    return config.motor_vehicle_safe_trajectory_distance_m


def vehicle_risk_multiplier(class_name: str, config: RiskModelConfig) -> float:
    return max(0.0, config.vehicle_risk_multipliers.get(class_name, 1.0))


def time_to_collision_s(distance_m: float | None, closing_speed_mps: float) -> float | None:
    if distance_m is None or closing_speed_mps <= 0.05:
        return None
    return distance_m / closing_speed_mps


def decel_required_mps2(distance_m: float | None, closing_speed_mps: float) -> float:
    if distance_m is None or distance_m <= 0.05 or closing_speed_mps <= 0.05:
        return 0.0
    return closing_speed_mps * closing_speed_mps / (2.0 * distance_m)


def radial_closing_speed_mps(x_m: float, z_m: float, vx_mps: float, vz_mps: float) -> float:
    distance_m = math.hypot(x_m, z_m)
    if distance_m <= 1e-6:
        return max(0.0, -vz_mps)
    return max(0.0, -((x_m * vx_mps + z_m * vz_mps) / distance_m))


def trajectory_distance_m(x_m: float, z_m: float, vx_mps: float, vz_mps: float) -> float:
    speed = math.hypot(vx_mps, vz_mps)
    if speed <= 1e-6:
        return math.hypot(x_m, z_m)
    return abs(x_m * vz_mps - z_m * vx_mps) / speed


def _collision_time_risk(time_s: float | None, config: RiskModelConfig) -> float:
    if time_s is None:
        return 0.0
    if time_s <= config.emergency_ttc_s:
        return 1.0
    if time_s >= config.safe_ttc_s:
        return 0.0
    risk_window_s = max(config.safe_ttc_s - config.emergency_ttc_s, 1e-6)
    normalized_time = clamp((time_s - config.emergency_ttc_s) / risk_window_s)
    return clamp(1.0 - normalized_time ** max(config.ttc_risk_exponent, 1e-6))


def _trajectory_distance_risk(trajectory_distance: float, safe_distance_m: float, exponent: float) -> float:
    if safe_distance_m <= 1e-6:
        return 0.0
    normalized_distance = clamp(trajectory_distance / safe_distance_m)
    return clamp(1.0 - normalized_distance ** max(exponent, 1e-6))


def assess_collision_risk(
    target: TrackedObject,
    config: RiskModelConfig | None = None,
) -> RiskAssessment:
    config = config or RiskModelConfig()
    point = target.ground_point
    if point is None or target.distance_m is None:
        return RiskAssessment(
            track_id=target.track_id,
            score=0.0,
            level=RiskLevel.SAFE,
            ttc_s=None,
            trajectory_distance_m=None,
            drac_mps2=0.0,
            closing_speed_mps=0.0,
        )

    trajectory_distance = trajectory_distance_m(point.x_m, point.z_m, target.vx_mps, target.vz_mps)
    if target.vz_mps >= 0.0:
        return RiskAssessment(
            track_id=target.track_id,
            score=0.0,
            level=RiskLevel.SAFE,
            ttc_s=None,
            trajectory_distance_m=trajectory_distance,
            drac_mps2=0.0,
            closing_speed_mps=0.0,
        )

    safe_trajectory_distance = trajectory_safe_distance_threshold_m(target.class_name, config)
    closing_speed = radial_closing_speed_mps(point.x_m, point.z_m, target.vx_mps, target.vz_mps)
    ttc = time_to_collision_s(target.distance_m, closing_speed)
    drac = decel_required_mps2(target.distance_m, closing_speed)

    if ttc is not None and ttc > config.safe_ttc_s:
        return RiskAssessment(
            track_id=target.track_id,
            score=0.0,
            level=RiskLevel.SAFE,
            ttc_s=ttc,
            trajectory_distance_m=trajectory_distance,
            drac_mps2=drac,
            closing_speed_mps=closing_speed,
        )

    if trajectory_distance > safe_trajectory_distance:
        return RiskAssessment(
            track_id=target.track_id,
            score=0.0,
            level=RiskLevel.SAFE,
            ttc_s=ttc,
            trajectory_distance_m=trajectory_distance,
            drac_mps2=drac,
            closing_speed_mps=closing_speed,
        )

    trajectory_risk = _trajectory_distance_risk(
        trajectory_distance,
        safe_trajectory_distance,
        config.trajectory_risk_exponent,
    )
    ttc_risk = _collision_time_risk(ttc, config)
    drac_risk = clamp(
        (drac - config.comfortable_decel_mps2)
        / max(config.emergency_decel_mps2 - config.comfortable_decel_mps2, 0.1)
    )
    closing_risk = clamp(closing_speed / config.max_closing_speed_mps)

    weights = config.weights
    total_weight = max(weights.trajectory + weights.ttc + weights.drac + weights.closing, 1e-6)
    base_score = clamp(
        (
            weights.trajectory * trajectory_risk
            + weights.ttc * ttc_risk
            + weights.drac * drac_risk
            + weights.closing * closing_risk
        )
        / total_weight
    )
    score = clamp(base_score * vehicle_risk_multiplier(target.class_name, config))
    return RiskAssessment(
        track_id=target.track_id,
        score=score,
        level=risk_level_from_score(score),
        ttc_s=ttc,
        trajectory_distance_m=trajectory_distance,
        drac_mps2=drac,
        closing_speed_mps=closing_speed,
    )


class RiskModel:
    def __init__(self, config: RiskModelConfig | None = None) -> None:
        self.config = config or RiskModelConfig()

    def assess(self, target: TrackedObject) -> RiskAssessment:
        return assess_collision_risk(target, self.config)
