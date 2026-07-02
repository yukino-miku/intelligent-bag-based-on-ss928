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


class MotionPattern(IntEnum):
    STATIC_OR_UNCERTAIN = 0
    MOVING_AWAY = 1
    LATERAL_CUT_IN = 2
    HEAD_ON_OR_CLOSING = 3
    NEAR_STATIC_OBSTACLE = 4


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
    static_obstacle: float = 1.4


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
    min_closing_speed_mps: float = 0.20
    lateral_cut_in_speed_mps: float = 0.50
    near_static_distance_m: float = 2.00
    static_obstacle_risk_start_m: float = 2.00
    static_obstacle_emergency_m: float = 0.60
    trajectory_risk_exponent: float = 2.0
    ttc_risk_exponent: float = 2.0
    velocity_risk_confidence_floor: float = 0.65
    cut_in_attention_trajectory_ratio: float = 0.50
    cut_in_caution_trajectory_ratio: float = 0.30
    cut_in_caution_trajectory_m: float = 0.50
    cut_in_caution_ttc_s: float = 3.50
    cut_in_attention_score_floor: float = 0.40
    cut_in_caution_score_floor: float = 0.60
    near_static_attention_distance_m: float = 1.50
    near_static_caution_distance_m: float = 1.00
    near_static_danger_distance_m: float = 0.60
    near_static_attention_score_floor: float = 0.40
    near_static_caution_score_floor: float = 0.60
    near_static_danger_score_floor: float = 0.70
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
    motion_pattern: MotionPattern = MotionPattern.STATIC_OR_UNCERTAIN
    static_obstacle_risk: float = 0.0
    trajectory_risk: float = 0.0
    ttc_risk: float = 0.0
    drac_risk: float = 0.0
    closing_risk: float = 0.0


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


def motion_pattern_name(pattern: MotionPattern) -> str:
    return {
        MotionPattern.STATIC_OR_UNCERTAIN: "STATIC",
        MotionPattern.MOVING_AWAY: "AWAY",
        MotionPattern.LATERAL_CUT_IN: "CUTIN",
        MotionPattern.HEAD_ON_OR_CLOSING: "CLOSING",
        MotionPattern.NEAR_STATIC_OBSTACLE: "NEAR",
    }[pattern]


def classify_motion_pattern(
    target: TrackedObject,
    trajectory_distance: float,
    closing_speed_mps: float,
    config: RiskModelConfig,
) -> MotionPattern:
    distance_m = target.distance_m
    speed_mps = target.speed_mps
    if distance_m is not None and distance_m <= config.near_static_distance_m and speed_mps <= 0.35:
        return MotionPattern.NEAR_STATIC_OBSTACLE
    if closing_speed_mps >= config.min_closing_speed_mps:
        if abs(target.vx_mps) >= max(abs(target.vz_mps), 0.1) * 0.8 and trajectory_distance <= trajectory_safe_distance_threshold_m(target.class_name, config):
            return MotionPattern.LATERAL_CUT_IN
        return MotionPattern.HEAD_ON_OR_CLOSING
    if speed_mps >= 0.35 and closing_speed_mps < config.min_closing_speed_mps:
        return MotionPattern.MOVING_AWAY
    return MotionPattern.STATIC_OR_UNCERTAIN


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


def _near_static_obstacle_risk(distance_m: float | None, config: RiskModelConfig) -> float:
    if distance_m is None or distance_m >= config.static_obstacle_risk_start_m:
        return 0.0
    risk_window = max(config.static_obstacle_risk_start_m - config.static_obstacle_emergency_m, 1e-6)
    normalized = clamp((distance_m - config.static_obstacle_emergency_m) / risk_window)
    return clamp(1.0 - normalized)


