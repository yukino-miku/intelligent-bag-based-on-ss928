from dataclasses import dataclass

from radar_protocol import RadarTarget


RISK_SCORE = {
    "safe": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "emergency": 4,
}


@dataclass(frozen=True)
class TargetRisk:
    target: RadarTarget
    area: str
    risk_level: str
    action: str


def classify_area(angle_deg: int) -> str:
    if angle_deg < -15:
        return "left"
    if angle_deg > 15:
        return "right"
    return "center"


def evaluate_target(target: RadarTarget) -> TargetRisk:
    distance = max(0, target.distance_m)
    speed = max(0, target.velocity_mps)

    if distance <= 1:
        level = "emergency"
    elif distance <= 2 or speed >= 2:
        level = "high"
    elif distance <= 4 or speed >= 1:
        level = "medium"
    elif distance <= 8:
        level = "low"
    else:
        level = "safe"

    area = classify_area(target.angle_deg)
    return TargetRisk(target=target, area=area, risk_level=level, action=_action_for(area, level))


def summarize_targets(targets: list[RadarTarget]) -> dict[str, TargetRisk | None]:
    summary: dict[str, TargetRisk | None] = {"left": None, "center": None, "right": None}

    for target in targets:
        evaluated = evaluate_target(target)
        current = summary[evaluated.area]
        if current is None or RISK_SCORE[evaluated.risk_level] > RISK_SCORE[current.risk_level]:
            summary[evaluated.area] = evaluated
        elif current is not None and RISK_SCORE[evaluated.risk_level] == RISK_SCORE[current.risk_level]:
            if evaluated.target.distance_m < current.target.distance_m:
                summary[evaluated.area] = evaluated

    return summary


def _action_for(area: str, level: str) -> str:
    if level == "safe":
        return "none"
    if level == "low":
        return "watch"
    if level == "medium":
        return f"{area}_short_warning"
    if level == "high":
        return f"{area}_strong_warning"
    return f"{area}_emergency_warning"
