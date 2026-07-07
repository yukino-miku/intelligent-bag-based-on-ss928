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
    REMOTE_TRAFFIC = 5
    SIDE_STATIC = 6


class CorridorZone(IntEnum):
    UNKNOWN = 0
    IN_PATH = 1
    NEAR_SIDE = 2
    REMOTE_TRAFFIC = 3
    SIDE_STATIC = 4


RISK_LEVEL_SCORE_THRESHOLDS = {
    RiskLevel.SAFE: 0.0,
    RiskLevel.ATTENTION: 0.40,
    RiskLevel.CAUTION: 0.60,
    RiskLevel.DANGER: 0.70,
    RiskLevel.EMERGENCY: 0.80,
}


RISK_CAP_SCORE_MAX = {
    RiskLevel.SAFE: 0.0,
    RiskLevel.ATTENTION: 0.599,
    RiskLevel.CAUTION: 0.699,
    RiskLevel.DANGER: 0.799,
    RiskLevel.EMERGENCY: 1.0,
}


@dataclass(frozen=True)
class RiskWeights:
    trajectory: float = 4.0
    ttc: float = 2.0
    drac: float = 1.5
    closing: float = 1.5
    static_obstacle: float = 1.4


@dataclass(frozen=True)
class SeverityProfile:
    severity_class: str
    attention_time_s: float
    caution_time_s: float
    danger_time_s: float
    emergency_time_s: float
    warning_radius_m: float
    personal_space_radius_m: float
    low_speed_mps: float
    high_speed_mps: float


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
    cut_in_attention_score_floor: float = 0.40
    cut_in_caution_score_floor: float = 0.60
    near_static_attention_distance_m: float = 1.50
    near_static_caution_distance_m: float = 1.00
    near_static_danger_distance_m: float = 0.60
    near_static_attention_score_floor: float = 0.40
    near_static_caution_score_floor: float = 0.60
    near_static_danger_score_floor: float = 0.70
    personal_space_radius_m: float = 0.80
    warning_corridor_half_width_m: float = 1.20
    side_attention_corridor_half_width_m: float = 2.00
    near_side_corridor_half_width_m: float = 2.50
    in_path_depth_m: float = 5.00
    remote_traffic_min_distance_m: float = 6.00
    remote_traffic_lateral_m: float = 3.00
    cut_in_time_horizon_s: float = 3.50
    cpa_risk_time_horizon_s: float = 4.00
    remote_traffic_immediate_cpa_s: float = 2.00
    low_speed_cpa_time_horizon_s: float = 2.00
    min_cpa_speed_mps: float = 0.35
    static_motion_speed_mps: float = 0.35
    low_speed_bicycle_motorcycle_mps: float = 1.00
    low_speed_motor_vehicle_mps: float = 0.80
    high_speed_bicycle_motorcycle_mps: float = 3.00
    high_speed_motor_vehicle_mps: float = 2.00
    min_stable_track_age_frames: int = 3
    unstable_velocity_confidence: float = 0.45
    high_position_jitter_m: float = 0.75
    future_conflict_horizon_s: float = 6.00
    moving_away_trend_mps: float = 0.15
    approach_trend_mps: float = -0.15
    min_approach_consistency_for_high_risk: float = 0.50
    min_path_conflict_consistency_for_high_risk: float = 0.50
    low_distance_confidence: float = 0.35
    large_vehicle_profile: SeverityProfile = field(
        default_factory=lambda: SeverityProfile(
            severity_class="large_vehicle",
            attention_time_s=6.00,
            caution_time_s=4.80,
            danger_time_s=3.00,
            emergency_time_s=1.30,
            warning_radius_m=2.40,
            personal_space_radius_m=0.90,
            low_speed_mps=0.80,
            high_speed_mps=2.00,
        )
    )
    small_rider_profile: SeverityProfile = field(
        default_factory=lambda: SeverityProfile(
            severity_class="small_rider",
            attention_time_s=4.00,
            caution_time_s=3.00,
            danger_time_s=2.00,
            emergency_time_s=1.00,
            warning_radius_m=1.50,
            personal_space_radius_m=0.75,
            low_speed_mps=1.00,
            high_speed_mps=2.50,
        )
    )
    unknown_or_other_profile: SeverityProfile = field(
        default_factory=lambda: SeverityProfile(
            severity_class="unknown_or_other",
            attention_time_s=4.50,
            caution_time_s=3.20,
            danger_time_s=2.20,
            emergency_time_s=1.10,
            warning_radius_m=1.80,
            personal_space_radius_m=0.80,
            low_speed_mps=0.80,
            high_speed_mps=2.00,
        )
    )
    vehicle_risk_multipliers: dict[str, float] = field(
        default_factory=lambda: DEFAULT_VEHICLE_RISK_MULTIPLIERS.copy()
    )
    weights: RiskWeights = field(default_factory=RiskWeights)


@dataclass(frozen=True)
class CpaMetrics:
    time_s: float | None
    distance_m: float | None
    valid: bool


@dataclass(frozen=True)
class FutureConflict:
    moving_away: bool = False
    approaching: bool = False
    will_enter_personal_space: bool = False
    will_enter_warning_corridor: bool = False
    personal_entry_time_s: float | None = None
    corridor_entry_time_s: float | None = None
    min_future_distance_m: float | None = None
    path_conflict: bool = False
    conflict_reason: str = "none"


@dataclass(frozen=True)
class RiskAssessment:
    track_id: int
    score: float
    level: RiskLevel
    ttc_s: float | None
    trajectory_distance_m: float | None
    drac_mps2: float
    closing_speed_mps: float
    visual_level: RiskLevel | None = None
    haptic_level: RiskLevel | None = None
    motion_pattern: MotionPattern = MotionPattern.STATIC_OR_UNCERTAIN
    cpa_time_s: float | None = None
    cpa_distance_m: float | None = None
    cpa_valid: bool = False
    corridor_zone: CorridorZone = CorridorZone.UNKNOWN
    risk_cap_reason: str = "none"
    moving_away: bool = False
    approaching: bool = False
    path_conflict: bool = False
    will_enter_personal_space: bool = False
    will_enter_warning_corridor: bool = False
    personal_entry_time_s: float | None = None
    corridor_entry_time_s: float | None = None
    min_future_distance_m: float | None = None
    conflict_reason: str = "none"
    severity_class: str = "unknown_or_other"
    warning_action: str = "none"
    warning_time_horizon_s: float = 0.0
    warning_radius_m: float = 0.0
    risk_action_reason: str = "none"
    ignored_reason: str = ""
    static_obstacle_risk: float = 0.0
    trajectory_risk: float = 0.0
    ttc_risk: float = 0.0
    drac_risk: float = 0.0
    closing_risk: float = 0.0

    def __post_init__(self) -> None:
        if self.visual_level is None:
            object.__setattr__(self, "visual_level", self.level)
        if self.haptic_level is None:
            object.__setattr__(self, "haptic_level", self.level)


