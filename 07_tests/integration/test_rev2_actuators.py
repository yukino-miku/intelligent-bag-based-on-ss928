from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "06_software" / "board_runtime" / "common"
CONTROLLER = ROOT / "06_software" / "board_runtime" / "smartbag_alert_controller"
sys.path[:0] = [str(COMMON), str(CONTROLLER)]

from hardware_profile import pin_conflicts, validate_hardware_profile  # noqa: E402
from haptics import Tm6605HapticBackend  # noqa: E402
from i2c_mux import I2cMuxTransaction  # noqa: E402
from lights import LinuxSysfsPwm, LightPattern, PwmChannelSpec, PwmLightBackend  # noqa: E402


class FakeAdapter:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []
        self.handle = 0

    def open(self, device: str) -> object:
        self.handle += 1
        self.events.append((self.handle, "open", device))
        return self.handle

    def close(self, handle: object) -> None:
        self.events.append((handle, "close"))

    def set_address(self, handle: object, address: int) -> None:
        self.events.append((handle, "address", address))

    def write(self, handle: object, data: bytes) -> None:
        self.events.append((handle, "write", bytes(data)))

    def read(self, handle: object, length: int) -> bytes:
        self.events.append((handle, "read", length))
        return bytes(length)


class FakePwm:
    def __init__(self) -> None:
        self.outputs: list[tuple[int, int, int, int, bool]] = []

    def list_chips(self) -> list[dict[str, object]]:
        return [{"chip": 0, "npwm": 16, "path": "/mock/pwmchip0"}]

    def resolve_chip(self, requested: int | str, channel: int) -> int:
        return 0

    def setup_channel(self, chip: int, channel: int, period_ns: int) -> Path:
        return Path(f"/mock/pwmchip{chip}/pwm{channel}")

    def set_output(self, chip: int, channel: int, period_ns: int, duty_percent: int, enabled: bool) -> None:
        self.outputs.append((chip, channel, period_ns, duty_percent, enabled))


LEVEL_EFFECTS = {
    "0": {"effect": 0, "count": 0, "interval_ms": 0},
    "1": {"effect": 0, "count": 0, "interval_ms": 0},
    "2": {"effect": 0, "count": 0, "interval_ms": 0},
    "3": {"effect": 15, "count": 3, "interval_ms": 750},
    "4": {"effect": 14, "count": 3, "interval_ms": 300},
}

LIGHT_PATTERNS = {
    "0": {"duty_percent": 0, "on_ms": 0, "off_ms": 0, "count": 0},
    "1": {"duty_percent": 0, "on_ms": 0, "off_ms": 0, "count": 0},
    "2": {"duty_percent": 0, "on_ms": 0, "off_ms": 0, "count": 0},
    "3": {"duty_percent": 50, "on_ms": 1000, "off_ms": 0, "count": 1},
    "4": {"duty_percent": 80, "on_ms": 200, "off_ms": 200, "count": 3},
}


def rev2_profile() -> dict[str, object]:
    return {
        "profile": "rev2_tm6605_mr20",
        "i2c_mux": {
            "enabled": True,
            "required": True,
            "channels": {"bmi270": 0, "left_haptic": 1, "right_haptic": 2},
        },
        "imu": {"required": True},
        "haptics": {"backend": "tm6605_lra", "required": True},
        "lights": {
            "enabled": True,
            "required": False,
            "left": {"pin": 7},
            "right": {"pin": 32},
        },
        "radar": {"enabled": True, "required": False},
        "audio": {"enabled": False, "required": False},
    }


