from __future__ import annotations

import errno
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol

from alert_core import VALID_SIDES, normalize_level, normalize_side


@dataclass(frozen=True)
class PwmChannelSpec:
    side: str
    channel: int
    pin: int
    chip: int | str = "auto"


@dataclass(frozen=True)
class LightPattern:
    duty_percent: int
    on_ms: int
    off_ms: int
    repeat: bool
    mode: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "LightPattern":
        pattern = cls(
            duty_percent=int(raw.get("duty_percent", 0)),
            on_ms=int(raw.get("on_ms", 0)),
            off_ms=int(raw.get("off_ms", 0)),
            repeat=bool(raw.get("repeat", int(raw.get("count", 0)) > 0)),
            mode=str(raw.get("mode", "off")),
        )
        if not 0 <= pattern.duty_percent <= 100 or min(pattern.on_ms, pattern.off_ms) < 0:
            raise ValueError("invalid light pattern")
        if pattern.repeat and (
            pattern.duty_percent <= 0 or pattern.on_ms <= 0 or pattern.off_ms <= 0
        ):
            raise ValueError("repeating light pattern requires duty, on_ms and off_ms > 0")
        return pattern


@dataclass
class LightSideState:
    current_level: int = 0
    phase: str = "off"
    next_transition: float | None = None
    cycle_count: int = 0
    duty_percent: int = 0
    mode: str = "off"


class LightBackend(Protocol):
    def preflight(self) -> None: ...

    def setup(self) -> None: ...

    def apply_levels(self, levels: Mapping[str, int], now: float | None = None) -> None: ...

    def tick(self, now: float | None = None) -> None: ...

    def stop_side(self, side: str) -> None: ...

    def stop_all(self) -> None: ...

    def status(self) -> dict[str, object]: ...