MOTOR_VEHICLE_CLASSES = {"car", "motorcycle", "truck", "bus"}
LARGE_MOTOR_VEHICLE_CLASSES = {"car", "truck", "bus"}
SMALL_RIDER_CLASSES = {"bicycle", "motorcycle"}


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


def warning_action_for_level(level: RiskLevel) -> str:
    return {
        RiskLevel.SAFE: "none",
        RiskLevel.ATTENTION: "short_weak_pulse",
        RiskLevel.CAUTION: "medium_interval_pulse",
        RiskLevel.DANGER: "strong_fast_pulse",
        RiskLevel.EMERGENCY: "continuous_high_frequency",
    }[level]


def severity_profile_for_class(class_name: str, config: RiskModelConfig) -> SeverityProfile:
    if class_name in LARGE_MOTOR_VEHICLE_CLASSES:
        return config.large_vehicle_profile
    if class_name in SMALL_RIDER_CLASSES:
        return config.small_rider_profile
    return config.unknown_or_other_profile


def trajectory_safe_distance_threshold_m(class_name: str, config: RiskModelConfig) -> float:
    if class_name == "bicycle":
        return config.bicycle_safe_trajectory_distance_m
    if class_name in MOTOR_VEHICLE_CLASSES:
        return config.motor_vehicle_safe_trajectory_distance_m
    return config.motor_vehicle_safe_trajectory_distance_m


def low_speed_threshold_mps(class_name: str, config: RiskModelConfig) -> float:
    return severity_profile_for_class(class_name, config).low_speed_mps


def high_speed_threshold_mps(class_name: str, config: RiskModelConfig) -> float:
    return severity_profile_for_class(class_name, config).high_speed_mps


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


def closest_point_of_approach_m(
    x_m: float,
    z_m: float,
    vx_mps: float,
    vz_mps: float,
    min_speed_mps: float = 0.35,
) -> CpaMetrics:
    speed_sq = vx_mps * vx_mps + vz_mps * vz_mps
    if speed_sq <= min_speed_mps * min_speed_mps:
        return CpaMetrics(time_s=None, distance_m=None, valid=False)

    t_cpa = -((x_m * vx_mps + z_m * vz_mps) / speed_sq)
    if t_cpa <= 0.0:
        return CpaMetrics(time_s=t_cpa, distance_m=math.hypot(x_m, z_m), valid=False)

    closest_x = x_m + vx_mps * t_cpa
    closest_z = z_m + vz_mps * t_cpa
    return CpaMetrics(time_s=t_cpa, distance_m=math.hypot(closest_x, closest_z), valid=True)


def time_to_enter_corridor(
    x_m: float,
    z_m: float,
    vx_mps: float,
    vz_mps: float,
    half_width_m: float,
    depth_m: float,
    horizon_s: float,
) -> float | None:
    def axis_interval(position: float, velocity: float, lower: float, upper: float) -> tuple[float, float] | None:
        if abs(velocity) <= 1e-6:
            if lower <= position <= upper:
                return -math.inf, math.inf
            return None
        t1 = (lower - position) / velocity
        t2 = (upper - position) / velocity
        return min(t1, t2), max(t1, t2)

    x_interval = axis_interval(x_m, vx_mps, -half_width_m, half_width_m)
    z_interval = axis_interval(z_m, vz_mps, 0.0, depth_m)
    if x_interval is None or z_interval is None:
        return None

    enter_s = max(0.0, x_interval[0], z_interval[0])
    exit_s = min(horizon_s, x_interval[1], z_interval[1])
    if enter_s <= exit_s:
        return enter_s
    return None


def _time_to_enter_radius(
    x_m: float,
    z_m: float,
    vx_mps: float,
    vz_mps: float,
    radius_m: float,
    horizon_s: float,
) -> float | None:
    if math.hypot(x_m, z_m) <= radius_m:
        return 0.0

    speed_sq = vx_mps * vx_mps + vz_mps * vz_mps
    if speed_sq <= 1e-8:
        return None

    b = 2.0 * (x_m * vx_mps + z_m * vz_mps)
    c = x_m * x_m + z_m * z_m - radius_m * radius_m
    discriminant = b * b - 4.0 * speed_sq * c
    if discriminant < 0.0:
        return None

    sqrt_discriminant = math.sqrt(discriminant)
    t1 = (-b - sqrt_discriminant) / (2.0 * speed_sq)
    t2 = (-b + sqrt_discriminant) / (2.0 * speed_sq)
    enter_s = max(0.0, min(t1, t2))
    exit_s = max(t1, t2)
    if enter_s <= exit_s and enter_s <= horizon_s and exit_s >= 0.0:
        return enter_s
    return None


