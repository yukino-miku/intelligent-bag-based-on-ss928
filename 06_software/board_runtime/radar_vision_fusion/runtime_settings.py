from __future__ import annotations

import json
import math
import os
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping

from risk_model import RiskModelConfig

try:
    from .radar_camera_calibration import FusionCalibration
    from .radar_vision_association import AssociationConfig
except ImportError:
    from radar_camera_calibration import FusionCalibration
    from radar_vision_association import AssociationConfig


SIDE_FIELDS = {
    "camera_mount_y_m": (-3.0, 5.0),
    "radar_mount_y_m": (-3.0, 5.0),
    "camera_mount_x_m": (-5.0, 5.0),
    "radar_mount_x_m": (-5.0, 5.0),
    "camera_yaw_deg": (-180.0, 180.0),
    "camera_pitch_deg": (-90.0, 90.0),
    "radar_yaw_deg": (-180.0, 180.0),
    "camera_horizontal_fov_deg": (10.0, 179.0),
}

ASSOCIATION_FIELDS = {
    "projection_half_width_px": (0.0, 640.0),
    "projection_half_width_ratio": (0.0, 0.50),
    "bbox_expand_ratio": (0.0, 2.0),
    "association_max_time_delta_s": (0.01, 2.0),
    "max_center_distance_px": (1.0, 1280.0),
    "max_association_cost": (0.01, 10.0),
    "ambiguity_cost_gap": (0.0, 1.0),
}

RISK_MULTIPLIER_FIELDS = {
    "bicycle_risk_multiplier": "bicycle",
    "motorcycle_risk_multiplier": "motorcycle",
    "car_risk_multiplier": "car",
    "truck_risk_multiplier": "truck",
    "bus_risk_multiplier": "bus",
    "unknown_risk_multiplier": "unknown",
}


@dataclass(frozen=True)
class RuntimeTuningState:
    calibrations: dict[str, FusionCalibration]
    association: AssociationConfig
    risk: RiskModelConfig
    warning_sensitivity: float
    version: int


class RuntimeTuningManager:
    """Validate, persist and atomically publish the runtime tuning whitelist."""

    def __init__(
        self,
        calibrations: Mapping[str, FusionCalibration],
        association: AssociationConfig,
        risk: RiskModelConfig,
        warning_sensitivity: float = 1.0,
        *,
        path: str | Path = "/etc/smartbag/runtime-tuning.json",
        on_apply: Callable[[RuntimeTuningState], None] | None = None,
    ) -> None:
        self.path = Path(path)
        self._on_apply = on_apply
        self._lock = threading.RLock()
        self._defaults = RuntimeTuningState(
            calibrations=dict(calibrations),
            association=association,
            risk=risk,
            warning_sensitivity=_range("warning_sensitivity", warning_sensitivity, 0.25, 2.0),
            version=1,
        )
        self._state = self._defaults
        if self.path.is_file():
            persisted = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(persisted, Mapping):
                self._state = self._build_state(persisted, version=max(1, int(persisted.get("version", 1))))
        self._publish()

    def state(self) -> RuntimeTuningState:
        with self._lock:
            return self._state

    def as_dict(self) -> dict[str, object]:
        with self._lock:
            return self._serialize(self._state)

    def patch(self, patch: Mapping[str, object]) -> dict[str, object]:
        with self._lock:
            merged = _deep_merge(self._serialize(self._state), patch)
            candidate = self._build_state(merged, version=self._state.version + 1)
            self._persist(candidate)
            self._state = candidate
            self._publish()
            return self._serialize(candidate)

    def reset(self) -> dict[str, object]:
        with self._lock:
            candidate = replace(self._defaults, version=self._state.version + 1)
            self._persist(candidate)
            self._state = candidate
            self._publish()
            return self._serialize(candidate)

    def _build_state(self, data: Mapping[str, object], *, version: int) -> RuntimeTuningState:
        allowed_top = {"left", "right", "association", "risk", "version"}
        unknown_top = set(data) - allowed_top
        if unknown_top:
            raise ValueError(f"unsupported runtime settings sections: {sorted(unknown_top)}")

        calibrations: dict[str, FusionCalibration] = {}
        for side in ("left", "right"):
            original = self._state.calibrations.get(side, self._defaults.calibrations.get(side))
            if original is None:
                continue
            values = data.get(side, {})
            if not isinstance(values, Mapping):
                raise ValueError(f"{side} settings must be an object")
            unknown = set(values) - set(SIDE_FIELDS)
            if unknown:
                raise ValueError(f"unsupported {side} settings: {sorted(unknown)}")
            updates = {
                name: _range(f"{side}.{name}", values.get(name, getattr(original, name)), low, high)
                for name, (low, high) in SIDE_FIELDS.items()
            }
            calibrations[side] = replace(original, **updates)

        association_values = data.get("association", {})
        if not isinstance(association_values, Mapping):
            raise ValueError("association settings must be an object")
        unknown_association = set(association_values) - set(ASSOCIATION_FIELDS)
        if unknown_association:
            raise ValueError(f"unsupported association settings: {sorted(unknown_association)}")
        association = replace(
            self._state.association,
            **{
                name: _range(
                    f"association.{name}",
                    association_values.get(name, getattr(self._state.association, name)),
                    low,
                    high,
                )
                for name, (low, high) in ASSOCIATION_FIELDS.items()
            },
        )

        risk_values = data.get("risk", {})
        if not isinstance(risk_values, Mapping):
            raise ValueError("risk settings must be an object")
        allowed_risk = {"warning_sensitivity", *RISK_MULTIPLIER_FIELDS}
        unknown_risk = set(risk_values) - allowed_risk
        if unknown_risk:
            raise ValueError(f"unsupported risk settings: {sorted(unknown_risk)}")
        sensitivity = _range(
            "risk.warning_sensitivity",
            risk_values.get("warning_sensitivity", self._state.warning_sensitivity),
            0.25,
            2.0,
        )
        multipliers = dict(self._state.risk.vehicle_risk_multipliers)
        for field_name, class_name in RISK_MULTIPLIER_FIELDS.items():
            if field_name in risk_values:
                multipliers[class_name] = _range(f"risk.{field_name}", risk_values[field_name], 0.0, 3.0)
        risk = replace(self._state.risk, vehicle_risk_multipliers=multipliers)
        return RuntimeTuningState(calibrations, association, risk, sensitivity, version)

    def _persist(self, state: RuntimeTuningState) -> None:
        payload = json.dumps(self._serialize(state), ensure_ascii=False, indent=2) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _publish(self) -> None:
        if self._on_apply is not None:
            self._on_apply(self._state)

    @staticmethod
    def _serialize(state: RuntimeTuningState) -> dict[str, object]:
        payload: dict[str, object] = {"version": state.version}
        for side, calibration in state.calibrations.items():
            payload[side] = {name: getattr(calibration, name) for name in SIDE_FIELDS}
        payload["association"] = {
            name: getattr(state.association, name)
            for name in ASSOCIATION_FIELDS
        }
        payload["risk"] = {
            "warning_sensitivity": state.warning_sensitivity,
            **{
                field_name: state.risk.vehicle_risk_multipliers.get(class_name, 1.0)
                for field_name, class_name in RISK_MULTIPLIER_FIELDS.items()
            },
        }
        return payload


def _range(name: str, value: object, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{name} must be in [{low}, {high}]")
    return number


def _deep_merge(base: Mapping[str, object], patch: Mapping[str, object]) -> dict[str, object]:
    result = dict(base)
    for key, value in patch.items():
        if key == "version":
            continue
        current = result.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = value
    return result
