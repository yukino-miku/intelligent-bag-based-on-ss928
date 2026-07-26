#!/usr/bin/env python3
"""Bring up MT5710 NCM networking and run all real SmartBag upload producers."""

from __future__ import annotations

import argparse
import os
import re
import select
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


CLOUDBASE_HOST = "cloud1-d7gdmg27139f4fbf2.service.tcloudbase.com"
TERMINAL_LINES = {"OK", "ERROR", "COMMAND NOT SUPPORT", "NO CARRIER"}
_SMS_MESSAGE_REFERENCE = int(time.time()) & 0xFF


def _next_sms_message_reference() -> int:
    global _SMS_MESSAGE_REFERENCE
    reference = _SMS_MESSAGE_REFERENCE
    _SMS_MESSAGE_REFERENCE = (reference + 1) & 0xFF
    return reference


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str], float], RunResult]


@dataclass(frozen=True)
class Ucs2Sms:
    setup_commands: tuple[str, ...]
    submit_command: str
    pdu_hex: str


def build_ucs2_sms(phone: str, message: str, message_reference: int = 0x66) -> Ucs2Sms:
    normalized_phone = phone.strip()
    if not re.fullmatch(r"\+?\d{5,20}", normalized_phone):
        raise ValueError("SMS phone must contain 5 to 20 digits with an optional leading plus")
    if not message:
        raise ValueError("SMS message must not be empty")
    if not 0 <= message_reference <= 0xFF:
        raise ValueError("SMS message reference must be between 0 and 255")
    encoded_message = message.encode("utf-16-be")
    if len(encoded_message) // 2 > 70:
        raise ValueError("UCS2 SMS message exceeds one 70-character message")
    international = normalized_phone.startswith("+")
    digits = normalized_phone[1:] if international else normalized_phone
    padded_digits = digits + ("F" if len(digits) % 2 else "")
    swapped_digits = "".join(
        padded_digits[index + 1] + padded_digits[index]
        for index in range(0, len(padded_digits), 2)
    )
    address_type = "91" if international else "81"
    user_data = encoded_message.hex().upper()
    # Keep the SMSC-length octet below at zero so the modem uses AT+CSCA.
    # MT5710's documented PDU-mode CMGS example uses SMS-SUBMIT FO=0x15
    # and a relative validity period of 0xFF. FO=0x15 asks the network to
    # reject duplicates, so TP-MR must change for every alarm. The prior fixed
    # TP-MR=0x66 made every message after the first look like a duplicate.
    # The prior generic
    # 0x11/0x00/0xA7 header was accepted at the prompt but this firmware did
    # not return +CMGS for it on the live 5G SMS path.
    tpdu = (
        "15"
        f"{message_reference:02X}"
        f"{len(digits):02X}"
        f"{address_type}"
        f"{swapped_digits}"
        "00"
        "08"
        "FF"
        f"{len(encoded_message):02X}"
        f"{user_data}"
    )
    return Ucs2Sms(
        # Prefer packet-switched SMS on the 5G registration used by this board.
        # The setting is persistent on the modem, but asserting it per send keeps
        # a reboot or a previous manual test from changing the alarm path.
        # A fall is one independent alarm: explicitly end any prior
        # multi-message session before opening PDU mode for this one.
        setup_commands=("AT+CMMS=0", "AT+CGSMS=2", "AT+CMGF=0"),
        submit_command=f"AT+CMGS={len(tpdu) // 2}",
        pdu_hex="00" + tpdu,
    )


def choose_apn(operator: str, imsi: str, override: str) -> str:
    explicit = override.strip()
    if explicit:
        return explicit
    normalized = operator.upper().replace("_", " ").replace("-", " ")
    if "TELECOM" in normalized:
        return "ctnet"
    if "MOBILE" in normalized or "CMCC" in normalized:
        return "cmnet"
    if "UNICOM" in normalized:
        return "3gnet"
    prefix = re.sub(r"\D", "", imsi)[:5]
    if prefix in {"46003", "46005", "46011"}:
        return "ctnet"
    if prefix in {"46000", "46002", "46004", "46007", "46008"}:
        return "cmnet"
    if prefix in {"46001", "46006", "46009"}:
        return "3gnet"
    raise RuntimeError("cannot determine APN; pass --apn")