def future_conflict_for_target(
    target: TrackedObject,
    profile: SeverityProfile,
    cpa: CpaMetrics,
    config: RiskModelConfig,
) -> FutureConflict:
    point = target.ground_point
    if point is None or target.distance_m is None:
        return FutureConflict(conflict_reason="no_ground_point")

    horizon_s = max(profile.attention_time_s, config.future_conflict_horizon_s)
    speed_mps = math.hypot(target.vx_mps, target.vz_mps)
    dot_pv = point.x_m * target.vx_mps + point.z_m * target.vz_mps
    current_inside_personal = target.distance_m <= profile.personal_space_radius_m
    enough_speed = speed_mps >= config.min_cpa_speed_mps
    cpa_time = cpa.time_s
    cpa_distance = cpa.distance_m

    distance_trend_mps = float(getattr(target, "distance_trend_mps", 0.0))
    approach_consistency = float(getattr(target, "approach_consistency", 0.0))
    trend_moving_away = distance_trend_mps >= config.moving_away_trend_mps
    trend_approaching = distance_trend_mps <= config.approach_trend_mps

    personal_entry_time_s = _time_to_enter_radius(
        point.x_m,
        point.z_m,
        target.vx_mps,
        target.vz_mps,
        profile.personal_space_radius_m,
        horizon_s,
    )
    corridor_entry_time_s = time_to_enter_corridor(
        point.x_m,
        point.z_m,
        target.vx_mps,
        target.vz_mps,
        config.warning_corridor_half_width_m,
        config.in_path_depth_m,
        horizon_s,
    )

    moving_away_candidate = False
    if enough_speed and dot_pv >= 0.0:
        moving_away_candidate = True
    if trend_moving_away and (not cpa.valid or (cpa_time is not None and cpa_time <= 0.0)):
        moving_away_candidate = True

    will_enter_personal = personal_entry_time_s is not None
    will_enter_corridor = corridor_entry_time_s is not None
    if (
        will_enter_corridor
        and corridor_entry_time_s is not None
        and corridor_entry_time_s <= 1e-6
        and moving_away_candidate
        and not will_enter_personal
    ):
        will_enter_corridor = False
        corridor_entry_time_s = None
    path_conflict = current_inside_personal or will_enter_personal or will_enter_corridor

    if cpa.valid and cpa_time is not None and cpa_distance is not None and 0.0 <= cpa_time <= horizon_s:
        min_future_distance_m = cpa_distance
    elif current_inside_personal:
        min_future_distance_m = target.distance_m
    else:
        future_x = point.x_m + target.vx_mps * horizon_s
        future_z = point.z_m + target.vz_mps * horizon_s
        min_future_distance_m = min(target.distance_m, math.hypot(future_x, future_z))

    moving_away = moving_away_candidate
    if current_inside_personal or path_conflict:
        moving_away = False

    approaching = False
    if enough_speed and dot_pv < 0.0:
        approaching = True
    if trend_approaching:
        approaching = True
    if enough_speed and approach_consistency >= config.min_approach_consistency_for_high_risk:
        approaching = True
    if moving_away and not path_conflict:
        approaching = False

    if current_inside_personal:
        reason = "current_personal_space"
    elif will_enter_personal:
        reason = "personal_space_entry"
    elif will_enter_corridor:
        reason = "warning_corridor_entry"
    elif moving_away:
        reason = "moving_away_no_future_conflict"
    else:
        reason = "no_corridor_entry"

    return FutureConflict(
        moving_away=moving_away,
        approaching=approaching,
        will_enter_personal_space=will_enter_personal,
        will_enter_warning_corridor=will_enter_corridor,
        personal_entry_time_s=personal_entry_time_s,
        corridor_entry_time_s=corridor_entry_time_s,
        min_future_distance_m=min_future_distance_m,
        path_conflict=path_conflict,
        conflict_reason=reason,
    )


def motion_pattern_name(pattern: MotionPattern) -> str:
    return {
        MotionPattern.STATIC_OR_UNCERTAIN: "STATIC",
        MotionPattern.MOVING_AWAY: "AWAY",
        MotionPattern.LATERAL_CUT_IN: "CUTIN",
        MotionPattern.HEAD_ON_OR_CLOSING: "CLOSING",
        MotionPattern.NEAR_STATIC_OBSTACLE: "NEAR",
        MotionPattern.REMOTE_TRAFFIC: "REMOTE",
        MotionPattern.SIDE_STATIC: "SIDE_STATIC",
    }[pattern]


def corridor_zone_name(zone: CorridorZone) -> str:
    return {
        CorridorZone.UNKNOWN: "UNK",
        CorridorZone.IN_PATH: "PATH",
        CorridorZone.NEAR_SIDE: "SIDE",
        CorridorZone.REMOTE_TRAFFIC: "REMOTE",
        CorridorZone.SIDE_STATIC: "SIDE_STATIC",
    }[zone]


def classify_corridor_zone(target: TrackedObject, config: RiskModelConfig) -> CorridorZone:
    point = target.ground_point
    if point is None or point.z_m <= 0.0:
        return CorridorZone.UNKNOWN

    abs_x = abs(point.x_m)
    z_m = point.z_m
    if abs_x < config.warning_corridor_half_width_m and z_m <= config.in_path_depth_m:
        return CorridorZone.IN_PATH
    if (
        target.speed_mps <= config.static_motion_speed_mps
        and abs_x >= config.warning_corridor_half_width_m
        and z_m <= config.remote_traffic_min_distance_m
    ):
        return CorridorZone.SIDE_STATIC
    if abs_x > config.remote_traffic_lateral_m or z_m > config.remote_traffic_min_distance_m:
        return CorridorZone.REMOTE_TRAFFIC
    if abs_x < config.near_side_corridor_half_width_m and z_m <= config.in_path_depth_m:
        return CorridorZone.NEAR_SIDE
    return CorridorZone.UNKNOWN


def _cpa_enters_radius(cpa: CpaMetrics, radius_m: float, horizon_s: float) -> bool:
    return (
        cpa.valid
        and cpa.time_s is not None
        and cpa.distance_m is not None
        and 0.0 < cpa.time_s <= horizon_s
        and cpa.distance_m <= radius_m
    )


def _target_motion_is_unstable(target: TrackedObject, config: RiskModelConfig) -> bool:
    flags = set(getattr(target, "motion_quality_flags", ()))
    return (
        getattr(target, "track_age_frames", 1) < config.min_stable_track_age_frames
        or getattr(target, "velocity_confidence", 1.0) < config.unstable_velocity_confidence
        or getattr(target, "position_jitter_m", 0.0) >= config.high_position_jitter_m
        or bool(flags.intersection({"unstable_velocity", "velocity_reversal", "position_jitter", "speed_spike"}))
    )


