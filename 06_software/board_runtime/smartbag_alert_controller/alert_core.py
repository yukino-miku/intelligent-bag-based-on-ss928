from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Mapping


DEFAULT_PWM_PERIOD_NS = 1_000_000
VALID_SIDES = ("left", "right")


@dataclass(frozen=True)
class PwmPin:
    key: str
    side: str
    stage: int
    header_pin: int
    signal: str
    pwm_chip: int
    pwm_channel: int
    pinmux_addr: str
    pinmux_value: str


MOTOR_PWM_PINS: tuple[PwmPin, ...] = (
    PwmPin("left_1", "left", 1, 7, "PWM0_OUT10_0_P", 0, 10, "0x102F0110", "0x1205"),
    PwmPin("left_2", "left", 2, 32, "PWM0_OUT1_0_P", 0, 1, "0x102F01EC", "0x1201"),
    PwmPin("right_1", "right", 1, 35, "PWM0_OUT14_0_P", 0, 14, "0x102F0100", "0x1205"),
    PwmPin("right_2", "right", 2, 37, "PWM0_OUT15_0_P", 0, 15, "0x102F00DC", "0x1205"),
)

MOTOR_BY_KEY = {pin.key: pin for pin in MOTOR_PWM_PINS}
MOTORS_BY_SIDE = {
    "left": tuple(pin for pin in MOTOR_PWM_PINS if pin.side == "left"),
    "right": tuple(pin for pin in MOTOR_PWM_PINS if pin.side == "right"),
}

DEFAULT_LEVEL_DUTY_PERCENT = {
    0: (0, 0),
    1: (60, 0),
    2: (60, 60),
    3: (100, 60),
    4: (100, 100),
}
LEVEL_DUTY_PERCENT = DEFAULT_LEVEL_DUTY_PERCENT

SIDE_ALIASES = {
    "l": "left",
    "left": "left",
    "左": "left",
    "r": "right",
    "right": "right",
    "右": "right",
}


@dataclass(frozen=True)
class AlertCommand:
    kind: str
    side: str | None = None
    level: int = 0


@dataclass(frozen=True)
class AlertEvent:
    side: str
    level: int
    score: float | None = None
    track_id: int | None = None
    ts: float | None = None
    class_name: str | None = None
    distance_m: float | None = None
    observation_age_ms: float | None = None
    clear_reason: str | None = None
    event_kind: str = "state_change"
    source: str = ""
    source_id: str | None = None
    ttc_s: float | None = None
    closing_speed_mps: float | None = None
    lateral_distance_m: float | None = None
    longitudinal_distance_m: float | None = None
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class AlertOutput:
    duties_ns: dict[str, int]
    audio_clip: str | None = None
    levels: dict[str, int] | None = None
    expired_sides: tuple[str, ...] = ()
    expired_sources: tuple[str, ...] = ()
    expired_source_sides: tuple[tuple[str, str], ...] = ()


def normalize_side(side: str) -> str:
    normalized = SIDE_ALIASES.get(str(side).strip().lower())
    if normalized not in VALID_SIDES:
        raise ValueError(f"invalid side: {side!r}")
    return normalized


def normalize_level(level: Any, *, allow_zero: bool = True) -> int:
    try:
        value = int(level)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid alert level: {level!r}") from exc
    low = 0 if allow_zero else 1
    if value < low or value > 4:
        raise ValueError(f"alert level must be {low}..4, got {value}")
    return value


def duty_ns_for_percent(percent: int, period_ns: int = DEFAULT_PWM_PERIOD_NS) -> int:
    if percent <= 0:
        return 0
    if percent >= 100:
        return period_ns
    return int(round(period_ns * (percent / 100.0)))


def duties_for_levels(
    levels_by_side: Mapping[str, int],
    period_ns: int = DEFAULT_PWM_PERIOD_NS,
    level_duty_percent: Mapping[int | str, tuple[int, int] | list[int]] | None = None,
) -> dict[str, int]:
    configured = level_duty_percent or DEFAULT_LEVEL_DUTY_PERCENT
    normalized_duties = {
        int(level): (int(values[0]), int(values[1]))
        for level, values in configured.items()
    }
    for level in range(5):
        if level not in normalized_duties or len(normalized_duties[level]) != 2:
            raise ValueError("level duty mapping must define levels 0..4 with two stages")
    normalized_levels = {"left": 0, "right": 0}
    for side, level in levels_by_side.items():
        normalized_levels[normalize_side(side)] = normalize_level(level)

    duties: dict[str, int] = {}
    for side in VALID_SIDES:
        stage_percents = normalized_duties[normalized_levels[side]]
        for pin, percent in zip(MOTORS_BY_SIDE[side], stage_percents):
            duties[pin.key] = duty_ns_for_percent(percent, period_ns)
    return duties


def audio_clip_for(side: str, level: int) -> str | None:
    normalized_side = normalize_side(side)
    normalized_level = normalize_level(level)
    if normalized_level <= 0:
        return None
    prefix = "L" if normalized_side == "left" else "R"
    return f"{prefix}{normalized_level}"


