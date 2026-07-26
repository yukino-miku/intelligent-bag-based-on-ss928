from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from mt5710_connectivity import (  # noqa: E402
    AtSession,
    Mt5710CallNotifier,
    Mt5710SmsNotifier,
    RunResult,
    build_ucs2_sms,
    build_sensor_commands,
    choose_apn,
    discover_ncm_interface,
    parse_registration,
    prepare_network,
    route_uses_interface,
    run_application,
)


class PolicyTests(unittest.TestCase):
    def test_apn_override_and_operator_mapping(self) -> None:
        self.assertEqual(choose_apn("CHINA TELECOM", "460031234", ""), "ctnet")
        self.assertEqual(choose_apn("CHINA MOBILE", "460001234", ""), "cmnet")
        self.assertEqual(choose_apn("CHN-UNICOM", "460011234", ""), "3gnet")
        self.assertEqual(choose_apn("", "460111234", "private.apn"), "private.apn")

    def test_registration_requires_registered_and_attached(self) -> None:
        ready = ["+CEREG: 2,1", "+C5GREG: 2,1,\"175006\"", "+CGATT: 1", "OK"]
        searching = ["+CEREG: 2,2", "+C5GREG: 2,2", "+CGATT: 1", "OK"]
        detached = ["+CEREG: 2,1", "+CGATT: 0", "OK"]
        self.assertEqual(parse_registration(ready), (True, True))
        self.assertEqual(parse_registration(searching), (False, True))
        self.assertEqual(parse_registration(detached), (True, False))

    def test_discovers_only_cdc_ncm_interface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            net_root = Path(tmp)
            for name, driver in (("eth0", "hisi_gmac"), ("enx1234", "cdc_ncm")):
                device = net_root / name / "device"
                device.mkdir(parents=True)
                (device / "uevent").write_text(f"DRIVER={driver}\n", encoding="utf-8")
            self.assertEqual(discover_ncm_interface(net_root), "enx1234")

    def test_ncm_discovery_rejects_ambiguous_modems_and_can_match_usb_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            net_root = Path(tmp)
            for name, product in (("enx1111", "1111"), ("enx5710", "1573")):
                device = net_root / name / "device"
                device.mkdir(parents=True)
                (device / "uevent").write_text("DRIVER=cdc_ncm\n", encoding="utf-8")
                (device / "idVendor").write_text("12d1\n", encoding="ascii")
                (device / "idProduct").write_text(product + "\n", encoding="ascii")
            with self.assertRaisesRegex(RuntimeError, "multiple cdc_ncm"):
                discover_ncm_interface(net_root)
            self.assertEqual(discover_ncm_interface(net_root, ("12d1", "1573")), "enx5710")

    def test_route_must_use_requested_interface(self) -> None:
        text = "203.205.254.17 via 10.72.12.1 dev enx1234 src 10.72.12.12 uid 0"
        self.assertTrue(route_uses_interface(text, "enx1234"))
        self.assertFalse(route_uses_interface(text, "eth0"))

    def test_real_sensor_commands_never_enable_simulation(self) -> None:
        work_root = Path("/root/smartbag")
        dx_command, bmi_command = build_sensor_commands(work_root)
        joined = " ".join(dx_command + bmi_command)
        self.assertIn("dx_gp21_tracker.py", joined)
        self.assertEqual(
            bmi_command,
            [
                "python3",
                str(work_root / "imu" / "bmi270_backpack.py"),
                "--config",
                "/etc/smartbag/bmi270.json",
                "--no-ble",
            ],
        )
        self.assertEqual(dx_command.count("--no-ble"), 1)
        self.assertNotIn("--simulate", joined)

    def test_can_skip_unplugged_dx_gp21_without_skipping_bmi270(self) -> None:
        work_root = Path("/root/smartbag")
        commands = build_sensor_commands(work_root, include_gnss=False)

        joined = " ".join(part for command in commands for part in command)
        self.assertNotIn("dx_gp21_tracker.py", joined)
        self.assertEqual(
            commands,
            [[
                "python3",
                str(work_root / "imu" / "bmi270_backpack.py"),
                "--config",
                "/etc/smartbag/bmi270.json",
                "--no-ble",
            ]],
        )


