from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class MigrationReport:
    old_profile: str
    new_profile: str
    replaced_fields: tuple[str, ...]
    retained_legacy_fields: tuple[str, ...]
    manual_confirmation: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "old_profile": self.old_profile,
            "new_profile": self.new_profile,
            "replaced_fields": list(self.replaced_fields),
            "retained_legacy_fields": list(self.retained_legacy_fields),
            "manual_confirmation": list(self.manual_confirmation),
        }


def _legacy_hardware(config: Mapping[str, Any]) -> dict[str, object]:
    pwm = config.get("pwm", {}) if isinstance(config.get("pwm"), Mapping) else {}
    audio = config.get("audio", {}) if isinstance(config.get("audio"), Mapping) else {}
    return {
        "profile": "legacy_pwm_haptics",
        "i2c_mux": {"enabled": False, "required": False, "failure_policy": "degrade"},
        "imu": {"backend": "bmi270", "required": False, "failure_policy": "degrade"},
        "haptics": {
            "backend": "legacy_pwm",
            "required": True,
            "failure_policy": "fail_service",
            "period_ns": int(pwm.get("period_ns", 1_000_000)),
            "level_duty_percent": copy.deepcopy(pwm.get("level_duty_percent", {})),
        },
        "lights": {"enabled": False, "required": False, "failure_policy": "degrade"},
        "radar": {"enabled": False, "required": False, "failure_policy": "degrade"},
        "audio": {
            "enabled": bool(audio.get("enabled", False)),
            "backend": "max98357",
            "required": False,
            "failure_policy": "degrade",
        },
    }


def _rev2_hardware() -> dict[str, object]:
    return {
        "profile": "rev2_tm6605_mr20",
        "i2c_mux": {
            "enabled": True,
            "device": "/dev/i2c-0",
            "address": "0x70",
            "lock_file": "/run/lock/smartbag-i2c0-mux.lock",
            "channels": {"bmi270": 0, "left_haptic": 1, "right_haptic": 2},
            "required": True,
            "failure_policy": "fail_service",
        },
        "imu": {
            "backend": "bmi270",
            "address": "0x68",
            "mux_channel": 0,
            "required": True,
            "failure_policy": "fail_service",
        },
        "haptics": {
            "backend": "tm6605_lra",
            "address": "0x2d",
            "left_channel": 1,
            "right_channel": 2,
            "required": True,
            "failure_policy": "fail_service",
            "level_effects": {
                "0": {"effect": 0, "count": 0, "interval_ms": 0},
                "1": {"effect": 0, "count": 0, "interval_ms": 0},
                "2": {"effect": 0, "count": 0, "interval_ms": 0},
                "3": {"effect": 15, "count": 3, "interval_ms": 750},
                "4": {"effect": 14, "count": 3, "interval_ms": 300},
            },
        },
        "lights": {
            "enabled": True,
            "required": False,
            "failure_policy": "degrade",
            "period_ns": 1_000_000,
            "left": {"chip": 0, "channel": 10, "pin": 7},
            "right": {"chip": 0, "channel": 1, "pin": 32},
            "level_patterns": {
                "0": {"duty_percent": 0, "on_ms": 0, "off_ms": 0, "count": 0},
                "1": {"duty_percent": 0, "on_ms": 0, "off_ms": 0, "count": 0},
                "2": {"duty_percent": 0, "on_ms": 0, "off_ms": 0, "count": 0},
                "3": {"duty_percent": 50, "on_ms": 1000, "off_ms": 0, "count": 1},
                "4": {"duty_percent": 80, "on_ms": 200, "off_ms": 200, "count": 3},
            },
        },
        "radar": {
            "enabled": True,
            "required": False,
            "failure_policy": "degrade",
            "config": "/etc/smartbag/mr20-radar.json",
        },
        "audio": {
            "enabled": False,
            "backend": "max98357",
            "required": False,
            "failure_policy": "degrade",
        },
    }


def migrate_config(
    source: Mapping[str, Any],
    *,
    new_profile: str = "legacy_pwm_haptics",
) -> tuple[dict[str, Any], MigrationReport]:
    if new_profile not in ("legacy_pwm_haptics", "rev2_tm6605_mr20"):
        raise ValueError("new_profile must be legacy_pwm_haptics or rev2_tm6605_mr20")
    result = copy.deepcopy(dict(source))
    old_hardware = source.get("hardware", {})
    old_profile = (
        str(old_hardware.get("profile", "legacy_unprofiled"))
        if isinstance(old_hardware, Mapping)
        else "legacy_unprofiled"
    )
    replaced: list[str] = []
    retained: list[str] = []
    pwm = source.get("pwm")
    if isinstance(pwm, Mapping) and "level_duty_percent" in pwm:
        replaced.append("pwm.level_duty_percent -> hardware.haptics")
        retained.append("pwm.level_duty_percent")
    cameras = source.get("cameras")
    if isinstance(cameras, Mapping):
        for side in ("left", "right"):
            camera = cameras.get(side)
            if isinstance(camera, Mapping) and "pwm_channels" in camera:
                replaced.append(f"cameras.{side}.pwm_channels -> hardware profile")
                retained.append(f"cameras.{side}.pwm_channels")
    result["hardware"] = (
        _rev2_hardware() if new_profile == "rev2_tm6605_mr20" else _legacy_hardware(source)
    )
    result["config_migration"] = {
        "legacy_fields_retained": retained,
        "note": "Legacy fields remain for rollback; new runtime reads hardware.*.",
    }
    manual = (
        "Confirm Pin3/5 TCA9548A wiring and voltage levels.",
        "Confirm BMI270 CH0, left TM6605 CH1 and right TM6605 CH2.",
        "Confirm Pin7/32 now drive powered light modules, not legacy vibration motors.",
        "Confirm MR20 eth1 host-route addresses before enabling radar.",
    ) if new_profile == "rev2_tm6605_mr20" else (
        "Legacy PWM wiring remains active; do not connect Rev2 lights to Pin7/32.",
    )
    return result, MigrationReport(
        old_profile=old_profile,
        new_profile=new_profile,
        replaced_fields=tuple(replaced),
        retained_legacy_fields=tuple(retained),
        manual_confirmation=manual,
    )