def classify_motion_pattern(
    target: TrackedObject,
    trajectory_distance: float,
    closing_speed_mps: float,
    config: RiskModelConfig,
    cpa: CpaMetrics | None = None,
    corridor_zone: CorridorZone | None = None,
    future_conflict: FutureConflict | None = None,
) -> MotionPattern:
    cpa = cpa or closest_point_of_approach_m(
        target.ground_point.x_m if target.ground_point else 0.0,
        target.ground_point.z_m if target.ground_point else 0.0,
        target.vx_mps,
        target.vz_mps,
        config.min_cpa_speed_mps,
    )
    corridor_zone = corridor_zone or classify_corridor_zone(target, config)
    distance_m = target.distance_m
    speed_mps = target.speed_mps
    path_conflict = bool(future_conflict.path_conflict) if future_conflict is not None else False
    moving_away = bool(future_conflict.moving_away) if future_conflict is not None else False
    approach_consistency = float(getattr(target, "approach_consistency", 0.0))

    if distance_m is not None and distance_m <= config.near_static_distance_m and speed_mps <= config.static_motion_speed_mps:
        return MotionPattern.NEAR_STATIC_OBSTACLE
    if corridor_zone == CorridorZone.SIDE_STATIC:
        return MotionPattern.SIDE_STATIC

    if future_conflict is not None:
        personal_cpa_soon = (
            future_conflict.personal_entry_time_s is not None
            and future_conflict.personal_entry_time_s <= config.remote_traffic_immediate_cpa_s
        )
    else:
        personal_cpa_soon = _cpa_enters_radius(
            cpa,
            config.personal_space_radius_m,
            config.remote_traffic_immediate_cpa_s,
        )
    corridor_entry_soon = (
        future_conflict.will_enter_warning_corridor
        if future_conflict is not None
        else _cpa_enters_radius(cpa, config.warning_corridor_half_width_m, config.cut_in_time_horizon_s)
    )
    if moving_away and not path_conflict:
        return MotionPattern.MOVING_AWAY
    if corridor_zone == CorridorZone.REMOTE_TRAFFIC and not path_conflict:
        return MotionPattern.REMOTE_TRAFFIC

    if _target_motion_is_unstable(target, config) and not personal_cpa_soon:
        return MotionPattern.STATIC_OR_UNCERTAIN

    point = target.ground_point
    if point is None:
        return MotionPattern.STATIC_OR_UNCERTAIN

    moving_toward_center = point.x_m * target.vx_mps < 0.0
    if (
        path_conflict
        and (personal_cpa_soon or corridor_entry_soon)
        and abs(point.x_m) >= config.warning_corridor_half_width_m
        and moving_toward_center
        and abs(target.vx_mps) >= config.lateral_cut_in_speed_mps
        and approach_consistency >= config.min_approach_consistency_for_high_risk
    ):
        return MotionPattern.LATERAL_CUT_IN

    if closing_speed_mps >= config.min_closing_speed_mps and (
        path_conflict
        and approach_consistency >= config.min_approach_consistency_for_high_risk
        and (corridor_zone == CorridorZone.IN_PATH or personal_cpa_soon or corridor_entry_soon)
    ):
        return MotionPattern.HEAD_ON_OR_CLOSING

    if speed_mps >= config.static_motion_speed_mps and closing_speed_mps < config.min_closing_speed_mps:
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


def _cpa_distance_risk(cpa: CpaMetrics, config: RiskModelConfig) -> float:
    if (
        not cpa.valid
        or cpa.time_s is None
        or cpa.distance_m is None
        or cpa.time_s > config.cpa_risk_time_horizon_s
    ):
        return 0.0

    distance_risk = _trajectory_distance_risk(
        cpa.distance_m,
        config.warning_corridor_half_width_m,
        config.trajectory_risk_exponent,
    )
    if cpa.time_s <= config.cut_in_time_horizon_s:
        return distance_risk

    tail_window = max(config.cpa_risk_time_horizon_s - config.cut_in_time_horizon_s, 1e-6)
    time_scale = clamp((config.cpa_risk_time_horizon_s - cpa.time_s) / tail_window)
    return distance_risk * time_scale


def _near_static_obstacle_risk(distance_m: float | None, corridor_zone: CorridorZone, config: RiskModelConfig) -> float:
    if corridor_zone != CorridorZone.IN_PATH:
        return 0.0
    if distance_m is None or distance_m >= config.static_obstacle_risk_start_m:
        return 0.0
    risk_window = max(config.static_obstacle_risk_start_m - config.static_obstacle_emergency_m, 1e-6)
    normalized = clamp((distance_m - config.static_obstacle_emergency_m) / risk_window)
    return clamp(1.0 - normalized)


def _score_for_level_floor(level: RiskLevel) -> float:
    if level <= RiskLevel.SAFE:
        return 0.0
    return risk_score_threshold_for_level(level)


def _max_level(current: RiskLevel, candidate: RiskLevel) -> RiskLevel:
    return candidate if candidate > current else current