class LinuxSysfsPwm:
    def __init__(
        self,
        root: Path = Path("/sys/class/pwm"),
        *,
        export_timeout_s: float = 1.0,
        dry_run: bool = False,
    ) -> None:
        self.root = root
        self.export_timeout_s = float(export_timeout_s)
        self.dry_run = dry_run
        self.operations: list[dict[str, object]] = []

    def list_chips(self) -> list[dict[str, object]]:
        result = []
        for path in sorted(self.root.glob("pwmchip*")):
            try:
                chip = int(path.name.removeprefix("pwmchip"))
                npwm = int((path / "npwm").read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                continue
            result.append({"chip": chip, "npwm": npwm, "path": str(path)})
        return result

    def resolve_chip(self, requested: int | str, channel: int) -> int:
        chips = self.list_chips()
        if self.dry_run and not chips:
            return int(requested) if requested != "auto" else 0
        if requested != "auto":
            chip = int(requested)
            match = next((item for item in chips if item["chip"] == chip), None)
            if match is None or int(match["npwm"]) <= channel:
                raise RuntimeError(f"pwmchip{chip} does not expose channel {channel}; found={chips}")
            return chip
        candidates = [int(item["chip"]) for item in chips if int(item["npwm"]) > channel]
        if len(candidates) != 1:
            raise RuntimeError(f"PWM channel {channel} auto discovery is ambiguous: {candidates}")
        return candidates[0]

    def setup_channel(self, chip: int, channel: int, period_ns: int) -> Path:
        chip_dir = self.root / f"pwmchip{chip}"
        channel_dir = chip_dir / f"pwm{channel}"
        if self.dry_run:
            self._record(channel_dir, "setup", period_ns)
            return channel_dir
        if not channel_dir.exists():
            self._write(chip_dir / "export", str(channel))
            deadline = time.monotonic() + self.export_timeout_s
            while not channel_dir.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
        if not channel_dir.exists():
            raise RuntimeError(f"{channel_dir} did not appear after export")
        self._safe_disable_and_clear(channel_dir)
        self._write(channel_dir / "period", str(int(period_ns)))
        self._write(channel_dir / "duty_cycle", "0")
        return channel_dir

    def set_output(
        self,
        chip: int,
        channel: int,
        period_ns: int,
        duty_percent: int,
        enabled: bool,
    ) -> None:
        channel_dir = self.root / f"pwmchip{chip}" / f"pwm{channel}"
        duty_ns = int(period_ns) * max(0, min(100, int(duty_percent))) // 100 if enabled else 0
        if self.dry_run:
            self._record(channel_dir, "output", duty_ns, enabled=enabled)
            return
        if not channel_dir.exists():
            raise RuntimeError(f"{channel_dir} is not exported")
        if not enabled:
            self._write(channel_dir / "enable", "0")
            self._write(channel_dir / "duty_cycle", "0")
            return
        current_period = self._read_int(channel_dir / "period")
        if current_period != int(period_ns):
            self._safe_disable_and_clear(channel_dir)
            self._write(channel_dir / "period", str(int(period_ns)))
        self._write(channel_dir / "duty_cycle", str(duty_ns))
        self._write(channel_dir / "enable", "1")

    def _safe_disable_and_clear(self, channel_dir: Path) -> None:
        if (channel_dir / "enable").exists():
            self._write(channel_dir / "enable", "0")
        if (channel_dir / "duty_cycle").exists():
            self._write(channel_dir / "duty_cycle", "0")

    def _write(self, path: Path, value: str) -> None:
        try:
            path.write_text(value + "\n", encoding="ascii")
            self._record(path, "write", value)
        except OSError as exc:
            detail = f"PWM write failed path={path} value={value} errno={exc.errno}"
            if exc.errno == errno.EINVAL:
                detail += "; verify disable/duty=0/period/duty/enable order, channel ownership and pinmux"
            raise RuntimeError(detail) from exc

    def _read_int(self, path: Path) -> int | None:
        try:
            return int(path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            return None

    def _record(self, path: Path, operation: str, value: object, **extra: object) -> None:
        self.operations.append({"path": str(path), "operation": operation, "value": value, **extra})


class PwmLightBackend:
    def __init__(
        self,
        pwm: LinuxSysfsPwm,
        channels: Mapping[str, PwmChannelSpec],
        level_patterns: Mapping[int | str, Mapping[str, object]],
        *,
        period_ns: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.pwm = pwm
        self.channels = {normalize_side(side): spec for side, spec in channels.items()}
        if set(self.channels) != set(VALID_SIDES):
            raise ValueError("light channels must define left and right")
        self.patterns = {
            int(level): LightPattern.from_mapping(pattern)
            for level, pattern in level_patterns.items()
        }
        if set(self.patterns) != set(range(5)):
            raise ValueError("lights.level_patterns must define levels 0..4")
        self.period_ns = int(period_ns)
        self.clock = clock
        self._resolved_chips: dict[str, int] = {}
        self._states = {side: LightSideState() for side in VALID_SIDES}
        self._errors = 0
        self._last_error = ""
        self._last_write_mono_s: dict[str, float | None] = {
            side: None for side in VALID_SIDES
        }

    def preflight(self) -> None:
        for side, spec in self.channels.items():
            self._resolved_chips[side] = self.pwm.resolve_chip(spec.chip, spec.channel)

    def setup(self) -> None:
        self.preflight()
        for side, spec in self.channels.items():
            self.pwm.setup_channel(self._resolved_chips[side], spec.channel, self.period_ns)
        self.stop_all()

    def apply_levels(self, levels: Mapping[str, int], now: float | None = None) -> None:
        now = self.clock() if now is None else float(now)
        for side in VALID_SIDES:
            level = normalize_level(levels.get(side, 0))
            state = self._states[side]
            if level == state.current_level:
                continue
            self._set_output(side, False)
            state.current_level = level
            state.phase = "off"
            state.next_transition = None
            state.cycle_count = 0
            state.duty_percent = 0
            state.mode = "off"
            pattern = self.patterns[level]
            if pattern.repeat:
                state.phase = "on"
                state.next_transition = now + pattern.on_ms / 1000.0
                state.duty_percent = pattern.duty_percent
                state.mode = pattern.mode
                self._set_output(side, True, pattern.duty_percent)

    def tick(self, now: float | None = None) -> None:
        now = self.clock() if now is None else float(now)
        for side in VALID_SIDES:
            state = self._states[side]
            if state.next_transition is None or state.next_transition > now:
                continue
            pattern = self.patterns[state.current_level]
            if state.phase == "on":
                self._set_output(side, False)
                state.phase = "off"
                state.next_transition = now + pattern.off_ms / 1000.0
            else:
                self._set_output(side, True, pattern.duty_percent)
                state.phase = "on"
                state.cycle_count += 1
                state.next_transition = now + pattern.on_ms / 1000.0

    def stop_side(self, side: str) -> None:
        side = normalize_side(side)
        self._states[side] = LightSideState()
        self._set_output(side, False)

    def stop_all(self) -> None:
        for side in VALID_SIDES:
            self._states[side] = LightSideState()
            if side in self._resolved_chips:
                self._set_output(side, False)

    def status(self) -> dict[str, object]:
        side_states = {
            side: {
                "current_level": state.current_level,
                "phase": state.phase,
                "next_transition": state.next_transition,
                "cycle_count": state.cycle_count,
                "duty_percent": state.duty_percent,
                "mode": state.mode,
            }
            for side, state in self._states.items()
        }
        return {
            "backend": "pwm_lights",
            "levels": {side: state.current_level for side, state in self._states.items()},
            "sides": side_states,
            "resolved_chips": dict(self._resolved_chips),
            "pending_by_side": {
                side: int(state.next_transition is not None)
                for side, state in self._states.items()
            },
            "error_count": self._errors,
            "last_error": self._last_error,
            "last_write_mono_s": dict(self._last_write_mono_s),
        }

    def _set_output(self, side: str, enabled: bool, duty_percent: int = 0) -> None:
        spec = self.channels[side]
        try:
            self.pwm.set_output(
                self._resolved_chips[side], spec.channel, self.period_ns, duty_percent, enabled
            )
            self._last_write_mono_s[side] = self.clock()
        except Exception as exc:
            self._errors += 1
            self._last_error = f"{type(exc).__name__}: {exc}"
            raise


class DisabledLightBackend:
    def preflight(self) -> None:
        return None

    def setup(self) -> None:
        return None

    def apply_levels(self, levels: Mapping[str, int], now: float | None = None) -> None:
        del levels, now

    def tick(self, now: float | None = None) -> None:
        del now

    def stop_side(self, side: str) -> None:
        normalize_side(side)

    def stop_all(self) -> None:
        return None

    def status(self) -> dict[str, object]:
        return {"backend": "disabled", "levels": {"left": 0, "right": 0}}
