from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


VALID_PROFILES = ("legacy_pwm_haptics", "rev2_tm6605_mr20")
VALID_FAILURE_POLICIES = ("degrade", "fail_service")
VALID_MODULE_STATES = ("disabled", "starting", "online", "degraded", "offline", "error")


@dataclass(frozen=True)
class PinUse:
    pin: int
    owner: str
    function: str


def _module_policy(config: Mapping[str, Any], name: str) -> None:
    module = config.get(name, {})
    if not isinstance(module, Mapping):
        raise ValueError(f"hardware.{name} must be an object")
    policy = str(module.get("failure_policy", "fail_service" if module.get("required") else "degrade"))
    if policy not in VALID_FAILURE_POLICIES:
        raise ValueError(f"hardware.{name}.failure_policy must be one of {VALID_FAILURE_POLICIES}")


def pin_uses_for_hardware(config: Mapping[str, Any]) -> tuple[PinUse, ...]:
    uses = [
        PinUse(3, "i2c_mux", "I2C0_SDA"),
        PinUse(5, "i2c_mux", "I2C0_SCL"),
        PinUse(8, "gnss", "UART4_TXD"),
        PinUse(10, "gnss", "UART4_RXD"),
        PinUse(12, "audio", "I2S_BCLK"),
        PinUse(38, "audio", "I2S_WS"),
        PinUse(40, "audio", "I2S_SD_TX"),
    ]
    profile = str(config.get("profile", "legacy_pwm_haptics"))
    haptics = config.get("haptics", {})
    lights = config.get("lights", {})
    if profile == "legacy_pwm_haptics" or (
        isinstance(haptics, Mapping) and haptics.get("backend") == "legacy_pwm"
    ):
        uses.extend(
            (
                PinUse(7, "legacy_haptics", "PWM0_OUT10_0_P"),
                PinUse(32, "legacy_haptics", "PWM0_OUT1_0_P"),
                PinUse(35, "legacy_haptics", "PWM0_OUT14_0_P"),
                PinUse(37, "legacy_haptics", "PWM0_OUT15_0_P"),
            )
        )
    if isinstance(lights, Mapping) and bool(lights.get("enabled", False)):
        for side in ("left", "right"):
            spec = lights.get(side, {})
            if isinstance(spec, Mapping):
                uses.append(PinUse(int(spec["pin"]), f"{side}_light", "PWM"))
    return tuple(uses)


def pin_conflicts(config: Mapping[str, Any]) -> dict[int, tuple[PinUse, ...]]:
    grouped: dict[int, list[PinUse]] = {}
    for use in pin_uses_for_hardware(config):
        grouped.setdefault(use.pin, []).append(use)
    return {pin: tuple(uses) for pin, uses in grouped.items() if len(uses) > 1}


def validate_hardware_profile(config: Mapping[str, Any]) -> None:
    profile = str(config.get("profile", ""))
    if profile not in VALID_PROFILES:
        raise ValueError(f"hardware.profile must be one of {VALID_PROFILES}")
    for name in ("i2c_mux", "imu", "haptics", "lights", "radar", "audio"):
        _module_policy(config, name)

    haptics = config.get("haptics", {})
    if not isinstance(haptics, Mapping):
        raise ValueError("hardware.haptics must be an object")
    backend = str(haptics.get("backend", ""))
    expected = "tm6605_lra" if profile == "rev2_tm6605_mr20" else "legacy_pwm"
    if backend != expected:
        raise ValueError(f"profile {profile} requires haptics.backend={expected}")

    mux = config.get("i2c_mux", {})
    if profile == "rev2_tm6605_mr20":
        if not isinstance(mux, Mapping) or not bool(mux.get("enabled", False)):
            raise ValueError("Rev2 requires hardware.i2c_mux.enabled=true")
        channels = mux.get("channels", {})
        if not isinstance(channels, Mapping):
            raise ValueError("hardware.i2c_mux.channels must be an object")
        expected_channels = {"bmi270": 0, "left_haptic": 1, "right_haptic": 2}
        if {key: int(channels.get(key, -1)) for key in expected_channels} != expected_channels:
            raise ValueError("Rev2 mux channels must be BMI270=0, left_haptic=1, right_haptic=2")

    conflicts = pin_conflicts(config)
    if conflicts:
        detail = ", ".join(
            f"Pin{pin}:" + "/".join(use.owner for use in uses)
            for pin, uses in sorted(conflicts.items())
        )
        raise ValueError(f"hardware pin conflict: {detail}")

