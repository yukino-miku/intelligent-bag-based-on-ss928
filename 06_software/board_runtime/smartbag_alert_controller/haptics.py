from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol

from alert_core import VALID_SIDES, duties_for_levels, normalize_level, normalize_side

from i2c_mux import I2cMuxTransaction


TM6605_EFFECT_REGISTER = 0x04
TM6605_PLAY_REGISTER = 0x0C


class HapticBackend(Protocol):
    def preflight(self) -> None: ...

    def setup(self) -> None: ...

    def apply_levels(self, levels: Mapping[str, int], now: float | None = None) -> None: ...

    def tick(self, now: float | None = None) -> None: ...

    def stop_side(self, side: str) -> None: ...

    def stop_all(self) -> None: ...

    def status(self) -> dict[str, object]: ...


@dataclass(frozen=True)
class EffectPattern:
    effect: int
    repeat_interval_ms: int

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "EffectPattern":
        effect = int(raw.get("effect", 0))
        repeat_interval_ms = int(raw.get("repeat_interval_ms", raw.get("interval_ms", 0)))
        if effect not in range(256) or repeat_interval_ms < 0:
            raise ValueError("invalid TM6605 effect pattern")
        if effect > 0 and repeat_interval_ms <= 0:
            raise ValueError("active TM6605 effect requires repeat_interval_ms > 0")
        return cls(effect, repeat_interval_ms)


@dataclass
class HapticSideState:
    requested_level: int = 0
    applied_level: int = 0
    effect: int = 0
    next_play_at: float | None = None
    cycle_index: int = 0
    active: bool = False
    play_count: int = 0
    error_count: int = 0
    last_error: str = ""