def _level_from_cpa_and_context(
    target: TrackedObject,
    profile: SeverityProfile,
    cpa: CpaMetrics,
    corridor_zone: CorridorZone,
    future_conflict: FutureConflict,
    closing_speed_mps: float,
    ttc_s: float | None,
    config: RiskModelConfig,
) -> tuple[RiskLevel, str]:
    distance_m = target.distance_m
    if distance_m is not None and distance_m <= profile.personal_space_radius_m:
        return RiskLevel.EMERGENCY, "current_personal_space"

    level = RiskLevel.SAFE
    reason = "score_terms"
    is_large_vehicle = profile.severity_class == "large_vehicle"
    is_small_rider = profile.severity_class == "small_rider"
    in_path = corridor_zone == CorridorZone.IN_PATH
    near_side = corridor_zone == CorridorZone.NEAR_SIDE
    stable_motion = not _target_motion_is_unstable(target, config)
    personal_entry_s = future_conflict.personal_entry_time_s
    corridor_entry_s = future_conflict.corridor_entry_time_s
    min_future_distance = future_conflict.min_future_distance_m

    if not future_conflict.path_conflict:
        if (
            future_conflict.approaching
            and min_future_distance is not None
            and min_future_distance <= profile.warning_radius_m
            and not future_conflict.moving_away
        ):
            return RiskLevel.ATTENTION, f"{profile.severity_class}_possible_future_relevance"
        return RiskLevel.SAFE, future_conflict.conflict_reason

    def time_leq(value: float | None, threshold: float) -> bool:
        return value is not None and value <= threshold

    if time_leq(personal_entry_s, profile.emergency_time_s):
        return RiskLevel.EMERGENCY, f"{profile.severity_class}_emergency_personal_entry"

    if is_large_vehicle:
        if time_leq(personal_entry_s, profile.danger_time_s):
            return RiskLevel.DANGER, "large_vehicle_personal_path_conflict"
        if (
            in_path
            and time_leq(ttc_s, profile.danger_time_s)
            and closing_speed_mps >= config.min_closing_speed_mps
            and min_future_distance is not None
            and min_future_distance <= config.warning_corridor_half_width_m
        ):
            return RiskLevel.DANGER, "large_vehicle_in_path_closing"
        if time_leq(personal_entry_s, profile.caution_time_s):
            return RiskLevel.CAUTION, "large_vehicle_personal_path_conflict"
        if (
            time_leq(corridor_entry_s, profile.caution_time_s)
            and (in_path or corridor_zone == CorridorZone.REMOTE_TRAFFIC)
            and min_future_distance is not None
            and min_future_distance <= profile.warning_radius_m
        ):
            return RiskLevel.CAUTION, "large_vehicle_corridor_path_conflict"
        if time_leq(personal_entry_s, profile.attention_time_s) or time_leq(corridor_entry_s, profile.attention_time_s):
            return RiskLevel.ATTENTION, "large_vehicle_early_future_conflict"
        if in_path and closing_speed_mps >= config.min_closing_speed_mps:
            return RiskLevel.ATTENTION, "large_vehicle_in_path_closing"
        return level, reason

    if is_small_rider:
        high_speed = target.speed_mps >= profile.high_speed_mps
        low_speed = target.speed_mps < profile.low_speed_mps
        if time_leq(personal_entry_s, profile.danger_time_s) and high_speed:
            return RiskLevel.DANGER, "small_rider_high_speed_personal_conflict"
        if time_leq(personal_entry_s, profile.caution_time_s) and (stable_motion or in_path or near_side):
            return RiskLevel.CAUTION, "small_rider_personal_conflict"
        if (
            time_leq(corridor_entry_s, profile.caution_time_s)
            and in_path
            and not low_speed
            and min_future_distance is not None
            and min_future_distance <= config.warning_corridor_half_width_m
        ):
            return RiskLevel.CAUTION, "small_rider_corridor_conflict"
        if time_leq(personal_entry_s, profile.attention_time_s) and not low_speed:
            return RiskLevel.ATTENTION, "small_rider_possible_personal_conflict"
        return level, reason

    if time_leq(personal_entry_s, profile.danger_time_s):
        return RiskLevel.DANGER, "unknown_personal_conflict"
    if time_leq(personal_entry_s, profile.caution_time_s) or (
        time_leq(corridor_entry_s, profile.caution_time_s)
        and min_future_distance is not None
        and min_future_distance <= config.warning_corridor_half_width_m
    ):
        return RiskLevel.CAUTION, "unknown_path_conflict"
    if time_leq(personal_entry_s, profile.attention_time_s) or time_leq(corridor_entry_s, profile.attention_time_s):
        return RiskLevel.ATTENTION, "unknown_possible_conflict"
    return level, reason


def _apply_motion_pattern_score_floor(
    score: float,
    target: TrackedObject,
    motion_pattern: MotionPattern,
    cpa: CpaMetrics,
    corridor_zone: CorridorZone,
    future_conflict: FutureConflict,
    config: RiskModelConfig,
) -> float:
    if not future_conflict.path_conflict:
        return score

    if (
        motion_pattern == MotionPattern.LATERAL_CUT_IN
        and future_conflict.corridor_entry_time_s is not None
        and future_conflict.corridor_entry_time_s <= config.cut_in_time_horizon_s
        and future_conflict.min_future_distance_m is not None
        and future_conflict.min_future_distance_m <= config.warning_corridor_half_width_m
        and not _target_motion_is_unstable(target, config)
    ):
        score = max(score, config.cut_in_attention_score_floor)
        if (
            future_conflict.personal_entry_time_s is not None
            and future_conflict.personal_entry_time_s <= config.remote_traffic_immediate_cpa_s
        ):
            score = max(score, config.cut_in_caution_score_floor)
        if (
            target.class_name in SMALL_RIDER_CLASSES
            and target.speed_mps >= high_speed_threshold_mps(target.class_name, config)
            and future_conflict.personal_entry_time_s is not None
            and future_conflict.personal_entry_time_s <= 1.25
        ):
            score = max(score, risk_score_threshold_for_level(RiskLevel.DANGER))

    if motion_pattern == MotionPattern.NEAR_STATIC_OBSTACLE and target.distance_m is not None:
        if target.distance_m <= config.near_static_danger_distance_m:
            score = max(score, config.near_static_danger_score_floor)
        elif target.distance_m <= config.near_static_caution_distance_m:
            score = max(score, config.near_static_caution_score_floor)
        elif target.distance_m <= config.near_static_attention_distance_m:
            score = max(score, config.near_static_attention_score_floor)

    if (
        corridor_zone == CorridorZone.IN_PATH
        and future_conflict.corridor_entry_time_s is not None
        and future_conflict.corridor_entry_time_s <= config.caution_ttc_s
        and future_conflict.min_future_distance_m is not None
        and future_conflict.min_future_distance_m <= config.warning_corridor_half_width_m
    ):
        score = max(score, risk_score_threshold_for_level(RiskLevel.ATTENTION))
        if (
            future_conflict.personal_entry_time_s is not None
            or (
                target.class_name in LARGE_MOTOR_VEHICLE_CLASSES
                and target.speed_mps >= high_speed_threshold_mps(target.class_name, config)
                and future_conflict.corridor_entry_time_s <= config.danger_ttc_s
            )
        ):
            score = max(score, risk_score_threshold_for_level(RiskLevel.CAUTION))

    if (
        target.class_name in LARGE_MOTOR_VEHICLE_CLASSES
        and corridor_zone == CorridorZone.IN_PATH
        and future_conflict.personal_entry_time_s is not None
        and future_conflict.personal_entry_time_s <= config.remote_traffic_immediate_cpa_s
        and target.speed_mps >= high_speed_threshold_mps(target.class_name, config)
    ):
        score = max(score, risk_score_threshold_for_level(RiskLevel.DANGER))

    if (
        future_conflict.personal_entry_time_s is not None
        and future_conflict.personal_entry_time_s <= 0.80
        and future_conflict.min_future_distance_m is not None
        and future_conflict.min_future_distance_m <= config.personal_space_radius_m * 0.50
    ):
        score = max(score, risk_score_threshold_for_level(RiskLevel.EMERGENCY))

    if target.distance_m is not None and target.distance_m <= config.personal_space_radius_m:
        score = max(score, risk_score_threshold_for_level(RiskLevel.EMERGENCY))

    return clamp(score)