class FakeAtSession:
    def __init__(self, responses: dict[str, list[str]]) -> None:
        self.responses = responses
        self.commands: list[str] = []

    def command(self, command: str, timeout_s: float = 4.0) -> list[str]:
        del timeout_s
        self.commands.append(command)
        return list(self.responses.get(command, ["OK"]))


class SmsTests(unittest.TestCase):
    def test_builds_single_ucs2_pdu_message_for_chinese_alarm(self) -> None:
        message = "检测到你的儿童遇到危险，可能发生严重摔倒，请立刻到小程序查看具体消息"

        sms = build_ucs2_sms("15500001111", message)

        self.assertEqual(sms.setup_commands, ("AT+CMMS=0", "AT+CGSMS=2", "AT+CMGF=0"))
        self.assertEqual(sms.submit_command, "AT+CMGS=82")
        self.assertEqual(
            sms.pdu_hex,
            "0015660B815105001011F10008FF44" + message.encode("utf-16-be").hex().upper(),
        )

    def test_at_session_sends_pdu_and_waits_for_message_reference(self) -> None:
        class ScriptedSession(AtSession):
            def __init__(self) -> None:
                super().__init__("unused")
                self.fd = 99
                self.commands = []
                self.cancel_count = 0
                self.responses = iter((b"\r\n> ", b"\r\n+CMGS: 42\r\n\r\nOK\r\n"))

            def _cancel_pending_sms_input(self) -> None:
                self.cancel_count += 1

            def command(self, command: str, timeout_s: float = 4.0) -> list[str]:
                del timeout_s
                self.commands.append(command)
                return ["OK"]

            def _read_until(self, predicate, timeout_s: float) -> bytes:
                del timeout_s
                response = next(self.responses)
                if not predicate(response):
                    raise AssertionError("scripted response did not satisfy read predicate")
                return response

        session = ScriptedSession()
        writes = []
        with patch(
            "mt5710_connectivity.os.write",
            side_effect=lambda fd, data: writes.append((fd, data)) or len(data),
        ), patch(
            "mt5710_connectivity._next_sms_message_reference",
            return_value=0x66,
        ):
            result = session.send_ucs2_sms("15500001111", "危险")

        self.assertEqual(session.cancel_count, 1)
        self.assertEqual(session.commands, ["AT", "AT+CMMS=0", "AT+CGSMS=2", "AT+CMGF=0"])
        self.assertEqual(writes[0], (99, b"AT+CMGS=18\r"))
        self.assertEqual(
            writes[1],
            (
                99,
                (
                    "0015660B815105001011F10008FF04"
                    + "危险".encode("utf-16-be").hex().upper()
                ).encode("ascii")
                + b"\x1a",
            ),
        )
        self.assertIn("+CMGS: 42", result)

    def test_notifier_only_sends_final_fall_alarm(self) -> None:
        sent = []

        class FakeSmsSession:
            def __enter__(self):
                return self

            def __exit__(self, *items):
                del items

            def send_ucs2_sms(self, phone: str, message: str, timeout_s: float = 30.0):
                sent.append((phone, message, timeout_s))
                return ["+CMGS: 7", "OK"]

        notifier = Mt5710SmsNotifier(
            phone="15500001111",
            message="报警",
            timeout_s=20.0,
            at_factory=lambda port, baud: FakeSmsSession(),
        )

        self.assertFalse(notifier({"signal": "HIGH_WARNING", "alarmType": "fall_detected"}))
        self.assertFalse(notifier({"signal": "FALL_ALARM", "alarmType": "other"}))
        self.assertTrue(notifier({"signal": "FALL_ALARM", "alarmType": "fall_detected"}))
        self.assertEqual(sent, [("15500001111", "报警", 20.0)])

    def test_sms_notifier_rejects_invalid_phone(self) -> None:
        with self.assertRaisesRegex(ValueError, "SMS phone"):
            Mt5710SmsNotifier(phone="not-a-phone", message="报警")

    def test_call_notifier_dials_only_final_fall_and_hangs_up_when_answered(self) -> None:
        commands = []

        class FakeCallSession:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                del exc_type, exc, traceback

            def command(self, command: str, timeout_s: float = 4.0) -> list[str]:
                del timeout_s
                commands.append(command)
                if command == "AT+CLCC":
                    return ['+CLCC: 1,0,0,0,0,"15500001111",161', "OK"]
                return ["OK"]

        class ImmediateThread:
            def __init__(self, *, target, **kwargs):
                del kwargs
                self.target = target

            def start(self):
                self.target()

        notifier = Mt5710CallNotifier(
            "15500001111",
            ring_seconds=12.0,
            poll_interval_s=0.0,
            at_factory=lambda port, baud: FakeCallSession(),
            thread_factory=ImmediateThread,
            sleep_fn=lambda seconds: None,
        )

        self.assertFalse(notifier({"signal": "HIGH_WARNING", "alarmType": "fall_detected"}))
        self.assertFalse(notifier({"signal": "FALL_ALARM", "alarmType": "other"}))
        self.assertTrue(notifier({"signal": "FALL_ALARM", "alarmType": "fall_detected"}))
        self.assertEqual(commands, ["AT", "ATD15500001111;", "AT+CLCC", "ATH"])

    def test_call_notifier_rejects_unsafe_phone_and_invalid_ring_duration(self) -> None:
        with self.assertRaisesRegex(ValueError, "call phone"):
            Mt5710CallNotifier("123;ATH")
        with self.assertRaisesRegex(ValueError, "ring duration"):
            Mt5710CallNotifier("15500001111", ring_seconds=16.0)

    def test_at_session_can_store_send_once_and_delete_pdu(self) -> None:
        class ScriptedSession(AtSession):
            def __init__(self) -> None:
                super().__init__("unused")
                self.fd = 99
                self.commands = []
                self.responses = iter((b"\r\n> ", b"\r\n+CMGW: 7\r\n\r\nOK\r\n"))

            def _cancel_pending_sms_input(self) -> None:
                pass

            def command(self, command: str, timeout_s: float = 4.0) -> list[str]:
                del timeout_s
                self.commands.append(command)
                if command == "AT+CMSS=7":
                    return ["+CMSS: 44", "OK"]
                return ["OK"]

            def _read_until(self, predicate, timeout_s: float) -> bytes:
                del timeout_s
                response = next(self.responses)
                self.assert_predicate = predicate(response)
                if not self.assert_predicate:
                    raise AssertionError("scripted response did not satisfy read predicate")
                return response

        session = ScriptedSession()
        writes = []
        with patch(
            "mt5710_connectivity.os.write",
            side_effect=lambda fd, data: writes.append((fd, data)) or len(data),
        ), patch(
            "mt5710_connectivity._next_sms_message_reference",
            return_value=0x67,
        ):
            result = session.send_ucs2_sms_via_storage("15500001111", "危险")

        self.assertEqual(session.commands[-2:], ["AT+CMSS=7", "AT+CMGD=7"])
        self.assertEqual(writes[0], (99, b"AT+CMGW=18\r"))
        self.assertTrue(writes[1][1].endswith(b"\x1a"))
        self.assertIn("+CMSS: 44", result)