class Tm6605HapticBackend:
    def __init__(
        self,
        transactions: Mapping[str, I2cMuxTransaction],
        level_effects: Mapping[int | str, Mapping[str, object]],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.transactions = {normalize_side(side): tx for side, tx in transactions.items()}
        if not self.transactions:
            raise ValueError("at least one TM6605 side is required")
        self.patterns = {
            int(level): EffectPattern.from_mapping(pattern)
            for level, pattern in level_effects.items()
        }
        for level in range(5):
            if level not in self.patterns:
                raise ValueError("haptics.level_effects must define levels 0..4")
        self.clock = clock
        self._states = {side: HapticSideState() for side in VALID_SIDES}
        self._last_write_mono_s: dict[str, float | None] = {
            side: None for side in VALID_SIDES
        }

    def preflight(self) -> None:
        for side, transaction in self.transactions.items():
            try:
                transaction.execute(lambda device: device.write(bytes((TM6605_PLAY_REGISTER, 0))))
            except Exception as exc:
                self._record_error(side, exc)
                raise RuntimeError(f"{side} TM6605 preflight failed: {exc}") from exc

    def setup(self) -> None:
        self.stop_all()

    def apply_levels(self, levels: Mapping[str, int], now: float | None = None) -> None:
        now = self.clock() if now is None else float(now)
        normalized = {side: 0 for side in VALID_SIDES}
        for side, level in levels.items():
            normalized[normalize_side(side)] = normalize_level(level)
        for side in VALID_SIDES:
            level = normalized[side]
            state = self._states[side]
            if level == state.requested_level and level == state.applied_level:
                continue
            if state.active or state.applied_level > 0:
                self._stop_hardware(side)
            state.requested_level = level
            state.applied_level = 0
            state.effect = 0
            state.next_play_at = None
            state.cycle_index = 0
            state.active = False
            pattern = self.patterns[level]
            if side in self.transactions and level > 0 and pattern.effect > 0:
                state.applied_level = level
                state.effect = pattern.effect
                state.next_play_at = now
                state.active = True
        self.tick(now)

    def tick(self, now: float | None = None) -> None:
        now = self.clock() if now is None else float(now)
        for side in VALID_SIDES:
            state = self._states[side]
            if not state.active or state.next_play_at is None or state.next_play_at > now:
                continue
            self._play(side, state.effect)
            state.cycle_index += 1
            interval_s = self.patterns[state.applied_level].repeat_interval_ms / 1000.0
            state.next_play_at = now + interval_s

    def stop_side(self, side: str) -> None:
        side = normalize_side(side)
        state = self._states[side]
        state.requested_level = 0
        state.applied_level = 0
        state.effect = 0
        state.next_play_at = None
        state.cycle_index = 0
        state.active = False
        self._stop_hardware(side)

    def stop_all(self) -> None:
        for side in VALID_SIDES:
            self.stop_side(side)

    def status(self) -> dict[str, object]:
        side_states = {
            side: {
                "requested_level": state.requested_level,
                "applied_level": state.applied_level,
                "effect": state.effect,
                "next_play_at": state.next_play_at,
                "cycle_index": state.cycle_index,
                "active": state.active,
                "play_count": state.play_count,
                "error_count": state.error_count,
                "last_error": state.last_error,
            }
            for side, state in self._states.items()
        }
        return {
            "backend": "tm6605_lra",
            "levels": {side: state.applied_level for side, state in self._states.items()},
            "sides": side_states,
            "pending_by_side": {
                side: int(state.active) for side, state in self._states.items()
            },
            "play_count": {side: state.play_count for side, state in self._states.items()},
            "error_count": {side: state.error_count for side, state in self._states.items()},
            "last_error": {side: state.last_error for side, state in self._states.items()},
            "last_write_mono_s": dict(self._last_write_mono_s),
            "i2c": {side: tx.status() for side, tx in self.transactions.items()},
        }

    def _play(self, side: str, effect: int) -> None:
        transaction = self.transactions.get(side)
        if transaction is None:
            return

        def operation(device: object) -> None:
            device.write(bytes((TM6605_EFFECT_REGISTER, effect)))  # type: ignore[attr-defined]
            device.write(bytes((TM6605_PLAY_REGISTER, 1)))  # type: ignore[attr-defined]

        try:
            transaction.execute(operation)
            self._last_write_mono_s[side] = self.clock()
            self._states[side].play_count += 1
        except Exception as exc:
            self._record_error(side, exc)
            raise

    def _stop_hardware(self, side: str) -> None:
        transaction = self.transactions.get(side)
        if transaction is None:
            return
        try:
            transaction.execute(
                lambda device: device.write(bytes((TM6605_PLAY_REGISTER, 0)))
            )
            self._last_write_mono_s[side] = self.clock()
        except Exception as exc:
            self._record_error(side, exc)
            raise

    def _record_error(self, side: str, exc: Exception) -> None:
        self._states[side].error_count += 1
        self._states[side].last_error = f"{type(exc).__name__}: {exc}"


class LegacyPwmHapticBackend:
    def __init__(
        self,
        pwm: object,
        *,
        period_ns: int,
        level_duty_percent: Mapping[int | str, tuple[int, int] | list[int]],
    ) -> None:
        self.pwm = pwm
        self.period_ns = int(period_ns)
        self.level_duty_percent = level_duty_percent
        self._levels = {side: 0 for side in VALID_SIDES}
        self._last_write_mono_s: dict[str, float | None] = {
            side: None for side in VALID_SIDES
        }

    def preflight(self) -> None:
        self.pwm.preflight()  # type: ignore[attr-defined]

    def setup(self) -> None:
        self.pwm.setup()  # type: ignore[attr-defined]

    def apply_levels(self, levels: Mapping[str, int], now: float | None = None) -> None:
        del now
        for side in VALID_SIDES:
            self._levels[side] = normalize_level(levels.get(side, 0))
        self.pwm.apply(  # type: ignore[attr-defined]
            duties_for_levels(self._levels, self.period_ns, self.level_duty_percent)
        )
        completed_at = time.monotonic()
        self._last_write_mono_s = {side: completed_at for side in VALID_SIDES}

    def tick(self, now: float | None = None) -> None:
        del now

    def stop_side(self, side: str) -> None:
        self._levels[normalize_side(side)] = 0
        self.apply_levels(self._levels)

    def stop_all(self) -> None:
        self._levels = {side: 0 for side in VALID_SIDES}
        self.pwm.stop_all()  # type: ignore[attr-defined]

    def status(self) -> dict[str, object]:
        return {
            "backend": "legacy_pwm",
            "levels": dict(self._levels),
            "last_write_mono_s": dict(self._last_write_mono_s),
        }


class DryRunHapticBackend:
    def __init__(self) -> None:
        self._levels = {side: 0 for side in VALID_SIDES}

    def preflight(self) -> None:
        return None

    def setup(self) -> None:
        self.stop_all()

    def apply_levels(self, levels: Mapping[str, int], now: float | None = None) -> None:
        del now
        self._levels = {side: normalize_level(levels.get(side, 0)) for side in VALID_SIDES}

    def tick(self, now: float | None = None) -> None:
        del now

    def stop_side(self, side: str) -> None:
        self._levels[normalize_side(side)] = 0

    def stop_all(self) -> None:
        self._levels = {side: 0 for side in VALID_SIDES}

    def status(self) -> dict[str, object]:
        return {"backend": "dry_run", "levels": dict(self._levels)}