def parse_alert_command(command: str) -> AlertCommand:
    text = str(command or "").strip()
    if not text:
        raise ValueError("empty alert command")

    parts = text.upper().split()
    if len(parts) < 2 or parts[0] != "AL":
        raise ValueError(f"unsupported alert command: {command!r}")
    if parts[1] == "CLEAR":
        if len(parts) != 2:
            raise ValueError(f"unsupported clear command: {command!r}")
        return AlertCommand(kind="clear")

    if len(parts) == 2:
        target = parts[1]
        if len(target) < 2:
            raise ValueError(f"unsupported alert target: {command!r}")
        side = normalize_side(target[0])
        level = normalize_level(target[1:])
        return AlertCommand(kind="alert", side=side, level=level)

    if len(parts) == 3:
        side = normalize_side(parts[1])
        level = normalize_level(parts[2].lstrip("L"))
        return AlertCommand(kind="alert", side=side, level=level)

    raise ValueError(f"unsupported alert command: {command!r}")


def parse_vision_alert_jsonl(line: str) -> AlertEvent | None:
    data = json.loads(line)
    if not isinstance(data, dict) or data.get("type") != "vision_alert":
        return None
    event_kind = str(data.get("event_kind", "state_change"))
    if event_kind not in ("state_change", "heartbeat"):
        raise ValueError(f"invalid vision alert event_kind: {event_kind!r}")
    side = normalize_side(str(data["side"]))
    return AlertEvent(
        side=side,
        level=normalize_level(data["level"]),
        event_kind=event_kind,
        score=float(data["score"]) if data.get("score") is not None else None,
        track_id=int(data["track_id"]) if data.get("track_id") is not None else None,
        ts=float(data["ts"]) if data.get("ts") is not None else None,
        class_name=str(data["class"]) if data.get("class") is not None else None,
        distance_m=float(data["distance_m"]) if data.get("distance_m") is not None else None,
        observation_age_ms=(
            float(data["observation_age_ms"])
            if data.get("observation_age_ms") is not None
            else None
        ),
        clear_reason=str(data["clear_reason"]) if data.get("clear_reason") is not None else None,
        source=str(data.get("source") or f"vision:{side}"),
        source_id=str(data["source_id"]) if data.get("source_id") is not None else None,
        ttc_s=float(data["ttc_s"]) if data.get("ttc_s") is not None else None,
        closing_speed_mps=(
            float(data["closing_speed_mps"])
            if data.get("closing_speed_mps") is not None
            else None
        ),
        lateral_distance_m=(
            float(data["lateral_distance_m"])
            if data.get("lateral_distance_m") is not None
            else None
        ),
        longitudinal_distance_m=(
            float(data["longitudinal_distance_m"])
            if data.get("longitudinal_distance_m") is not None
            else None
        ),
        metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else None,
    )


def event_is_stale(event: AlertEvent, now_s: float, max_age_s: float) -> bool:
    if max_age_s > 0.0 and event.observation_age_ms is not None and event.observation_age_ms > max_age_s * 1000.0:
        return True
    if event.ts is None or max_age_s <= 0.0:
        return False
    age_s = float(now_s) - float(event.ts)
    return age_s > max_age_s or age_s < -max(1.0, max_age_s)