class Tm6605BackendTest(unittest.TestCase):
    def test_effect_and_play_register_share_one_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = FakeAdapter()
            lock = str(Path(temp_dir) / "mux.lock")
            transactions = {
                side: I2cMuxTransaction(
                    "/dev/i2c-0", 0x2D, mux_address=0x70, mux_channel=channel,
                    lock_file=lock, adapter=adapter,
                )
                for side, channel in (("left", 1), ("right", 2))
            }
            backend = Tm6605HapticBackend(transactions, LEVEL_EFFECTS, clock=lambda: 10.0)
            backend.apply_levels({"left": 3, "right": 0}, now=10.0)
            writes = [event[2] for event in adapter.events if event[1] == "write"]
            self.assertEqual([b"\x02", b"\x04\x0f", b"\x0c\x01"], writes)
            opens = sum(1 for event in adapter.events if event[1] == "open")
            self.assertEqual(1, opens)
            backend.apply_levels({"left": 3, "right": 0}, now=10.1)
            self.assertEqual(2, backend.status()["pending_by_side"]["left"])
            backend.tick(10.75)
            backend.stop_side("left")
            self.assertEqual(0, backend.status()["pending_by_side"]["left"])

    def test_left_and_right_schedules_are_independent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = FakeAdapter()
            lock = str(Path(temp_dir) / "mux.lock")
            backend = Tm6605HapticBackend(
                {
                    "left": I2cMuxTransaction("/dev/i2c-0", 0x2D, mux_address=0x70, mux_channel=1, lock_file=lock, adapter=adapter),
                    "right": I2cMuxTransaction("/dev/i2c-0", 0x2D, mux_address=0x70, mux_channel=2, lock_file=lock, adapter=adapter),
                },
                LEVEL_EFFECTS,
            )
            backend.apply_levels({"left": 3, "right": 4}, now=1.0)
            backend.stop_side("left")
            status = backend.status()
            self.assertEqual(0, status["pending_by_side"]["left"])
            self.assertEqual(2, status["pending_by_side"]["right"])


class PwmLightBackendTest(unittest.TestCase):
    def test_level_patterns_and_same_state_do_not_requeue(self) -> None:
        pwm = FakePwm()
        backend = PwmLightBackend(
            pwm,  # type: ignore[arg-type]
            {
                "left": PwmChannelSpec("left", 10, 7, 0),
                "right": PwmChannelSpec("right", 1, 32, 0),
            },
            LIGHT_PATTERNS,
            period_ns=1_000_000,
        )
        backend.setup()
        pwm.outputs.clear()
        backend.apply_levels({"left": 3, "right": 0}, now=2.0)
        self.assertIn((0, 10, 1_000_000, 50, True), pwm.outputs)
        pending = backend.status()["pending_by_side"]["left"]
        backend.apply_levels({"left": 3, "right": 0}, now=2.1)
        self.assertEqual(pending, backend.status()["pending_by_side"]["left"])
        backend.tick(3.0)
        self.assertEqual((0, 10, 1_000_000, 0, False), pwm.outputs[-1])

    def test_sysfs_setup_clears_old_duty_before_smaller_period(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            channel = Path(temp_dir) / "pwmchip0" / "pwm10"
            channel.mkdir(parents=True)
            (channel.parent / "npwm").write_text("16\n", encoding="ascii")
            (channel / "enable").write_text("1\n", encoding="ascii")
            (channel / "period").write_text("1000000\n", encoding="ascii")
            (channel / "duty_cycle").write_text("900000\n", encoding="ascii")
            pwm = LinuxSysfsPwm(Path(temp_dir))
            pwm.setup_channel(0, 10, 500000)
            self.assertEqual("0", (channel / "enable").read_text(encoding="ascii").strip())
            self.assertEqual("0", (channel / "duty_cycle").read_text(encoding="ascii").strip())
            self.assertEqual("500000", (channel / "period").read_text(encoding="ascii").strip())

    def test_invalid_pattern_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            LightPattern.from_mapping({"duty_percent": 101, "count": 1})


class HardwareProfileTest(unittest.TestCase):
    def test_rev2_profile_has_no_pin_conflicts(self) -> None:
        profile = rev2_profile()
        validate_hardware_profile(profile)
        self.assertEqual({}, pin_conflicts(profile))

    def test_legacy_pwm_and_rev2_lights_cannot_share_pin7_or_pin32(self) -> None:
        profile = rev2_profile()
        profile["profile"] = "legacy_pwm_haptics"
        profile["haptics"] = {"backend": "legacy_pwm", "required": True}
        conflicts = pin_conflicts(profile)
        self.assertEqual({7, 32}, set(conflicts))
        with self.assertRaisesRegex(ValueError, "Pin7"):
            validate_hardware_profile(profile)


if __name__ == "__main__":
    unittest.main()