class NetworkOrchestrationTests(unittest.TestCase):
    def test_reuses_an_already_active_ncm_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            net_root = Path(tmp)
            device = net_root / "enx5g" / "device"
            device.mkdir(parents=True)
            (device / "uevent").write_text("DRIVER=cdc_ncm\n", encoding="utf-8")
            at = FakeAtSession(
                {
                    "AT": ["OK"],
                    "AT+CPIN?": ["+CPIN: READY", "OK"],
                    "AT+COPS?": ['+COPS: 0,0,"CHINA TELECOM",12', "OK"],
                    "AT+CIMI": ["460031234567890", "OK"],
                    "AT+CEREG?": ["+CEREG: 2,1", "OK"],
                    "AT+C5GREG?": ["+C5GREG: 2,1", "OK"],
                    "AT+CGATT?": ["+CGATT: 1", "OK"],
                    'AT^NDISDUP=1,1,"ctnet"': ["ERROR: DUPLICATED"],
                }
            )
            calls: list[list[str]] = []

            def runner(argv: list[str], timeout_s: float = 30.0) -> RunResult:
                del timeout_s
                calls.append(argv)
                if argv[:3] == ["ip", "route", "get"]:
                    return RunResult(0, "203.205.254.17 dev enx5g src 10.72.12.12", "")
                return RunResult(0, "", "")

            result = prepare_network(
                at_session=at,
                command_runner=runner,
                sys_class_net=net_root,
                resolver=lambda host: "203.205.254.17",
                apn_override="",
            )

            self.assertEqual(result["interface"], "enx5g")
            self.assertIn(["udhcpc", "-i", "enx5g", "-q", "-n", "-t", "8", "-T", "5"], calls)

    def test_prepares_network_in_order_and_verifies_cloudbase_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            net_root = Path(tmp)
            device = net_root / "enx5g" / "device"
            device.mkdir(parents=True)
            (device / "uevent").write_text("DRIVER=cdc_ncm\n", encoding="utf-8")
            at = FakeAtSession(
                {
                    "AT": ["OK"],
                    "AT+CPIN?": ["+CPIN: READY", "OK"],
                    "AT+COPS?": ['+COPS: 0,0,"CHINA TELECOM",12', "OK"],
                    "AT+CIMI": ["460031234567890", "OK"],
                    "AT+CEREG?": ["+CEREG: 2,1", "OK"],
                    "AT+C5GREG?": ["+C5GREG: 2,1", "OK"],
                    "AT+CGATT?": ["+CGATT: 1", "OK"],
                    'AT^NDISDUP=1,1,"ctnet"': ["OK", '^NDISSTAT: 1,1,,,,"IPV4"'],
                }
            )
            calls: list[list[str]] = []

            def runner(argv: list[str], timeout_s: float = 30.0) -> RunResult:
                del timeout_s
                calls.append(argv)
                if argv[:3] == ["ip", "route", "get"]:
                    return RunResult(0, "203.205.254.17 dev enx5g src 10.72.12.12", "")
                return RunResult(0, "", "")

            result = prepare_network(
                at_session=at,
                command_runner=runner,
                sys_class_net=net_root,
                resolver=lambda host: "203.205.254.17",
                apn_override="",
            )

            self.assertEqual(result["interface"], "enx5g")
            self.assertEqual(result["apn"], "ctnet")
            self.assertIn('AT^NDISDUP=1,1,"ctnet"', at.commands)
            self.assertEqual(calls[0], ["ip", "link", "set", "enx5g", "up"])
            self.assertEqual(calls[1][:3], ["udhcpc", "-i", "enx5g"])
            self.assertEqual(calls[2], ["ip", "route", "get", "203.205.254.17"])

    def test_failed_registration_prevents_dial_and_dhcp(self) -> None:
        at = FakeAtSession(
            {
                "AT": ["OK"],
                "AT+CPIN?": ["+CPIN: READY", "OK"],
                "AT+COPS?": ['+COPS: 0,0,"CHINA TELECOM",12', "OK"],
                "AT+CIMI": ["460031234567890", "OK"],
                "AT+CEREG?": ["+CEREG: 2,2", "OK"],
                "AT+C5GREG?": ["+C5GREG: 2,2", "OK"],
                "AT+CGATT?": ["+CGATT: 0", "OK"],
            }
        )
        calls: list[list[str]] = []

        with self.assertRaisesRegex(RuntimeError, "not registered/attached"):
            prepare_network(
                at_session=at,
                command_runner=lambda argv, timeout_s=30.0: calls.append(argv),
                sys_class_net=Path("/not-used"),
                resolver=lambda host: "203.205.254.17",
                apn_override="",
            )

        self.assertFalse(any(command.startswith("AT^NDISDUP") for command in at.commands))
        self.assertEqual(calls, [])

    def test_adds_cloudbase_host_route_when_ethernet_still_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            net_root = Path(tmp)
            device = net_root / "enx5g" / "device"
            device.mkdir(parents=True)
            (device / "uevent").write_text("DRIVER=cdc_ncm\n", encoding="utf-8")
            at = FakeAtSession(
                {
                    "AT": ["OK"],
                    "AT+CPIN?": ["+CPIN: READY", "OK"],
                    "AT+COPS?": ['+COPS: 0,0,"CHINA TELECOM",12', "OK"],
                    "AT+CIMI": ["460031234567890", "OK"],
                    "AT+CEREG?": ["+CEREG: 2,1", "OK"],
                    "AT+C5GREG?": ["+C5GREG: 2,1", "OK"],
                    "AT+CGATT?": ["+CGATT: 1", "OK"],
                    'AT^NDISDUP=1,1,"ctnet"': ["OK"],
                }
            )
            route_checks = 0
            calls: list[list[str]] = []

            def runner(argv: list[str], timeout_s: float = 30.0) -> RunResult:
                nonlocal route_checks
                del timeout_s
                calls.append(argv)
                if argv[:3] == ["ip", "route", "get"]:
                    route_checks += 1
                    interface = "eth0" if route_checks == 1 else "enx5g"
                    return RunResult(0, f"203.205.254.17 dev {interface}", "")
                if argv == ["ip", "route", "show", "default", "dev", "enx5g"]:
                    return RunResult(0, "default via 10.72.12.1 dev enx5g", "")
                return RunResult(0, "", "")

            prepare_network(
                at_session=at,
                command_runner=runner,
                sys_class_net=net_root,
                resolver=lambda host: "203.205.254.17",
                apn_override="",
            )

            self.assertIn(
                ["ip", "route", "replace", "203.205.254.17/32", "via", "10.72.12.1", "dev", "enx5g"],
                calls,
            )
            self.assertEqual(route_checks, 2)

    def test_normal_runtime_checks_credentials_before_network_changes(self) -> None:
        calls: list[str] = []
        args = type(
            "Args",
            (),
            {
                "skip_network": False,
                "skip_gnss": False,
                "check_only": False,
                "port": "/dev/ttyUSB1",
                "baud": 115200,
                "apn": "",
                "work_root": Path("/root/work"),
                "supervise_sensors": True,
            },
        )()

        with self.assertRaisesRegex(RuntimeError, "SMARTBAG_UPLOAD_TOKEN"):
            run_application(
                args,
                environ={},
                prerequisite_checker=lambda root: calls.append("preflight"),
                network_preparer=lambda *items, **kwargs: calls.append("network"),
                at_factory=lambda port, baud: None,
                pinmux_configurer=lambda runner: calls.append("pinmux"),
                supervisor=lambda commands, root: calls.append("supervisor") or 0,
            )

        self.assertEqual(calls, [])

    def test_runtime_skips_gnss_when_module_is_marked_unplugged(self) -> None:
        captured: list[list[str]] = []
        args = type(
            "Args",
            (),
            {
                "skip_network": True,
                "skip_gnss": True,
                "check_only": False,
                "port": "/dev/ttyUSB1",
                "baud": 115200,
                "apn": "",
                "work_root": Path("/root/work"),
                "supervise_sensors": True,
            },
        )()

        result = run_application(
            args,
            environ={"SMARTBAG_UPLOAD_TOKEN": "test"},
            prerequisite_checker=lambda root, include_gnss=True: self.assertFalse(include_gnss),
            pinmux_configurer=lambda runner, include_gnss=True: self.assertFalse(include_gnss),
            supervisor=lambda commands, root: captured.extend(commands) or 0,
        )

        self.assertEqual(result, 0)
        self.assertEqual(
            captured,
            [[
                "python3",
                str(args.work_root.resolve() / "imu" / "bmi270_backpack.py"),
                "--config",
                "/etc/smartbag/bmi270.json",
                "--no-ble",
            ]],
        )

    def test_formal_connectivity_mode_does_not_start_sensor_processes(self) -> None:
        args = type(
            "Args",
            (),
            {
                "skip_network": True,
                "skip_gnss": False,
                "check_only": False,
                "supervise_sensors": False,
                "port": "/dev/ttyUSB1",
                "baud": 115200,
                "apn": "",
                "work_root": Path("/root/smartbag"),
            },
        )()
        calls: list[str] = []
        result = run_application(
            args,
            environ={},
            prerequisite_checker=lambda *_args: calls.append("preflight"),
            pinmux_configurer=lambda *_args: calls.append("pinmux"),
            supervisor=lambda *_args: calls.append("supervisor") or 0,
            service_waiter=lambda: calls.append("wait") or 0,
        )
        self.assertEqual(result, 0)
        self.assertEqual(calls, ["wait"])


if __name__ == "__main__":
    unittest.main()
