from __future__ import annotations

from contextlib import contextmanager
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = ROOT / "06_software" / "board_runtime" / "smartbag_alert_controller"
COMMON = ROOT / "06_software" / "board_runtime" / "common"
for module_dir in (CONTROLLER, COMMON):
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))

from alert_core import AlertOutput  # noqa: E402
from pwm_lights import PwmLights  # noqa: E402
from smartbag_alert_controller import apply_output  # noqa: E402
from tm6605_haptics import TM6605_ADDRESS, Tm6605Haptics  # noqa: E402


class RecordingI2cBus:
    dry_run = True

    def __init__(self) -> None:
        self.writes: list[tuple[int, bytes]] = []
        self.transactions = 0

    @contextmanager
    def transaction(self):
        self.transactions += 1
        yield

    def write_to(self, address: int, payload: bytes, _label: str) -> None:
        self.writes.append((address, payload))


class RecordingOutputDevice:
    def __init__(self) -> None:
        self.levels: list[dict[str, int]] = []
        self.audio: list[str | None] = []
        self.duties: list[dict[str, int]] = []

    def set_levels(self, levels: dict[str, int]) -> None:
        self.levels.append(dict(levels))

    def request(self, clip: str | None) -> None:
        self.audio.append(clip)

    def apply(self, duties: dict[str, int]) -> None:
        self.duties.append(dict(duties))


class RecordingPwmBackend:
    dry_run = True

    def __init__(self) -> None:
        self.outputs: list[tuple[int, int, int, int, bool]] = []

    def set_output(self, chip: int, channel: int, period_ns: int, duty_percent: int, enabled: bool) -> None:
        self.outputs.append((chip, channel, period_ns, duty_percent, enabled))


class SandaHardwareIntegrationTest(unittest.TestCase):
    def test_tca_channels_are_unique_for_bmi_and_both_haptics(self) -> None:
        bmi = json.loads(
            (ROOT / "06_software/board_runtime/bmi270_backpack/config.example.json").read_text(encoding="utf-8")
        )
        controller = json.loads(
            (ROOT / "09_deliverables/board_deploy/config.example.json").read_text(encoding="utf-8")
        )
        channels = {
            int(bmi["device"]["i2c_mux_channel"]),
            int(controller["outputs"]["left_tm6605_channel"]),
            int(controller["outputs"]["right_tm6605_channel"]),
        }
        self.assertEqual({0, 1, 2}, channels)
        self.assertEqual("0x70", bmi["device"]["i2c_mux_addr"])
        self.assertEqual("0x70", controller["outputs"]["tm6605_mux_address"])

    def test_tm6605_channel_select_and_register_write_share_transaction(self) -> None:
        bus = RecordingI2cBus()
        haptics = Tm6605Haptics(bus, mux_address=0x70, channels={"left": 1, "right": 2})

        haptics.set_levels({"left": 1, "right": 0}, now=1.0)

        self.assertGreaterEqual(bus.transactions, 2)
        self.assertIn((0x70, b"\x02"), bus.writes)
        self.assertTrue(any(address == TM6605_ADDRESS for address, _payload in bus.writes))

    def test_formal_configs_leave_ble_to_controller_only(self) -> None:
        bmi = json.loads(
            (ROOT / "06_software/board_runtime/bmi270_backpack/config.example.json").read_text(encoding="utf-8")
        )
        gnss = json.loads(
            (ROOT / "06_software/board_runtime/dx_gp21_tracker/config.ss928_uart4.json").read_text(encoding="utf-8")
        )
        deploy = json.loads((ROOT / "09_deliverables/board_deploy/config.example.json").read_text(encoding="utf-8"))
        self.assertFalse(bmi["output"]["ble_enabled"])
        self.assertFalse(gnss["output"]["ble_enabled"])
        self.assertEqual("SS928-SmartBag", deploy["ble"]["name"])
        self.assertIn("--no-ble", deploy["modules"]["imu"]["command"])
        self.assertIn("--no-ble", deploy["modules"]["gnss"]["command"])

    def test_controller_routes_one_level_to_haptics_lights_and_audio(self) -> None:
        pwm = RecordingOutputDevice()
        haptics = RecordingOutputDevice()
        lights = RecordingOutputDevice()
        audio = RecordingOutputDevice()
        output = AlertOutput(
            duties_ns={"left_1": 1},
            audio_clip="L3",
            levels={"left": 3, "right": 0},
        )

        apply_output(output, pwm, audio, haptics, lights)

        self.assertEqual([], pwm.duties)
        self.assertEqual([{"left": 3, "right": 0}], haptics.levels)
        self.assertEqual([{"left": 3, "right": 0}], lights.levels)
        self.assertEqual(["L3"], audio.audio)

    def test_pwm_light_policy_uses_side_specific_level_three_and_four_patterns(self) -> None:
        pwm = RecordingPwmBackend()
        lights = PwmLights(pwm, clock=lambda: 10.0)

        lights.set_levels({"left": 3, "right": 4}, now=10.0)

        self.assertIn((0, 10, 1_000_000, 50, True), pwm.outputs)
        self.assertIn((0, 1, 1_000_000, 80, True), pwm.outputs)

    def test_mr20_workers_have_distinct_side_port_and_source_address(self) -> None:
        config = json.loads(
            (ROOT / "06_software/board_runtime/mr20_radar/config.example.json").read_text(encoding="utf-8")
        )
        enabled = [item for item in config["radars"] if item["enabled"]]
        self.assertEqual({"left", "right"}, {item["side"] for item in enabled})
        self.assertEqual(len(enabled), len({item["port"] for item in enabled}))
        self.assertEqual(len(enabled), len({item["radar_ip"] for item in enabled}))
        self.assertTrue(all(item["bind_host"] == "0.0.0.0" for item in enabled))


if __name__ == "__main__":
    unittest.main()
