from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class FallFusionConfig:
    warning_window_s: float = 10.0
    recovery_window_s: float = 7.0
    standing_posture_deg: float = 25.0
    standing_hold_s: float = 1.0


def _is_supported_warning(data: Mapping[str, Any]) -> bool:
    source = str(data.get("source", "")).strip().lower()
    try:
        level = int(data.get("level", 0))
    except (TypeError, ValueError):
        return False
    return level in (3, 4) and (source == "vision" or source.startswith("radar:"))


def write_high_warning_marker(path: str | Path, data: Mapping[str, Any]) -> bool:
    """Atomically remember the latest camera/radar level-3 or level-4 warning."""
    if not _is_supported_warning(data):
        return False

    marker = Path(path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "type": "high_warning",
        "source": str(data["source"]),
        "side": str(data.get("side", "unknown")),
        "level": int(data["level"]),
        "ts": float(data["ts"]),
    }
    temporary = marker.with_name(marker.name + ".tmp")
    temporary.write_text(json.dumps(record, separators=(",", ":")), encoding="utf-8")
    temporary.replace(marker)
    return True


def read_recent_warning(
    path: str | Path,
    now_wall: float,
    window_s: float = 10.0,
) -> dict[str, Any] | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not _is_supported_warning(data):
            return None
        age_s = float(now_wall) - float(data["ts"])
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if age_s < 0.0 or age_s > float(window_s):
        return None
    return data


class FallFusionGate:
    """Require IMU fall, a recent high warning, and no standing recovery."""

    def __init__(self, config: FallFusionConfig | None = None) -> None:
        self.config = config or FallFusionConfig()
        self._pending: dict[str, Any] | None = None
        self._standing_since: float | None = None

    @property
    def pending(self) -> bool:
        return self._pending is not None

    def start(
        self,
        imu_event: Mapping[str, Any],
        warning: Mapping[str, Any] | None,
        now_mono: float,
        now_wall: float,
    ) -> bool:
        if imu_event.get("event") != "fall_confirmed" or warning is None:
            return False
        if not _is_supported_warning(warning):
            return False
        warning_age_s = float(now_wall) - float(warning["ts"])
        if warning_age_s < 0.0 or warning_age_s > self.config.warning_window_s:
            return False

        self._pending = {
            "started_mono": float(now_mono),
            "started_wall": float(now_wall),
            "imu_event": dict(imu_event),
            "warning": dict(warning),
            "warning_age_s": warning_age_s,
        }
        self._standing_since = None
        return True

    def update_motion(
        self,
        posture_delta_deg: float,
        now_mono: float,
        now_wall: float,
    ) -> dict[str, Any] | None:
        if self._pending is None:
            return None

        now_mono = float(now_mono)
        if float(posture_delta_deg) <= self.config.standing_posture_deg:
            if self._standing_since is None:
                self._standing_since = now_mono
            elif now_mono - self._standing_since >= self.config.standing_hold_s:
                self._clear()
                return None
        else:
            self._standing_since = None

        if now_mono - float(self._pending["started_mono"]) < self.config.recovery_window_s:
            return None

        pending = self._pending
        alarm = {
            "type": "fall_alarm",
            "alarmType": "fall_detected",
            "signal": "FALL_ALARM",
            "severity": "high",
            "ts": float(now_wall),
            "deviceTimestampMs": int(float(now_wall) * 1000),
            "conditions": {
                "imu_fall_confirmed": True,
                "recent_level_3_or_4_warning": True,
                "no_standing_recovery_7s": True,
            },
            "evidence": {
                "imu": pending["imu_event"],
                "warning": pending["warning"],
                "warning_age_s": round(float(pending["warning_age_s"]), 3),
                "recovery_window_s": float(self.config.recovery_window_s),
                "last_posture_delta_deg": round(float(posture_delta_deg), 2),
            },
        }
        self._clear()
        return alarm

    def _clear(self) -> None:
        self._pending = None
        self._standing_since = None


def event_to_json(event: Mapping[str, Any]) -> str:
    return json.dumps(dict(event), separators=(",", ":"), ensure_ascii=True)
