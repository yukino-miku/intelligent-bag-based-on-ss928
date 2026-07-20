from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from alert_core import VALID_SIDES, normalize_level


DEFAULT_REV2_LEVEL_MAP = {0: 0, 1: 0, 2: 0, 3: 3, 4: 4}
DEFAULT_LEGACY_LEVEL_MAP = {level: level for level in range(5)}


@dataclass(frozen=True)
class OutputDecision:
    effective_levels: dict[str, int]
    haptic_levels: dict[str, int]
    light_levels: dict[str, int]
    audio_clip: str | None


class OutputPolicy:
    """Map stabilized effective levels to physical actuator levels."""

    def __init__(
        self,
        *,
        haptic_level_map: Mapping[int | str, int] | None = None,
        light_level_map: Mapping[int | str, int] | None = None,
        audio_levels: tuple[int, ...] = (3, 4),
    ) -> None:
        self.haptic_level_map = self._normalize_map(
            haptic_level_map or DEFAULT_REV2_LEVEL_MAP
        )
        self.light_level_map = self._normalize_map(
            light_level_map or DEFAULT_REV2_LEVEL_MAP
        )
        self.audio_levels = tuple(sorted({normalize_level(level) for level in audio_levels}))

    @classmethod
    def for_profile(
        cls,
        profile: str,
        config: Mapping[str, object] | None = None,
    ) -> "OutputPolicy":
        raw = config or {}
        default_map = (
            DEFAULT_LEGACY_LEVEL_MAP
            if profile == "legacy_pwm_haptics"
            else DEFAULT_REV2_LEVEL_MAP
        )
        haptic_map = raw.get("haptic_level_map", default_map)
        light_map = raw.get("light_level_map", default_map)
        audio_levels = raw.get("audio_levels", (3, 4))
        if not isinstance(haptic_map, Mapping) or not isinstance(light_map, Mapping):
            raise ValueError("output_policy level maps must be objects")
        if not isinstance(audio_levels, (list, tuple)):
            raise ValueError("output_policy.audio_levels must be a list")
        return cls(
            haptic_level_map=haptic_map,
            light_level_map=light_map,
            audio_levels=tuple(int(level) for level in audio_levels),
        )

    def decide(
        self,
        levels: Mapping[str, int],
        audio_clip: str | None = None,
    ) -> OutputDecision:
        effective = {
            side: normalize_level(levels.get(side, 0)) for side in VALID_SIDES
        }
        haptic = {
            side: self.haptic_level_map[effective[side]] for side in VALID_SIDES
        }
        lights = {
            side: self.light_level_map[effective[side]] for side in VALID_SIDES
        }
        clip = audio_clip
        if clip is not None:
            side = "left" if clip.startswith("L") else "right"
            if effective[side] not in self.audio_levels:
                clip = None
        return OutputDecision(effective, haptic, lights, clip)

    @staticmethod
    def _normalize_map(raw: Mapping[int | str, int]) -> dict[int, int]:
        result = {int(level): normalize_level(value) for level, value in raw.items()}
        if set(result) != set(range(5)):
            raise ValueError("output policy maps must define levels 0..4")
        return result