def _apply_motion_pattern_score_floor(
    score: float,
    target: TrackedObject,
    motion_pattern: MotionPattern,
    trajectory_distance: float,
    safe_trajectory_distance: float,
    ttc_s: float | None,
    config: RiskModelConfig,
) -> float:
    if motion_pattern == MotionPattern.LATERAL_CUT_IN:
        trajectory_ratio = trajectory_distance / max(safe_trajectory_distance, 1e-6)
        lateral_speed = abs(target.vx_mps)
        if (
            trajectory_ratio <= config.cut_in_attention_trajectory_ratio
            and lateral_speed >= config.lateral_cut_in_speed_mps
        ):
            score = max(score, config.cut_in_attention_score_floor)
        if (
            trajectory_ratio <= config.cut_in_caution_trajectory_ratio
            or trajectory_distance <= config.cut_in_caution_trajectory_m
            or (ttc_s is not None and ttc_s <= config.cut_in_caution_ttc_s)
        ) and lateral_speed >= config.lateral_cut_in_speed_mps:
            score = max(score, config.cut_in_caution_score_floor)

    if motion_pattern == MotionPattern.NEAR_STATIC_OBSTACLE and target.distance_m is not None:
        if target.distance_m <= config.near_static_danger_distance_m:
            score = max(score, config.near_static_danger_score_floor)
        elif target.distance_m <= config.near_static_caution_distance_m:
            score = max(score, config.near_static_caution_score_floor)
        elif target.distance_m <= config.near_static_attention_distance_m:
            score = max(score, config.near_static_attention_score_floor)

    return clamp(score)


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
            motion_pattern=MotionPattern.STATIC_OR_UNCERTAIN,
        )

    trajectory_distance = trajectory_distance_m(point.x_m, point.z_m, target.vx_mps, target.vz_mps)
    safe_trajectory_distance = trajectory_safe_distance_threshold_m(target.class_name, config)
    closing_speed = radial_closing_speed_mps(point.x_m, point.z_m, target.vx_mps, target.vz_mps)
    ttc = time_to_collision_s(target.distance_m, closing_speed)
    drac = decel_required_mps2(target.distance_m, closing_speed)
    motion_pattern = classify_motion_pattern(target, trajectory_distance, closing_speed, config)
    static_obstacle_risk = _near_static_obstacle_risk(target.distance_m, config)

    if ttc is not None and ttc > config.safe_ttc_s:
        return RiskAssessment(
            track_id=target.track_id,
            score=0.0,
            level=RiskLevel.SAFE,
            ttc_s=ttc,
            trajectory_distance_m=trajectory_distance,
            drac_mps2=drac,
            closing_speed_mps=closing_speed,
            motion_pattern=motion_pattern,
            static_obstacle_risk=static_obstacle_risk,
        )

    if trajectory_distance > safe_trajectory_distance and static_obstacle_risk <= 0.0:
        return RiskAssessment(
            track_id=target.track_id,
            score=0.0,
            level=RiskLevel.SAFE,
            ttc_s=ttc,
            trajectory_distance_m=trajectory_distance,
            drac_mps2=drac,
            closing_speed_mps=closing_speed,
            motion_pattern=motion_pattern,
            static_obstacle_risk=static_obstacle_risk,
        )

    if motion_pattern == MotionPattern.MOVING_AWAY and static_obstacle_risk <= 0.0:
        return RiskAssessment(
            track_id=target.track_id,
            score=0.0,
            level=RiskLevel.SAFE,
            ttc_s=ttc,
            trajectory_distance_m=trajectory_distance,
            drac_mps2=drac,
            closing_speed_mps=closing_speed,
            motion_pattern=motion_pattern,
            static_obstacle_risk=static_obstacle_risk,
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
    velocity_confidence = clamp(target.velocity_confidence if hasattr(target, "velocity_confidence") else 1.0)
    distance_confidence = clamp(target.distance_confidence if hasattr(target, "distance_confidence") else 1.0)
    velocity_risk_scale = max(config.velocity_risk_confidence_floor, velocity_confidence)
    ttc_risk *= velocity_risk_scale
    drac_risk *= velocity_risk_scale
    closing_risk *= velocity_risk_scale
    static_obstacle_risk *= max(0.35, distance_confidence)

    weights = config.weights
    weighted_terms = [
        (weights.trajectory, trajectory_risk),
        (weights.ttc, ttc_risk),
        (weights.drac, drac_risk),
        (weights.closing, closing_risk),
    ]
    if static_obstacle_risk > 0.0:
        weighted_terms.append((weights.static_obstacle, static_obstacle_risk))
    total_weight = max(sum(weight for weight, _risk in weighted_terms), 1e-6)
    base_score = clamp(
        sum(weight * risk for weight, risk in weighted_terms)
        / total_weight
    )
    score = clamp(base_score * vehicle_risk_multiplier(target.class_name, config))
    score = _apply_motion_pattern_score_floor(
        score,
        target,
        motion_pattern,
        trajectory_distance,
        safe_trajectory_distance,
        ttc,
        config,
    )
    return RiskAssessment(
        track_id=target.track_id,
        score=score,
        level=risk_level_from_score(score),
        ttc_s=ttc,
        trajectory_distance_m=trajectory_distance,
        drac_mps2=drac,
        closing_speed_mps=closing_speed,
        motion_pattern=motion_pattern,
        static_obstacle_risk=static_obstacle_risk,
        trajectory_risk=trajectory_risk,
        ttc_risk=ttc_risk,
        drac_risk=drac_risk,
        closing_risk=closing_risk,
    )


class RiskModel:
    def __init__(self, config: RiskModelConfig | None = None) -> None:
        self.config = config or RiskModelConfig()

    def assess(self, target: TrackedObject) -> RiskAssessment:
        return assess_collision_risk(target, self.config)
