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
    count: int
    interval_ms: int

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "EffectPattern":
        effect = int(raw.get("effect", 0))
        count = int(raw.get("count", 0))
        interval_ms = int(raw.get("interval_ms", 0))
        if effect not in range(256) or count < 0 or interval_ms < 0:
            raise ValueError("invalid TM6605 effect pattern")
        return cls(effect, count, interval_ms)


@dataclass(frozen=True)
class ScheduledEffect:
    at: float
    side: str
    effect: int


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
        self._levels = {side: 0 for side in VALID_SIDES}
        self._pending: list[ScheduledEffect] = []
        self._play_count = {side: 0 for side in VALID_SIDES}
        self._errors = {side: 0 for side in VALID_SIDES}
        self._last_error = {side: "" for side in VALID_SIDES}

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
            if level == self._levels[side]:
                continue
            self._pending = [item for item in self._pending if item.side != side]
            if self._levels[side] > 0:
                self._stop_hardware(side)
            self._levels[side] = level
            pattern = self.patterns[level]
            if side in self.transactions and pattern.effect > 0 and pattern.count > 0:
                self._pending.extend(
                    ScheduledEffect(now + index * pattern.interval_ms / 1000.0, side, pattern.effect)
                    for index in range(pattern.count)
                )
        self.tick(now)

    def tick(self, now: float | None = None) -> None:
        now = self.clock() if now is None else float(now)
        ready = sorted((item for item in self._pending if item.at <= now), key=lambda item: item.at)
        self._pending = [item for item in self._pending if item.at > now]
        for item in ready:
            self._play(item.side, item.effect)

    def stop_side(self, side: str) -> None:
        side = normalize_side(side)
        self._pending = [item for item in self._pending if item.side != side]
        self._levels[side] = 0
        self._stop_hardware(side)

    def stop_all(self) -> None:
        self._pending.clear()
        for side in VALID_SIDES:
            self._levels[side] = 0
            self._stop_hardware(side)

    def status(self) -> dict[str, object]:
        return {
            "backend": "tm6605_lra",
            "levels": dict(self._levels),
            "pending_by_side": {
                side: sum(1 for item in self._pending if item.side == side) for side in VALID_SIDES
            },
            "play_count": dict(self._play_count),
            "error_count": dict(self._errors),
            "last_error": dict(self._last_error),
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
            self._play_count[side] += 1
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
        except Exception as exc:
            self._record_error(side, exc)
            raise

    def _record_error(self, side: str, exc: Exception) -> None:
        self._errors[side] += 1
        self._last_error[side] = f"{type(exc).__name__}: {exc}"


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

    def tick(self, now: float | None = None) -> None:
        del now

    def stop_side(self, side: str) -> None:
        self._levels[normalize_side(side)] = 0
        self.apply_levels(self._levels)

    def stop_all(self) -> None:
        self._levels = {side: 0 for side in VALID_SIDES}
        self.pwm.stop_all()  # type: ignore[attr-defined]

    def status(self) -> dict[str, object]:
        return {"backend": "legacy_pwm", "levels": dict(self._levels)}


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