class AlertState:
    def __init__(
        self,
        event_timeout_s: float = 1.0,
        min_audio_interval_s: float = 2.0,
        period_ns: int = DEFAULT_PWM_PERIOD_NS,
        level_duty_percent: Mapping[int | str, tuple[int, int] | list[int]] | None = None,
        source_timeouts_s: Mapping[str, float] | None = None,
    ) -> None:
        self.event_timeout_s = max(0.05, float(event_timeout_s))
        self.min_audio_interval_s = max(0.0, float(min_audio_interval_s))
        self.period_ns = int(period_ns)
        self.level_duty_percent = level_duty_percent or DEFAULT_LEVEL_DUTY_PERCENT
        self.levels_by_side = {"left": 0, "right": 0}
        self.last_event_mono_by_side: dict[str, float] = {}
        self.last_audio_mono_by_clip: dict[str, float] = {}
        self.source_levels: dict[tuple[str, str], int] = {}
        self.last_event_mono_by_source: dict[tuple[str, str], float] = {}
        self.source_timeouts_s = {
            str(source): max(0.05, float(timeout))
            for source, timeout in (source_timeouts_s or {}).items()
        }

    @staticmethod
    def event_source(event: AlertEvent) -> str:
        source = str(event.source or "").strip()
        return source or f"vision:{normalize_side(event.side)}"

    def apply_event(self, event: AlertEvent, now: float | None = None) -> AlertOutput:
        now = time.monotonic() if now is None else now
        side = normalize_side(event.side)
        level = normalize_level(event.level)
        source = self.event_source(event)
        key = (source, side)
        previous_source_level = self.source_levels.get(key, 0)
        previous_level = self.levels_by_side[side]
        if event.event_kind == "heartbeat" and level != previous_source_level:
            return self._output()
        if level > 0:
            self.source_levels[key] = level
            self.last_event_mono_by_source[key] = now
        else:
            self.source_levels.pop(key, None)
            self.last_event_mono_by_source.pop(key, None)
        self._refresh_effective_side(side)
        effective_level = self.levels_by_side[side]

        clip = None if event.event_kind == "heartbeat" else audio_clip_for(side, effective_level)
        if clip is not None and not self._should_emit_audio(
            clip, previous_level, effective_level, now
        ):
            clip = None
        return self._output(audio_clip=clip)

    def apply_command(self, command: AlertCommand, now: float | None = None) -> AlertOutput:
        now = time.monotonic() if now is None else now
        if command.kind == "clear":
            self.clear()
            return self._output()
        if command.kind != "alert" or command.side is None:
            raise ValueError(f"unsupported alert command kind: {command.kind!r}")
        side = normalize_side(command.side)
        level = normalize_level(command.level)
        key = ("manual", side)
        if level > 0:
            self.source_levels[key] = level
            self.last_event_mono_by_source[key] = now
        else:
            self.source_levels.pop(key, None)
            self.last_event_mono_by_source.pop(key, None)
        previous_level = self.levels_by_side[side]
        self._refresh_effective_side(side)
        effective_level = self.levels_by_side[side]
        clip = audio_clip_for(side, effective_level)
        if clip:
            if previous_level != effective_level:
                self.last_audio_mono_by_clip[clip] = now
            else:
                clip = None
        return self._output(audio_clip=clip)

    def clear(self, *, source: str | None = None, side: str | None = None) -> None:
        normalized_side = normalize_side(side) if side is not None else None
        keys = [
            key
            for key in self.source_levels
            if (source is None or key[0] == source)
            and (normalized_side is None or key[1] == normalized_side)
        ]
        for key in keys:
            self.source_levels.pop(key, None)
            self.last_event_mono_by_source.pop(key, None)
        for affected_side in VALID_SIDES:
            if normalized_side is None or affected_side == normalized_side:
                self._refresh_effective_side(affected_side)
        if source is None and normalized_side is None:
            self.last_audio_mono_by_clip.clear()

    def expire(self, now: float | None = None) -> AlertOutput:
        now = time.monotonic() if now is None else now
        expired_sides: set[str] = set()
        expired_sources: list[str] = []
        expired_source_sides: list[tuple[str, str]] = []
        for key, last_event_mono in list(self.last_event_mono_by_source.items()):
            source, side = key
            timeout = self._timeout_for_source(source)
            if now - last_event_mono > timeout:
                self.source_levels.pop(key, None)
                self.last_event_mono_by_source.pop(key, None)
                expired_sides.add(side)
                expired_sources.append(source)
                expired_source_sides.append((source, side))
        for side in expired_sides:
            self._refresh_effective_side(side)
        return self._output(
            expired_sides=tuple(sorted(expired_sides)),
            expired_sources=tuple(sorted(expired_sources)),
            expired_source_sides=tuple(sorted(expired_source_sides)),
        )

    def source_snapshot(self) -> dict[str, dict[str, int]]:
        snapshot: dict[str, dict[str, int]] = {}
        for (source, side), level in sorted(self.source_levels.items()):
            snapshot.setdefault(source, {})[side] = level
        return snapshot

    def _timeout_for_source(self, source: str) -> float:
        if source in self.source_timeouts_s:
            return self.source_timeouts_s[source]
        prefix = source.split(":", 1)[0]
        return self.source_timeouts_s.get(prefix, self.event_timeout_s)

    def _refresh_effective_side(self, side: str) -> None:
        self.levels_by_side[side] = max(
            (level for (source, event_side), level in self.source_levels.items() if event_side == side),
            default=0,
        )
        times = [
            last
            for (source, event_side), last in self.last_event_mono_by_source.items()
            if event_side == side
        ]
        if times:
            self.last_event_mono_by_side[side] = max(times)
        else:
            self.last_event_mono_by_side.pop(side, None)

    def _should_emit_audio(self, clip: str, previous_level: int, level: int, now: float) -> bool:
        if level != previous_level:
            self.last_audio_mono_by_clip[clip] = now
            return True
        last_audio = self.last_audio_mono_by_clip.get(clip)
        if last_audio is None or now - last_audio >= self.min_audio_interval_s:
            self.last_audio_mono_by_clip[clip] = now
            return True
        return False

    def _output(
        self,
        audio_clip: str | None = None,
        expired_sides: tuple[str, ...] = (),
        expired_sources: tuple[str, ...] = (),
        expired_source_sides: tuple[tuple[str, str], ...] = (),
    ) -> AlertOutput:
        return AlertOutput(
            duties_ns=duties_for_levels(
                self.levels_by_side,
                period_ns=self.period_ns,
                level_duty_percent=self.level_duty_percent,
            ),
            audio_clip=audio_clip,
            levels=dict(self.levels_by_side),
            expired_sides=expired_sides,
            expired_sources=expired_sources,
            expired_source_sides=expired_source_sides,
        )