def _cap_score(score: float, cap_level: RiskLevel) -> float:
    return min(score, RISK_CAP_SCORE_MAX[cap_level])


def _contextual_risk_cap(
    target: TrackedObject,
    corridor_zone: CorridorZone,
    cpa: CpaMetrics,
    future_conflict: FutureConflict,
    profile: SeverityProfile,
    action_level: RiskLevel,
    config: RiskModelConfig,
) -> tuple[RiskLevel | None, str]:
    cap_level: RiskLevel | None = None
    reasons: list[str] = []

    def add_cap(level: RiskLevel, reason: str) -> None:
        nonlocal cap_level
        if cap_level is None or level < cap_level:
            cap_level = level
        reasons.append(reason)

    distance_m = target.distance_m
    current_inside_personal = distance_m is not None and distance_m <= profile.personal_space_radius_m
    enters_personal_immediately = (
        future_conflict.personal_entry_time_s is not None
        and future_conflict.personal_entry_time_s <= min(config.remote_traffic_immediate_cpa_s, profile.danger_time_s)
    )
    enters_corridor_soon = (
        future_conflict.corridor_entry_time_s is not None
        and future_conflict.corridor_entry_time_s <= profile.attention_time_s
    )

    if future_conflict.moving_away and not future_conflict.path_conflict and not current_inside_personal:
        add_cap(RiskLevel.SAFE, "moving_away_no_future_conflict")

    if not future_conflict.path_conflict and not current_inside_personal:
        add_cap(RiskLevel.ATTENTION, "no_corridor_entry")

    if corridor_zone == CorridorZone.REMOTE_TRAFFIC and not current_inside_personal:
        large_vehicle_path_conflict = (
            profile.severity_class == "large_vehicle"
            and action_level >= RiskLevel.ATTENTION
            and future_conflict.path_conflict
            and enters_corridor_soon
            and not _target_motion_is_unstable(target, config)
        )
        if large_vehicle_path_conflict:
            reasons.append("remote_large_vehicle_path_conflict")
        elif future_conflict.path_conflict and enters_personal_immediately and not _target_motion_is_unstable(target, config):
            add_cap(RiskLevel.ATTENTION, "remote_traffic_requires_confirmation")
        else:
            add_cap(
                RiskLevel.ATTENTION if future_conflict.path_conflict and enters_corridor_soon else RiskLevel.SAFE,
                "remote_traffic_no_path_conflict",
            )

    if corridor_zone == CorridorZone.SIDE_STATIC and not current_inside_personal:
        add_cap(RiskLevel.SAFE, "side_static")

    low_speed = target.speed_mps <= low_speed_threshold_mps(target.class_name, config)
    if low_speed and not current_inside_personal:
        enters_personal_soon = (
            future_conflict.personal_entry_time_s is not None
            and future_conflict.personal_entry_time_s <= config.low_speed_cpa_time_horizon_s
        )
        if not (corridor_zone == CorridorZone.IN_PATH and enters_personal_soon):
            distant_low_speed_small_rider = (
                profile.severity_class == "small_rider"
                and (
                    future_conflict.personal_entry_time_s is None
                    or future_conflict.personal_entry_time_s > profile.attention_time_s
                )
                and not (
                    corridor_zone == CorridorZone.IN_PATH
                    and distance_m is not None
                    and distance_m <= config.near_static_attention_distance_m
                )
            )
            add_cap(RiskLevel.SAFE if distant_low_speed_small_rider else RiskLevel.ATTENTION, "low_speed_non_path")

    if _target_motion_is_unstable(target, config) and not current_inside_personal:
        add_cap(RiskLevel.ATTENTION, "unstable_track")

    truncated_edges = {
        edge
        for edge in str(getattr(target, "bbox_truncated_edges", "")).split("|")
        if edge
    }
    edge_truncated = bool(truncated_edges.intersection({"left", "right"}))
    if edge_truncated and not current_inside_personal:
        low_quality_edge = (
            getattr(target, "track_age_frames", 1) < config.min_stable_track_age_frames
            or getattr(target, "velocity_confidence", 1.0) < 0.55
            or getattr(target, "distance_confidence", 1.0) < 0.55
            or getattr(target, "position_jitter_m", 0.0) >= config.high_position_jitter_m
        )
        if low_quality_edge:
            add_cap(RiskLevel.ATTENTION, "edge_truncated_cap")

    if (
        future_conflict.path_conflict
        and not current_inside_personal
        and action_level > RiskLevel.ATTENTION
        and float(getattr(target, "approach_consistency", 0.0)) < config.min_approach_consistency_for_high_risk
        and float(getattr(target, "path_conflict_consistency", 0.0)) < config.min_path_conflict_consistency_for_high_risk
    ):
        add_cap(RiskLevel.ATTENTION, "unstable_single_frame_cpa")

    if getattr(target, "distance_confidence", 1.0) < config.low_distance_confidence and not current_inside_personal:
        add_cap(RiskLevel.ATTENTION, "low_distance_confidence")

    return cap_level, "|".join(dict.fromkeys(reasons)) if reasons else "none"


def _apply_contextual_cap(score: float, cap_level: RiskLevel | None) -> float:
    if cap_level is None:
        return score
    return _cap_score(score, cap_level)