def parse_registration(lines: Sequence[str]) -> tuple[bool, bool]:
    registered = False
    attached = False
    for line in lines:
        match = re.search(r"\+(?:CEREG|C5GREG):\s*\d+\s*,\s*(\d+)", line)
        if match and match.group(1) in {"1", "5"}:
            registered = True
        match = re.search(r"\+CGATT:\s*(\d+)", line)
        if match:
            attached = match.group(1) == "1"
    return registered, attached


def _driver_name(interface_dir: Path) -> str:
    driver_link = interface_dir / "device" / "driver"
    try:
        return driver_link.resolve(strict=True).name
    except OSError:
        pass
    try:
        for line in (interface_dir / "device" / "uevent").read_text(encoding="utf-8").splitlines():
            if line.startswith("DRIVER="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def _usb_identity(device_path: Path) -> tuple[str, str] | None:
    try:
        resolved = device_path.resolve(strict=True)
    except OSError:
        resolved = device_path
    for candidate in (resolved, *resolved.parents):
        try:
            vendor = (candidate / "idVendor").read_text(encoding="ascii").strip().lower()
            product = (candidate / "idProduct").read_text(encoding="ascii").strip().lower()
            if vendor and product:
                return vendor, product
        except OSError:
            continue
    return None


def discover_ncm_interface(
    sys_class_net: Path = Path("/sys/class/net"),
    expected_usb_identity: tuple[str, str] | None = None,
) -> str:
    candidates = []
    for entry in sys_class_net.iterdir():
        if not entry.is_dir() or _driver_name(entry) != "cdc_ncm":
            continue
        identity = _usb_identity(entry / "device")
        if expected_usb_identity is None or identity == expected_usb_identity:
            candidates.append(entry.name)
    candidates.sort()
    if not candidates:
        raise RuntimeError("MT5710 cdc_ncm interface not found")
    if len(candidates) > 1:
        raise RuntimeError("multiple cdc_ncm interfaces found; cannot identify MT5710")
    return candidates[0]


def route_uses_interface(route_text: str, interface: str) -> bool:
    return re.search(rf"(?:^|\s)dev\s+{re.escape(interface)}(?:\s|$)", route_text) is not None


def _add_ncm_host_route(interface: str, cloud_ip: str, command_runner: CommandRunner) -> None:
    default_result = command_runner(["ip", "route", "show", "default", "dev", interface], 10.0)
    _require_success(default_result, "NCM default route lookup")
    match = re.search(
        rf"^default(?:\s+via\s+(\S+))?\s+dev\s+{re.escape(interface)}(?:\s|$)",
        default_result.stdout.strip(),
    )
    if not match:
        raise RuntimeError(f"DHCP did not install a default route for {interface}")
    argv = ["ip", "route", "replace", f"{cloud_ip}/32"]
    if match.group(1):
        argv.extend(["via", match.group(1)])
    argv.extend(["dev", interface])
    _require_success(command_runner(argv, 10.0), "CloudBase NCM host route")


def build_sensor_commands(work_root: Path, include_gnss: bool = True) -> list[list[str]]:
    dx_dir = work_root / "gnss"
    bmi_dir = work_root / "imu"
    dx_command = [
        "python3",
        str(dx_dir / "dx_gp21_tracker.py"),
        "--config",
        str(dx_dir / "config.ss928_uart4.json"),
        "--serial-device",
        "/dev/ttyAMA4",
        "--baud",
        "115200",
        "--no-ble",
    ]
    bmi_command = [
        "python3",
        str(bmi_dir / "bmi270_backpack.py"),
        "--config",
        "/etc/smartbag/bmi270.json",
        "--no-ble",
    ]
    return [dx_command, bmi_command] if include_gnss else [bmi_command]


def run_command(argv: list[str], timeout_s: float = 30.0) -> RunResult:
    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    return RunResult(completed.returncode, completed.stdout, completed.stderr)


def _require_success(result: RunResult, label: str) -> None:
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else f"rc={result.returncode}"
        raise RuntimeError(f"{label} failed: {detail}")


def _extract_operator(lines: Iterable[str]) -> str:
    for line in lines:
        match = re.search(r'\+COPS:\s*\d+\s*,\s*\d+\s*,\s*"([^"]+)"', line)
        if match:
            return match.group(1)
    return ""


def _extract_imsi(lines: Iterable[str]) -> str:
    for line in lines:
        if re.fullmatch(r"\d{10,20}", line.strip()):
            return line.strip()
    return ""


class AtSession:
    def __init__(self, port: str, baud: int = 115200) -> None:
        self.port = port
        self.baud = baud
        self.fd: int | None = None

    def __enter__(self) -> "AtSession":
        import termios

        self.fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(self.fd)
        attrs[0] = 0
        attrs[1] = 0
        attrs[2] |= termios.CLOCAL | termios.CREAD | termios.CS8
        attrs[2] &= ~(termios.PARENB | termios.CSTOPB | termios.CRTSCTS)
        attrs[3] = 0
        speed = getattr(termios, f"B{self.baud}", termios.B115200)
        attrs[4] = speed
        attrs[5] = speed
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        termios.tcflush(self.fd, termios.TCIOFLUSH)
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def command(self, command: str, timeout_s: float = 4.0) -> list[str]:
        if self.fd is None:
            raise RuntimeError("AT session is not open")
        os.write(self.fd, (command + "\r\n").encode("ascii"))
        deadline = time.monotonic() + timeout_s
        raw = bytearray()
        lines: list[str] = []
        while time.monotonic() < deadline:
            readable, _, _ = select.select([self.fd], [], [], min(0.2, deadline - time.monotonic()))
            if not readable:
                continue
            try:
                raw.extend(os.read(self.fd, 4096))
            except BlockingIOError:
                continue
            decoded = raw.decode("utf-8", errors="replace")
            lines = [item.strip() for item in re.split(r"[\r\n]+", decoded) if item.strip()]
            filtered = [line for line in lines if line != command]
            if any(
                line in TERMINAL_LINES
                or line.startswith("+CME ERROR")
                or line.startswith("+CMS ERROR")
                or line.startswith("ERROR:")
                for line in filtered
            ):
                return filtered
        return [line for line in lines if line != command]

    def _read_until(self, predicate: Callable[[bytes], bool], timeout_s: float) -> bytes:
        if self.fd is None:
            raise RuntimeError("AT session is not open")
        deadline = time.monotonic() + timeout_s
        raw = bytearray()
        while time.monotonic() < deadline:
            readable, _, _ = select.select([self.fd], [], [], min(0.2, deadline - time.monotonic()))
            if not readable:
                continue
            try:
                raw.extend(os.read(self.fd, 4096))
            except BlockingIOError:
                continue
            if predicate(bytes(raw)):
                return bytes(raw)
        return bytes(raw)

    def _cancel_pending_sms_input(self) -> None:
        """Leave an unfinished AT+CMGS editor before issuing another AT command.

        A timeout after Ctrl-Z can leave the PCUI accepting the next bytes as
        PDU data.  ESC is the modem-defined cancellation for that editor.  This
        is intentionally a recovery action only; it never retransmits an SMS.
        """
        if self.fd is None:
            raise RuntimeError("AT session is not open")
        try:
            os.write(self.fd, b"\x1b")
            self._read_until(
                lambda raw: b"\r\nOK\r\n" in raw or b"ERROR" in raw,
                1.0,
            )
        except OSError:
            # The following AT health check reports a real serial-port failure.
            pass

    def send_ucs2_sms(self, phone: str, message: str, timeout_s: float = 30.0) -> list[str]:
        if self.fd is None:
            raise RuntimeError("AT session is not open")
        sms = build_ucs2_sms(phone, message, _next_sms_message_reference())
        self._cancel_pending_sms_input()
        if "OK" not in self.command("AT"):
            raise RuntimeError("MT5710 SMS PCUI health check failed")
        for command in sms.setup_commands:
            lines = self.command(command)
            if "OK" not in lines:
                raise RuntimeError("MT5710 SMS setup failed")

        os.write(self.fd, (sms.submit_command + "\r").encode("ascii"))
        prompt = self._read_until(
            lambda raw: b">" in raw or b"ERROR" in raw,
            min(timeout_s, 10.0),
        )
        if b">" not in prompt:
            self._cancel_pending_sms_input()
            raise RuntimeError("MT5710 SMS prompt was not received")

        os.write(self.fd, sms.pdu_hex.encode("ascii") + b"\x1a")
        response = self._read_until(
            lambda raw: b"\r\nOK\r\n" in raw or b"ERROR" in raw,
            timeout_s,
        )
        text = response.decode("utf-8", errors="replace")
        lines = [item.strip() for item in re.split(r"[\r\n]+", text) if item.strip()]
        if not any(line.startswith("+CMGS:") for line in lines) or "OK" not in lines:
            modem_errors = [
                line for line in lines
                if line.startswith("+CMS ERROR") or line.startswith("+CME ERROR") or line == "ERROR"
            ]
            detail = ", ".join(modem_errors) if modem_errors else "missing +CMGS/OK"
            self._cancel_pending_sms_input()
            raise RuntimeError(f"MT5710 SMS send failed: {detail}")
        return lines

    def send_ucs2_sms_via_storage(
        self,
        phone: str,
        message: str,
        timeout_s: float = 30.0,
    ) -> list[str]:
        """Store one PDU with CMGW, submit it once with CMSS, then delete it."""
        if self.fd is None:
            raise RuntimeError("AT session is not open")
        sms = build_ucs2_sms(phone, message, _next_sms_message_reference())
        self._cancel_pending_sms_input()
        if "OK" not in self.command("AT"):
            raise RuntimeError("MT5710 SMS PCUI health check failed")
        for command in sms.setup_commands:
            if "OK" not in self.command(command):
                raise RuntimeError("MT5710 SMS setup failed")

        os.write(self.fd, (f"AT+CMGW={len(sms.pdu_hex) // 2 - 1}\r").encode("ascii"))
        prompt = self._read_until(
            lambda raw: b">" in raw or b"ERROR" in raw,
            min(timeout_s, 10.0),
        )
        if b">" not in prompt:
            self._cancel_pending_sms_input()
            raise RuntimeError("MT5710 SMS storage prompt was not received")

        os.write(self.fd, sms.pdu_hex.encode("ascii") + b"\x1a")
        stored_response = self._read_until(
            lambda raw: b"\r\nOK\r\n" in raw or b"ERROR" in raw,
            timeout_s,
        ).decode("utf-8", errors="replace")
        stored_lines = [
            item.strip() for item in re.split(r"[\r\n]+", stored_response) if item.strip()
        ]
        index_match = next(
            (re.match(r"\+CMGW:\s*(\d+)", line) for line in stored_lines if line.startswith("+CMGW:")),
            None,
        )
        if index_match is None or "OK" not in stored_lines:
            self._cancel_pending_sms_input()
            raise RuntimeError("MT5710 SMS storage failed")

        index = index_match.group(1)
        try:
            sent_lines = self.command(f"AT+CMSS={index}", timeout_s=timeout_s)
            if not any(line.startswith("+CMSS:") for line in sent_lines) or "OK" not in sent_lines:
                modem_errors = [
                    line for line in sent_lines
                    if line.startswith("+CMS ERROR") or line.startswith("+CME ERROR") or line == "ERROR"
                ]
                detail = ", ".join(modem_errors) if modem_errors else "missing +CMSS/OK"
                raise RuntimeError(f"MT5710 stored SMS send failed: {detail}")
            return sent_lines
        finally:
            self.command(f"AT+CMGD={index}", timeout_s=5.0)


class Mt5710SmsNotifier:
    def __init__(
        self,
        phone: str,
        message: str,
        port: str = "/dev/ttyUSB1",
        baud: int = 115200,
        timeout_s: float = 30.0,
        at_factory: Callable[[str, int], Any] = AtSession,
    ) -> None:
        build_ucs2_sms(phone, message)
        self.phone = phone
        self.message = message
        self.port = port
        self.baud = baud
        self.timeout_s = timeout_s
        self.at_factory = at_factory

    def __call__(self, alarm: Mapping[str, Any]) -> bool:
        if alarm.get("signal") != "FALL_ALARM" or alarm.get("alarmType") != "fall_detected":
            return False
        with self.at_factory(self.port, self.baud) as session:
            session.send_ucs2_sms(self.phone, self.message, timeout_s=self.timeout_s)
        print("MT5710 fall alarm SMS sent", flush=True)
        return True


class Mt5710CallNotifier:
    """Place one non-blocking ring-only call for a final fall alarm."""

    def __init__(
        self,
        phone: str,
        *,
        port: str = "/dev/ttyUSB1",
        baud: int = 115200,
        ring_seconds: float = 12.0,
        poll_interval_s: float = 1.0,
        at_factory: Callable[[str, int], Any] = AtSession,
        thread_factory: Callable[..., Any] = threading.Thread,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        normalized_phone = phone.strip()
        if not re.fullmatch(r"\+?\d{5,20}", normalized_phone):
            raise ValueError("call phone must contain 5 to 20 digits with an optional leading plus")
        if not 10.0 <= ring_seconds <= 15.0:
            raise ValueError("call ring duration must be between 10 and 15 seconds")
        self.phone = normalized_phone
        self.port = port
        self.baud = baud
        self.ring_seconds = float(ring_seconds)
        self.poll_interval_s = max(float(poll_interval_s), 0.0)
        self.at_factory = at_factory
        self.thread_factory = thread_factory
        self.sleep_fn = sleep_fn
        self.monotonic = monotonic
        self._state_lock = threading.Lock()
        self._active = False

    def __call__(self, alarm: Mapping[str, Any]) -> bool:
        if alarm.get("signal") != "FALL_ALARM" or alarm.get("alarmType") != "fall_detected":
            return False
        with self._state_lock:
            if self._active:
                print("MT5710 fall alarm call already active", flush=True)
                return False
            self._active = True
        worker = self.thread_factory(
            target=self._run_call,
            name="mt5710-fall-call",
            daemon=True,
        )
        try:
            worker.start()
        except Exception:
            with self._state_lock:
                self._active = False
            raise
        print("MT5710 fall alarm call scheduled", flush=True)
        return True

    def _run_call(self) -> None:
        call_started = False
        try:
            with self.at_factory(self.port, self.baud) as session:
                if "OK" not in session.command("AT"):
                    raise RuntimeError("MT5710 call PCUI health check failed")
                dial_lines = session.command(f"ATD{self.phone};", timeout_s=10.0)
                if "OK" not in dial_lines:
                    raise RuntimeError("MT5710 call dial failed")
                call_started = True
                print("MT5710 fall alarm call ringing", flush=True)
                deadline = self.monotonic() + self.ring_seconds
                while self.monotonic() < deadline:
                    remaining = max(0.0, deadline - self.monotonic())
                    self.sleep_fn(min(self.poll_interval_s, remaining))
                    call_lines = session.command("AT+CLCC", timeout_s=4.0)
                    statuses = []
                    for line in call_lines:
                        match = re.match(r"\+CLCC:\s*\d+\s*,\s*\d+\s*,\s*(\d+)", line)
                        if match:
                            statuses.append(int(match.group(1)))
                    if not statuses:
                        call_started = False
                        print("MT5710 fall alarm call ended by remote/network", flush=True)
                        return
                    if 0 in statuses:
                        print("MT5710 fall alarm call answered; hanging up", flush=True)
                        break
                if call_started:
                    session.command("ATH", timeout_s=5.0)
                    call_started = False
                    print("MT5710 fall alarm call hung up", flush=True)
        except Exception as exc:
            print(f"WARN MT5710 fall alarm call failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        finally:
            if call_started:
                try:
                    with self.at_factory(self.port, self.baud) as session:
                        session.command("ATH", timeout_s=5.0)
                except Exception:
                    pass
            with self._state_lock:
                self._active = False


def prepare_network(
    at_session: object,
    command_runner: CommandRunner = run_command,
    sys_class_net: Path = Path("/sys/class/net"),
    resolver: Callable[[str], str] = socket.gethostbyname,
    apn_override: str = "",
    expected_usb_identity: tuple[str, str] | None = None,
) -> dict[str, str]:
    at_lines: list[str] = []
    health = at_session.command("AT")
    if "OK" not in health:
        raise RuntimeError("MT5710 PCUI did not answer AT")
    sim_lines = at_session.command("AT+CPIN?")
    if not any("+CPIN: READY" in line for line in sim_lines):
        raise RuntimeError("MT5710 SIM is not ready")
    operator_lines = at_session.command("AT+COPS?")
    imsi_lines = at_session.command("AT+CIMI")
    at_lines.extend(at_session.command("AT+CEREG?"))
    at_lines.extend(at_session.command("AT+C5GREG?"))
    at_lines.extend(at_session.command("AT+CGATT?"))
    registered, attached = parse_registration(at_lines)
    if not registered or not attached:
        raise RuntimeError("MT5710 is not registered/attached")
    apn = choose_apn(_extract_operator(operator_lines), _extract_imsi(imsi_lines), apn_override)
    dial_command = f'AT^NDISDUP=1,1,"{apn}"'
    dial_lines = at_session.command(dial_command, timeout_s=12.0)
    already_active = any(line == "ERROR: DUPLICATED" for line in dial_lines)
    if not already_active and any("ERROR" in line or "NO NETWORK SERVICE" in line for line in dial_lines):
        raise RuntimeError("MT5710 NCM dial failed")
    if (
        not already_active
        and "OK" not in dial_lines
        and not any("^NDISSTAT: 1,1" in line for line in dial_lines)
    ):
        raise RuntimeError("MT5710 NCM dial gave no success response")

    interface = discover_ncm_interface(sys_class_net, expected_usb_identity)
    _require_success(command_runner(["ip", "link", "set", interface, "up"], 10.0), "NCM link up")
    _require_success(
        command_runner(["udhcpc", "-i", interface, "-q", "-n", "-t", "8", "-T", "5"], 50.0),
        "NCM DHCP",
    )
    cloud_ip = resolver(CLOUDBASE_HOST)
    route_result = command_runner(["ip", "route", "get", cloud_ip], 10.0)
    _require_success(route_result, "CloudBase route lookup")
    added_route = ""
    if not route_uses_interface(route_result.stdout, interface):
        _add_ncm_host_route(interface, cloud_ip, command_runner)
        added_route = cloud_ip
        route_result = command_runner(["ip", "route", "get", cloud_ip], 10.0)
        _require_success(route_result, "CloudBase route recheck")
        if not route_uses_interface(route_result.stdout, interface):
            raise RuntimeError(f"CloudBase route is not using {interface}")
    return {"interface": interface, "apn": apn, "cloud_ip": cloud_ip, "added_route": added_route}


def _cleanup_network_route(network: dict[str, str] | None, command_runner: CommandRunner) -> None:
    if not network or not network.get("added_route"):
        return
    command_runner(
        ["ip", "route", "del", f"{network['added_route']}/32", "dev", network["interface"]],
        10.0,
    )


def _require_runtime_files(work_root: Path, include_gnss: bool = True) -> None:
    required = [
        work_root / "cloud_uploader" / "telemetry_client.py",
        work_root / "imu" / "bmi270_backpack.py",
        work_root / "imu" / "posture_cloud.py",
        Path("/etc/smartbag/bmi270.json"),
    ]
    if include_gnss:
        required.extend(
            [
                work_root / "gnss" / "dx_gp21_tracker.py",
                work_root / "gnss" / "config.ss928_uart4.json",
            ]
        )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("missing runtime file: " + missing[0])
    devices = [Path("/dev/i2c-0")]
    if include_gnss:
        devices.append(Path("/dev/ttyAMA4"))
    for device in devices:
        if not device.exists():
            raise RuntimeError(f"missing device: {device}")
    for executable in ("python3", "bspmm", "ip", "udhcpc"):
        if shutil.which(executable) is None:
            raise RuntimeError(f"missing executable: {executable}")


def _configure_pinmux(command_runner: CommandRunner, include_gnss: bool = True) -> None:
    settings = [
        ["bspmm", "0x102F013c", "0x2031"],
        ["bspmm", "0x102F0140", "0x2031"],
    ]
    if include_gnss:
        settings[0:0] = [
            ["bspmm", "0x102F0134", "0x1201"],
            ["bspmm", "0x102F0138", "0x1201"],
        ]
    for argv in settings:
        _require_success(command_runner(argv, 10.0), "SS928 pinmux")


def _supervise(commands: Sequence[list[str]], work_root: Path) -> int:
    children: list[subprocess.Popen[bytes]] = []
    stopping = False

    def stop_handler(signum: int, frame: object) -> None:
        del signum, frame
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    try:
        for command in commands:
            child = subprocess.Popen(command, cwd=str(work_root))
            children.append(child)
            print(f"Started pid={child.pid}: {Path(command[1]).name}", flush=True)
        while not stopping:
            for child in children:
                code = child.poll()
                if code is not None:
                    print(f"Producer pid={child.pid} exited rc={code}", file=sys.stderr, flush=True)
                    return code if code != 0 else 1
            time.sleep(0.5)
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        deadline = time.monotonic() + 5.0
        for child in children:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                child.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                child.kill()


def _wait_for_shutdown(poll_interval_s: float = 1.0) -> int:
    stopping = False

    def stop_handler(signum: int, frame: object) -> None:
        del signum, frame
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    while not stopping:
        time.sleep(max(0.05, poll_interval_s))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/ttyUSB1", help="MT5710 PCUI serial port")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--apn", default="", help="APN override; normally auto-detected")
    parser.add_argument(
        "--work-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Board work directory containing the existing producers",
    )
    parser.add_argument("--skip-network", action="store_true", help="Skip MT5710 dialing for local diagnosis")
    parser.add_argument(
        "--skip-gnss",
        action="store_true",
        help="Do not require or start the unplugged DX-GP21-A GNSS module",
    )
    parser.add_argument("--check-only", action="store_true", help="Bring up and verify 5G, then exit")
    parser.add_argument(
        "--supervise-sensors",
        action="store_true",
        help="Legacy diagnostic mode only. Formal deployment keeps BMI270/GNSS in their own services.",
    )
    return parser


def run_application(
    args: argparse.Namespace,
    *,
    environ: dict[str, str] | os._Environ[str] = os.environ,
    prerequisite_checker: Callable[[Path, bool], None] = _require_runtime_files,
    network_preparer: Callable[..., dict[str, str]] = prepare_network,
    at_factory: Callable[[str, int], object] = AtSession,
    command_runner: CommandRunner = run_command,
    pinmux_configurer: Callable[[CommandRunner, bool], None] = _configure_pinmux,
    supervisor: Callable[[Sequence[list[str]], Path], int] = _supervise,
    service_waiter: Callable[[], int] = _wait_for_shutdown,
) -> int:
    work_root = args.work_root.resolve()
    include_gnss = not args.skip_gnss
    supervise_sensors = bool(getattr(args, "supervise_sensors", False))
    if not args.check_only and supervise_sensors:
        if not environ.get("SMARTBAG_UPLOAD_TOKEN", ""):
            raise RuntimeError("SMARTBAG_UPLOAD_TOKEN is not set")
        prerequisite_checker(work_root, include_gnss)

    network: dict[str, str] | None = None
    try:
        if not args.skip_network:
            if not Path(args.port).exists():
                raise RuntimeError(f"missing MT5710 PCUI port: {args.port}")
            tty_device = Path("/sys/class/tty") / Path(args.port).name / "device"
            expected_identity = _usb_identity(tty_device)
            with at_factory(args.port, args.baud) as at_session:
                network = network_preparer(
                    at_session,
                    command_runner=command_runner,
                    apn_override=args.apn,
                    expected_usb_identity=expected_identity,
                )
            print(
                f"5G ready: interface={network['interface']} apn_configured=yes "
                f"cloud_ip={network['cloud_ip']}",
                flush=True,
            )
        if args.check_only:
            return 0
        if supervise_sensors:
            pinmux_configurer(command_runner, include_gnss)
            commands = build_sensor_commands(work_root, include_gnss)
            producer_names = "DX-GP21-A and BMI270" if include_gnss else "BMI270 (DX-GP21-A skipped)"
            print(f"Starting legacy {producer_names} supervision", flush=True)
            return supervisor(commands, work_root)
        print("MT5710 owns connectivity only; BMI270 and GNSS remain separate services", flush=True)
        return service_waiter()
    finally:
        _cleanup_network_route(network, command_runner)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        print("ERROR: run as root on BOARD-LINUX", file=sys.stderr)
        return 2
    try:
        return run_application(args)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
