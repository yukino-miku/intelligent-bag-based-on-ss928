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
from smartbag_alert_controller import AudioPlayer, ManagedActuator, alert_event_ble_payload  # noqa: E402
from alert_core import AlertEvent  # noqa: E402
from output_policy import OutputPolicy  # noqa: E402


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


class RecoveringActuatorBackend:
    def __init__(self, *, fail_first_setup: bool = False) -> None:
        self.fail_first_setup = fail_first_setup
        self.setup_calls = 0
        self.applied: list[tuple[dict[str, int], float | None]] = []

    def preflight(self) -> None:
        return

    def setup(self) -> None:
        self.setup_calls += 1
        if self.fail_first_setup and self.setup_calls == 1:
            raise OSError("temporary device failure")

    def stop_all(self) -> None:
        return

    def apply_levels(self, levels: dict[str, int], now: float | None = None) -> None:
        self.applied.append((dict(levels), now))

    def tick(self, now: float | None = None) -> None:
        return

    def status(self) -> dict[str, object]:
        return {"setup_calls": self.setup_calls}


LEVEL_EFFECTS = {
    "0": {"effect": 0, "repeat_interval_ms": 0},
    "1": {"effect": 15, "repeat_interval_ms": 1800},
    "2": {"effect": 15, "repeat_interval_ms": 1000},
    "3": {"effect": 15, "repeat_interval_ms": 600},
    "4": {"effect": 14, "repeat_interval_ms": 300},
}

LIGHT_PATTERNS = {
    "0": {"duty_percent": 0, "on_ms": 0, "off_ms": 0, "repeat": False, "mode": "off"},
    "1": {"duty_percent": 0, "on_ms": 0, "off_ms": 0, "repeat": False, "mode": "off"},
    "2": {"duty_percent": 0, "on_ms": 0, "off_ms": 0, "repeat": False, "mode": "off"},
    "3": {"duty_percent": 50, "on_ms": 1000, "off_ms": 1000, "repeat": True, "mode": "slow_blink"},
    "4": {"duty_percent": 80, "on_ms": 200, "off_ms": 200, "repeat": True, "mode": "fast_blink"},
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
            self.assertEqual(1, backend.status()["pending_by_side"]["left"])
            backend.tick(10.6)
            self.assertEqual(2, backend.status()["play_count"]["left"])
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
            self.assertEqual(1, status["pending_by_side"]["right"])
            self.assertTrue(status["sides"]["right"]["active"])

    def test_heartbeat_and_long_runtime_keep_one_bounded_state_per_side(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = FakeAdapter()
            backend = Tm6605HapticBackend(
                {"left": I2cMuxTransaction("/dev/i2c-0", 0x2D, mux_address=0x70, mux_channel=1, lock_file=str(Path(temp_dir) / "mux.lock"), adapter=adapter)},
                LEVEL_EFFECTS,
            )
            backend.apply_levels({"left": 1, "right": 0}, now=0.0)
            for index in range(1000):
                backend.apply_levels({"left": 1, "right": 0}, now=index / 10.0)
            status = backend.status()
            self.assertEqual(1, status["pending_by_side"]["left"])
            self.assertGreater(status["play_count"]["left"], 1)
            self.assertLess(status["play_count"]["left"], 60)
            backend.tick(100.0)
            backend.apply_levels({"left": 4, "right": 0}, now=100.1)
            status = backend.status()
            self.assertEqual(4, status["sides"]["left"]["applied_level"])
            self.assertEqual(14, status["sides"]["left"]["effect"])


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
        backend.tick(4.0)
        self.assertEqual((0, 10, 1_000_000, 50, True), pwm.outputs[-1])
        self.assertEqual("slow_blink", backend.status()["sides"]["left"]["mode"])
        backend.apply_levels({"left": 4, "right": 0}, now=4.1)
        self.assertEqual("fast_blink", backend.status()["sides"]["left"]["mode"])

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

    def test_persistent_blink_is_bounded_and_levels_one_two_stay_off(self) -> None:
        pwm = FakePwm()
        backend = PwmLightBackend(
            pwm,  # type: ignore[arg-type]
            {"left": PwmChannelSpec("left", 10, 7, 0), "right": PwmChannelSpec("right", 1, 32, 0)},
            LIGHT_PATTERNS,
            period_ns=1_000_000,
        )
        backend.setup()
        backend.apply_levels({"left": 3, "right": 2}, now=0.0)
        for index in range(1, 1001):
            backend.tick(float(index))
            backend.apply_levels({"left": 3, "right": 2}, now=float(index))
        status = backend.status()
        self.assertEqual(1, status["pending_by_side"]["left"])
        self.assertEqual(0, status["pending_by_side"]["right"])
        self.assertEqual("off", status["sides"]["right"]["phase"])


class AudioPlayerTest(unittest.TestCase):
    def test_duplicate_requests_are_bounded_by_side_and_clear_removes_pending(self) -> None:
        player = AudioPlayer(Path("/unused"), dry_run=True)
        for _ in range(1000):
            player.apply_levels({"left": 3, "right": 0}, requested_clip="L3")
        self.assertEqual(1, player.status()["queue_depth"])
        player.apply_levels({"left": 3, "right": 4}, requested_clip="R4")
        self.assertEqual(2, player.status()["queue_depth"])
        player.clear_side("left")
        self.assertEqual({"right": "R4"}, player.status()["pending_by_side"])
        player.clear()
        self.assertEqual(0, player.status()["queue_depth"])

    def test_level_four_replaces_level_three_and_payload_exposes_outputs(self) -> None:
        player = AudioPlayer(Path("/unused"), dry_run=True)
        player.apply_levels({"left": 3, "right": 0}, requested_clip="L3")
        player.apply_levels({"left": 4, "right": 0}, requested_clip="L4")
        self.assertEqual({"left": "L4"}, player.status()["pending_by_side"])
        policy = OutputPolicy.for_profile("rev2_tm6605_mr20")
        decision = policy.decide({"left": 3, "right": 0}, "L3")
        payload = __import__("json").loads(alert_event_ble_payload(
            AlertEvent("left", 3, source="vision:left"),
            decision=decision,
            audio_enabled=True,
        ))
        self.assertEqual(3, payload["haptic_level"])
        self.assertEqual("slow_blink", payload["light_mode"])
        self.assertEqual("L3", payload["audio_clip"])
        self.assertTrue(payload["audio_enabled"])


class ManagedActuatorRecoveryTest(unittest.TestCase):
    def test_optional_backend_replays_desired_levels_after_recovery(self) -> None:
        primary = RecoveringActuatorBackend(fail_first_setup=True)
        fallback = RecoveringActuatorBackend()
        actuator = ManagedActuator(
            "lights",
            primary,
            fallback,
            {"required": False, "failure_policy": "degrade"},
        )
        actuator.initialize()
        self.assertEqual("degraded", actuator.state)
        actuator.apply_levels({"left": 3, "right": 0}, now=1.0)
        self.assertEqual(({"left": 3, "right": 0}, 1.0), fallback.applied[-1])

        self.assertTrue(actuator.retry_if_degraded(now=30.0, interval_s=30.0))
        self.assertEqual("online", actuator.state)
        self.assertEqual(({"left": 3, "right": 0}, 30.0), primary.applied[-1])
        self.assertEqual({"left": 3, "right": 0}, actuator.status()["desired_levels"])


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