def _haptic_level_for_context(
    level: RiskLevel,
    target: TrackedObject,
    future_conflict: FutureConflict,
    profile: SeverityProfile,
    cap_reason: str,
    config: RiskModelConfig,
) -> RiskLevel:
    if level <= RiskLevel.SAFE:
        return RiskLevel.SAFE
    if getattr(target, "ignored_reason", ""):
        return RiskLevel.SAFE

    distance_m = target.distance_m
    current_inside_personal = distance_m is not None and distance_m <= profile.personal_space_radius_m
    if current_inside_personal:
        return level
    if future_conflict.moving_away and not future_conflict.path_conflict:
        return RiskLevel.SAFE
    if not future_conflict.path_conflict:
        return RiskLevel.SAFE

    cap_reasons = {reason for reason in cap_reason.split("|") if reason and reason != "none"}
    if cap_reasons.intersection(
        {
            "edge_truncated_cap",
            "unstable_single_frame_cpa",
            "low_distance_confidence",
            "unstable_track",
        }
    ):
        return RiskLevel.SAFE if level <= RiskLevel.ATTENTION else RiskLevel.ATTENTION

    approach_consistency = float(getattr(target, "approach_consistency", 0.0))
    path_conflict_consistency = float(getattr(target, "path_conflict_consistency", 0.0))
    stable_path_relevance = (
        approach_consistency >= config.min_approach_consistency_for_high_risk
        or path_conflict_consistency >= config.min_path_conflict_consistency_for_high_risk
    )
    if not stable_path_relevance:
        return RiskLevel.SAFE if level <= RiskLevel.ATTENTION else RiskLevel.ATTENTION

    return level


def _empty_assessment(
    target: TrackedObject,
    cpa: CpaMetrics | None = None,
    corridor_zone: CorridorZone = CorridorZone.UNKNOWN,
    risk_cap_reason: str = "none",
    profile: SeverityProfile | None = None,
    future_conflict: FutureConflict | None = None,
) -> RiskAssessment:
    cpa = cpa or CpaMetrics(None, None, False)
    future_conflict = future_conflict or FutureConflict(conflict_reason="no_ground_point")
    severity_class = profile.severity_class if profile is not None else "unknown_or_other"
    warning_time_horizon_s = profile.attention_time_s if profile is not None else 0.0
    warning_radius_m = profile.warning_radius_m if profile is not None else 0.0
    return RiskAssessment(
        track_id=target.track_id,
        score=0.0,
        level=RiskLevel.SAFE,
        ttc_s=None,
        trajectory_distance_m=None,
        drac_mps2=0.0,
        closing_speed_mps=0.0,
        motion_pattern=MotionPattern.STATIC_OR_UNCERTAIN,
        cpa_time_s=cpa.time_s,
        cpa_distance_m=cpa.distance_m,
        cpa_valid=cpa.valid,
        corridor_zone=corridor_zone,
        risk_cap_reason=risk_cap_reason,
        moving_away=future_conflict.moving_away,
        approaching=future_conflict.approaching,
        path_conflict=future_conflict.path_conflict,
        will_enter_personal_space=future_conflict.will_enter_personal_space,
        will_enter_warning_corridor=future_conflict.will_enter_warning_corridor,
        personal_entry_time_s=future_conflict.personal_entry_time_s,
        corridor_entry_time_s=future_conflict.corridor_entry_time_s,
        min_future_distance_m=future_conflict.min_future_distance_m,
        conflict_reason=future_conflict.conflict_reason,
        severity_class=severity_class,
        warning_action=warning_action_for_level(RiskLevel.SAFE),
        warning_time_horizon_s=warning_time_horizon_s,
        warning_radius_m=warning_radius_m,
        risk_action_reason="no_ground_point",
        ignored_reason=getattr(target, "ignored_reason", ""),
    )


