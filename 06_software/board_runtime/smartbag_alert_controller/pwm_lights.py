from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from alert_core import VALID_SIDES, normalize_level, normalize_side


# The former vibration PWM signals are unused after the TM6605 migration.
# Pin7 is PWM0_OUT10_0_P (left light); Pin32 is PWM0_OUT1_0_P (right light).
LIGHT_PWM = {
    "left": {
        "chip": 0,
        "channel": 10,
        "pinmux": ("0x102F0110", "0x1205", "Pin7 PWM0_OUT10_0_P"),
    },
    "right": {
        "chip": 0,
        "channel": 1,
        "pinmux": ("0x102F01EC", "0x1201", "Pin32 PWM0_OUT1_0_P"),
    },
}
PWM_PERIOD_NS = 1_000_000  # 1 kHz: well above visible flicker.
LEVEL3_DUTY_PERCENT = 50
LEVEL3_DURATION_S = 1.0
LEVEL4_DUTY_PERCENT = 80
LEVEL4_PULSE_ON_S = 0.20
LEVEL4_PULSE_OFF_S = 0.20
LEVEL4_PULSE_COUNT = 3


@dataclass(frozen=True)
class LightStep:
    at: float
    side: str
    enabled: bool
    duty_percent: int = 0


class LinuxSysfsPwm:
    """Small sysfs PWM adapter, kept separate so timing can be unit-tested."""

    def __init__(self, root: Path = Path("/sys/class/pwm"), dry_run: bool = False) -> None:
        self.root = root
        self.dry_run = dry_run

    def setup_channel(self, chip: int, channel: int, period_ns: int) -> None:
        channel_dir = self.root / f"pwmchip{chip}" / f"pwm{channel}"
        if self.dry_run:
            self._write(self.root / f"pwmchip{chip}" / "export", str(channel), f"export pwmchip{chip}/pwm{channel}")
            self._write(channel_dir / "period", str(period_ns), f"set pwmchip{chip}/pwm{channel} period")
            self._write(channel_dir / "duty_cycle", "0", f"clear pwmchip{chip}/pwm{channel} duty")
            return
        if not channel_dir.exists():
            self._write(self.root / f"pwmchip{chip}" / "export", str(channel), f"export pwmchip{chip}/pwm{channel}")
            deadline = time.monotonic() + 1.0
            while not channel_dir.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not channel_dir.exists():
                raise RuntimeError(f"timed out waiting for pwmchip{chip}/pwm{channel} after export")
        enable_path = channel_dir / "enable"
        if enable_path.read_text(encoding="ascii").strip() == "1":
            self._write(enable_path, "0", f"disable pwmchip{chip}/pwm{channel}")
        self._write(channel_dir / "period", str(period_ns), f"set pwmchip{chip}/pwm{channel} period")
        self._write(channel_dir / "duty_cycle", "0", f"clear pwmchip{chip}/pwm{channel} duty")

    def set_output(self, chip: int, channel: int, period_ns: int, duty_percent: int, enabled: bool) -> None:
        channel_dir = self.root / f"pwmchip{chip}" / f"pwm{channel}"
        duty_ns = period_ns * max(0, min(100, duty_percent)) // 100 if enabled else 0
        self._write(channel_dir / "duty_cycle", str(duty_ns), f"set pwmchip{chip}/pwm{channel} duty={duty_percent}%")
        self._write(channel_dir / "enable", "1" if enabled else "0", f"{'enable' if enabled else 'disable'} pwmchip{chip}/pwm{channel}")

    def _write(self, path: Path, value: str, label: str) -> None:
        if self.dry_run:
            print(f"DRY pwm {label}: {path} <- {value}", flush=True)
            return
        path.write_text(value, encoding="ascii")


class PwmLights:
    """Drives one small-signal PWM light module per warning side.

    Level 3 turns the side light on at 50% PWM for one second.  Level 4 emits
    three 80% PWM pulses (200 ms on / 200 ms off).  Levels 1/2 and clear stop
    the side immediately.
    """

    def __init__(
        self,
        pwm: LinuxSysfsPwm,
        *,
        period_ns: int = PWM_PERIOD_NS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.pwm = pwm
        self.period_ns = period_ns
        self.clock = clock
        self._levels = {side: 0 for side in VALID_SIDES}
        self._pending: list[LightStep] = []

    def setup(self, skip_pinmux: bool = False) -> None:
        if not skip_pinmux:
            for spec in LIGHT_PWM.values():
                address, value, label = spec["pinmux"]
                if self.pwm.dry_run:
                    print(f"DRY bspmm {address} {value}  # {label}", flush=True)
                else:
                    subprocess.run(["bspmm", address, value], check=True)
        for spec in LIGHT_PWM.values():
            self.pwm.setup_channel(spec["chip"], spec["channel"], self.period_ns)

    def set_levels(self, levels: Mapping[str, int], now: float | None = None) -> None:
        now = self.clock() if now is None else now
        normalized = {side: 0 for side in VALID_SIDES}
        for side, level in levels.items():
            normalized[normalize_side(side)] = normalize_level(level)
        for side in VALID_SIDES:
            level = normalized[side]
            if level == self._levels[side]:
                continue
            self._pending = [step for step in self._pending if step.side != side]
            self._set_output(side, False)
            self._levels[side] = level
            if level == 3:
                self._pending.extend((
                    LightStep(now, side, True, LEVEL3_DUTY_PERCENT),
                    LightStep(now + LEVEL3_DURATION_S, side, False),
                ))
            elif level == 4:
                for pulse in range(LEVEL4_PULSE_COUNT):
                    start = now + pulse * (LEVEL4_PULSE_ON_S + LEVEL4_PULSE_OFF_S)
                    self._pending.append(LightStep(start, side, True, LEVEL4_DUTY_PERCENT))
                    self._pending.append(LightStep(start + LEVEL4_PULSE_ON_S, side, False))
        self.tick(now)

    def tick(self, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        ready = [step for step in self._pending if step.at <= now]
        self._pending = [step for step in self._pending if step.at > now]
        for step in sorted(ready, key=lambda item: item.at):
            self._set_output(step.side, step.enabled, step.duty_percent)

    def stop_all(self) -> None:
        self._pending.clear()
        for side in VALID_SIDES:
            self._set_output(side, False)
            self._levels[side] = 0

    def _set_output(self, side: str, enabled: bool, duty_percent: int = 0) -> None:
        spec = LIGHT_PWM[side]
        self.pwm.set_output(spec["chip"], spec["channel"], self.period_ns, duty_percent, enabled)