def assess_collision_risk(
    target: TrackedObject,
    config: RiskModelConfig | None = None,
) -> RiskAssessment:
    config = config or RiskModelConfig()
    profile = severity_profile_for_class(target.class_name, config)
    point = target.ground_point
    if point is None or target.distance_m is None:
        return _empty_assessment(target, profile=profile)

    trajectory_distance = trajectory_distance_m(point.x_m, point.z_m, target.vx_mps, target.vz_mps)
    cpa = closest_point_of_approach_m(
        point.x_m,
        point.z_m,
        target.vx_mps,
        target.vz_mps,
        config.min_cpa_speed_mps,
    )
    corridor_zone = classify_corridor_zone(target, config)
    future_conflict = future_conflict_for_target(target, profile, cpa, config)
    closing_speed = radial_closing_speed_mps(point.x_m, point.z_m, target.vx_mps, target.vz_mps)
    ttc = time_to_collision_s(target.distance_m, closing_speed)
    drac = decel_required_mps2(target.distance_m, closing_speed)
    motion_pattern = classify_motion_pattern(
        target,
        trajectory_distance,
        closing_speed,
        config,
        cpa=cpa,
        corridor_zone=corridor_zone,
        future_conflict=future_conflict,
    )
    static_obstacle_risk = _near_static_obstacle_risk(target.distance_m, corridor_zone, config)
    action_level, action_reason = _level_from_cpa_and_context(
        target,
        profile,
        cpa,
        corridor_zone,
        future_conflict,
        closing_speed,
        ttc,
        config,
    )
    cap_level, cap_reason = _contextual_risk_cap(
        target,
        corridor_zone,
        cpa,
        future_conflict,
        profile,
        action_level,
        config,
    )

    ttc_safe = ttc is not None and ttc > config.safe_ttc_s
    cpa_in_risk_window = (
        cpa.valid
        and cpa.time_s is not None
        and cpa.distance_m is not None
        and cpa.time_s <= config.cpa_risk_time_horizon_s
        and cpa.distance_m <= config.warning_corridor_half_width_m
    )
    if (
        ttc_safe
        and not cpa_in_risk_window
        and static_obstacle_risk <= 0.0
        and action_level <= RiskLevel.SAFE
        and not future_conflict.path_conflict
    ):
        return RiskAssessment(
            track_id=target.track_id,
            score=0.0,
            level=RiskLevel.SAFE,
            ttc_s=ttc,
            trajectory_distance_m=trajectory_distance,
            drac_mps2=drac,
            closing_speed_mps=closing_speed,
            motion_pattern=motion_pattern,
            cpa_time_s=cpa.time_s,
            cpa_distance_m=cpa.distance_m,
            cpa_valid=cpa.valid,
            corridor_zone=corridor_zone,
            risk_cap_reason=cap_reason,
            moving_away=future_conflict.moving_away,
            approaching=future_conflict.approaching,
            path_conflict=future_conflict.path_conflict,
            will_enter_personal_space=future_conflict.will_enter_personal_space,
            will_enter_warning_corridor=future_conflict.will_enter_warning_corridor,
            personal_entry_time_s=future_conflict.personal_entry_time_s,
            corridor_entry_time_s=future_conflict.corridor_entry_time_s,
            min_future_distance_m=future_conflict.min_future_distance_m,
            conflict_reason=future_conflict.conflict_reason,
            severity_class=profile.severity_class,
            warning_action=warning_action_for_level(RiskLevel.SAFE),
            warning_time_horizon_s=profile.attention_time_s,
            warning_radius_m=profile.warning_radius_m,
            risk_action_reason=action_reason,
            static_obstacle_risk=static_obstacle_risk,
        )

    if (
        motion_pattern in (MotionPattern.MOVING_AWAY, MotionPattern.REMOTE_TRAFFIC, MotionPattern.SIDE_STATIC)
        and static_obstacle_risk <= 0.0
        and not future_conflict.will_enter_personal_space
        and not future_conflict.will_enter_warning_corridor
        and action_level <= RiskLevel.SAFE
    ):
        return RiskAssessment(
            track_id=target.track_id,
            score=0.0,
            level=RiskLevel.SAFE,
            ttc_s=ttc,
            trajectory_distance_m=trajectory_distance,
            drac_mps2=drac,
            closing_speed_mps=closing_speed,
            motion_pattern=motion_pattern,
            cpa_time_s=cpa.time_s,
            cpa_distance_m=cpa.distance_m,
            cpa_valid=cpa.valid,
            corridor_zone=corridor_zone,
            risk_cap_reason=cap_reason,
            moving_away=future_conflict.moving_away,
            approaching=future_conflict.approaching,
            path_conflict=future_conflict.path_conflict,
            will_enter_personal_space=future_conflict.will_enter_personal_space,
            will_enter_warning_corridor=future_conflict.will_enter_warning_corridor,
            personal_entry_time_s=future_conflict.personal_entry_time_s,
            corridor_entry_time_s=future_conflict.corridor_entry_time_s,
            min_future_distance_m=future_conflict.min_future_distance_m,
            conflict_reason=future_conflict.conflict_reason,
            severity_class=profile.severity_class,
            warning_action=warning_action_for_level(RiskLevel.SAFE),
            warning_time_horizon_s=profile.attention_time_s,
            warning_radius_m=profile.warning_radius_m,
            risk_action_reason=action_reason,
            static_obstacle_risk=static_obstacle_risk,
        )

    trajectory_risk = 0.0
    if future_conflict.path_conflict and future_conflict.min_future_distance_m is not None:
        trajectory_risk = _trajectory_distance_risk(
            future_conflict.min_future_distance_m,
            config.warning_corridor_half_width_m,
            config.trajectory_risk_exponent,
        )
    ttc_risk = _collision_time_risk(ttc, config)
    drac_risk = clamp(
        (drac - config.comfortable_decel_mps2)
        / max(config.emergency_decel_mps2 - config.comfortable_decel_mps2, 0.1)
    )
    closing_risk = clamp(closing_speed / config.max_closing_speed_mps)
    velocity_confidence = clamp(getattr(target, "velocity_confidence", 1.0))
    distance_confidence = clamp(getattr(target, "distance_confidence", 1.0))
    if _target_motion_is_unstable(target, config):
        velocity_confidence = min(velocity_confidence, 0.35)
    velocity_risk_scale = max(config.velocity_risk_confidence_floor, velocity_confidence)
    ttc_risk *= velocity_risk_scale
    drac_risk *= velocity_risk_scale
    closing_risk *= velocity_risk_scale
    if not future_conflict.path_conflict:
        ttc_risk = min(ttc_risk, risk_score_threshold_for_level(RiskLevel.ATTENTION))
        drac_risk = min(drac_risk, risk_score_threshold_for_level(RiskLevel.ATTENTION))
        closing_risk = min(closing_risk, risk_score_threshold_for_level(RiskLevel.ATTENTION))
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
    base_score = clamp(sum(weight * risk for weight, risk in weighted_terms) / total_weight)
    score = clamp(base_score * vehicle_risk_multiplier(target.class_name, config))
    score = _apply_motion_pattern_score_floor(
        score,
        target,
        motion_pattern,
        cpa,
        corridor_zone,
        future_conflict,
        config,
    )
    score = max(score, _score_for_level_floor(action_level))
    score = _apply_contextual_cap(score, cap_level)
    level = risk_level_from_score(score)
    risk_action_reason = action_reason
    if cap_level is not None and action_level > cap_level:
        risk_action_reason = f"{action_reason}|capped_to_{cap_level.name.lower()}"
    haptic_level = _haptic_level_for_context(level, target, future_conflict, profile, cap_reason, config)
    return RiskAssessment(
        track_id=target.track_id,
        score=score,
        level=level,
        ttc_s=ttc,
        trajectory_distance_m=trajectory_distance,
        drac_mps2=drac,
        closing_speed_mps=closing_speed,
        visual_level=level,
        haptic_level=haptic_level,
        motion_pattern=motion_pattern,
        cpa_time_s=cpa.time_s,
        cpa_distance_m=cpa.distance_m,
        cpa_valid=cpa.valid,
        corridor_zone=corridor_zone,
        risk_cap_reason=cap_reason,
        moving_away=future_conflict.moving_away,
        approaching=future_conflict.approaching,
        path_conflict=future_conflict.path_conflict,
        will_enter_personal_space=future_conflict.will_enter_personal_space,
        will_enter_warning_corridor=future_conflict.will_enter_warning_corridor,
        personal_entry_time_s=future_conflict.personal_entry_time_s,
        corridor_entry_time_s=future_conflict.corridor_entry_time_s,
        min_future_distance_m=future_conflict.min_future_distance_m,
        conflict_reason=future_conflict.conflict_reason,
        severity_class=profile.severity_class,
        warning_action=warning_action_for_level(haptic_level),
        warning_time_horizon_s=profile.attention_time_s,
        warning_radius_m=profile.warning_radius_m,
        risk_action_reason=risk_action_reason,
        ignored_reason=getattr(target, "ignored_reason", ""),
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
