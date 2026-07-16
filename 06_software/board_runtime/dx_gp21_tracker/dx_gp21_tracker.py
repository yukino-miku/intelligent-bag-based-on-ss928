#!/usr/bin/env python3
"""
DX-GP21 GNSS tracker for SS928/HiEuler Pi.

Reads NMEA from a UART, stores valid WGS84 track points as JSONL, and exposes
the existing mini-program BLE Nordic UART Service command protocol.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple


KNOT_TO_MPS = 0.514444
DEFAULT_CONFIG: Dict[str, Any] = {
    "serial": {
        "device": "/dev/ttyAMA4",
        "baud": 115200,
        "dump_nmea": False,
    },
    "track": {
        "data_dir": "/var/lib/smartbag/tracks",
        "chunk_size": 25,
    },
    "output": {
        "console": True,
        "ble_enabled": False,
        "ble_name": "SS928-SmartBag",
        "live_hz": 1.0,
    },
}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Optional[str]) -> Dict[str, Any]:
    cfg = DEFAULT_CONFIG
    if path:
        with open(path, "r", encoding="utf-8") as f:
            cfg = deep_merge(DEFAULT_CONFIG, json.load(f))
    return cfg


def nmea_checksum(body: str) -> int:
    value = 0
    for ch in body:
        value ^= ord(ch)
    return value


def split_nmea(line: str) -> Optional[Tuple[str, str]]:
    text = line.strip()
    if not text.startswith("$") or "*" not in text:
        return None
    body, checksum = text[1:].split("*", 1)
    checksum = checksum[:2]
    if len(checksum) != 2:
        return None
    try:
        int(checksum, 16)
    except ValueError:
        return None
    return body, checksum.upper()


def is_valid_nmea(line: str) -> bool:
    parts = split_nmea(line)
    if parts is None:
        return False
    body, expected = parts
    return f"{nmea_checksum(body):02X}" == expected


def dm_to_decimal(value: str, hemisphere: str) -> float:
    hemi = hemisphere.upper()
    if hemi in ("N", "S"):
        deg_len = 2
    elif hemi in ("E", "W"):
        deg_len = 3
    else:
        raise ValueError("invalid hemisphere")
    if len(value) <= deg_len:
        raise ValueError("invalid coordinate")
    degrees = float(value[:deg_len])
    minutes = float(value[deg_len:])
    decimal = degrees + minutes / 60.0
    if hemi in ("S", "W"):
        decimal = -decimal
    return decimal


def _to_float(value: str) -> Optional[float]:
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value: str) -> int:
    if value == "":
        return 0
    try:
        return int(float(value))
    except ValueError:
        return 0


def _parse_utc_time(utc_time: str, utc_date: Optional[str]) -> Optional[float]:
    if not utc_time:
        return None
    try:
        hour = int(utc_time[0:2])
        minute = int(utc_time[2:4])
        seconds_value = float(utc_time[4:])
    except (ValueError, IndexError):
        return None
    second = int(seconds_value)
    microsecond = int(round((seconds_value - second) * 1_000_000))

    now = _dt.datetime.now(_dt.timezone.utc)
    year = now.year
    month = now.month
    day = now.day
    if utc_date:
        try:
            day = int(utc_date[0:2])
            month = int(utc_date[2:4])
            year_short = int(utc_date[4:6])
            year = 1900 + year_short if year_short >= 80 else 2000 + year_short
        except (ValueError, IndexError):
            return None
    try:
        dt = _dt.datetime(year, month, day, hour, minute, second, microsecond, tzinfo=_dt.timezone.utc)
    except ValueError:
        return None
    return dt.timestamp()


def parse_nmea(line: str) -> Optional[Tuple[str, List[str]]]:
    if not is_valid_nmea(line):
        return None
    parts = split_nmea(line)
    if parts is None:
        return None
    body, _checksum = parts
    fields = body.split(",")
    if not fields:
        return None
    sentence = fields[0]
    if len(sentence) < 5:
        return None
    return sentence[-3:], fields[1:]


class NmeaLocationTracker:
    def __init__(self) -> None:
        self.fix = 0
        self.satellites = 0
        self.hdop: Optional[float] = None
        self.altitude: Optional[float] = None
        self.speed_mps: Optional[float] = None
        self.course: Optional[float] = None
        self.last_point: Optional[Dict[str, Any]] = None
        self.last_sentence = ""
        self.bad_checksum = 0

    def update(self, line: str) -> Optional[Dict[str, Any]]:
        parsed = parse_nmea(line)
        if parsed is None:
            if line.strip().startswith("$"):
                self.bad_checksum += 1
            return None

        kind, fields = parsed
        self.last_sentence = kind
        if kind == "GGA":
            self._update_gga(fields)
            return None
        if kind == "RMC":
            return self._update_rmc(fields)
        if kind == "VTG":
            self._update_vtg(fields)
            return None
        return None

    def _update_gga(self, fields: List[str]) -> None:
        if len(fields) < 9:
            return
        self.fix = _to_int(fields[5])
        self.satellites = _to_int(fields[6])
        self.hdop = _to_float(fields[7])
        self.altitude = _to_float(fields[8])

    def _update_rmc(self, fields: List[str]) -> Optional[Dict[str, Any]]:
        if len(fields) < 9:
            return None
        status = fields[1].upper()
        self.fix = 1 if status == "A" else 0
        if self.fix <= 0:
            return None
        try:
            latitude = dm_to_decimal(fields[2], fields[3])
            longitude = dm_to_decimal(fields[4], fields[5])
        except (ValueError, IndexError):
            return None
        t = _parse_utc_time(fields[0], fields[8])
        speed_knots = _to_float(fields[6])
        course = _to_float(fields[7])
        if speed_knots is not None:
            self.speed_mps = speed_knots * KNOT_TO_MPS
        if course is not None:
            self.course = course

        point = {
            "typ": "loc",
            "t": t if t is not None else time.time(),
            "lat": latitude,
            "lon": longitude,
            "acc": self.hdop,
            "alt": self.altitude,
            "spd": self.speed_mps,
            "course": self.course,
            "fix": self.fix,
            "sat": self.satellites,
            "src": "dx_gp21",
            "cs": "wgs84",
        }
        self.last_point = point
        return point

    def _update_vtg(self, fields: List[str]) -> None:
        if len(fields) < 7:
            return
        course = _to_float(fields[0])
        speed_kph = _to_float(fields[6])
        if course is not None:
            self.course = course
        if speed_kph is not None:
            self.speed_mps = speed_kph / 3.6

    def status(self, serial_device: str, baud: int, track_count: int) -> Dict[str, Any]:
        frame = {
            "typ": "ts",
            "fix": self.fix,
            "sat": self.satellites,
            "hdop": self.hdop,
            "alt": self.altitude,
            "uart": serial_device,
            "baud": baud,
            "tracks": track_count,
            "bad": self.bad_checksum,
            "src": "dx_gp21",
        }
        if self.last_point is not None:
            frame.update(
                {
                    "t": self.last_point.get("t"),
                    "lat": self.last_point.get("lat"),
                    "lon": self.last_point.get("lon"),
                }
            )
        return frame


def is_valid_coordinate(latitude: Any, longitude: Any) -> bool:
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return False
    return math.isfinite(lat) and math.isfinite(lon) and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


class TrackStore:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def append(self, point: Dict[str, Any]) -> bool:
        if int(point.get("fix") or 0) <= 0:
            return False
        if not is_valid_coordinate(point.get("lat"), point.get("lon")):
            return False
        record = self._clean_point(point)
        path = self.data_dir / f"{self._track_id(record['t'])}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return True

    def list_tracks(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for index, path in enumerate(self._files()):
            count = 0
            first: Optional[Dict[str, Any]] = None
            last: Optional[Dict[str, Any]] = None
            for point in self._read_points(path):
                count += 1
                if first is None:
                    first = point
                last = point
            if count == 0 or first is None or last is None:
                continue
            items.append(
                {
                    "i": index,
                    "id": path.stem,
                    "n": count,
                    "start": first.get("t", 0),
                    "end": last.get("t", 0),
                }
            )
        return items

    def chunk(self, track_index: int, offset: int, limit: int = 25) -> Dict[str, Any]:
        files = self._files()
        index = max(0, int(track_index))
        start = max(0, int(offset))
        size = max(1, int(limit))
        if index >= len(files):
            return {"typ": "trk", "i": index, "o": start, "next": None, "done": 1, "pts": []}

        points: List[List[Any]] = []
        total_seen = 0
        for point in self._read_points(files[index]):
            if total_seen >= start and len(points) < size:
                points.append(self._compact_point(point))
            total_seen += 1

        next_offset = start + len(points)
        done = 1 if next_offset >= total_seen else 0
        return {
            "typ": "trk",
            "i": index,
            "o": start,
            "next": None if done else next_offset,
            "done": done,
            "pts": points,
        }

    def count(self) -> int:
        return len(self.list_tracks())

    def _files(self) -> List[Path]:
        return sorted(self.data_dir.glob("*.jsonl"), reverse=True)

    def _read_points(self, path: Path) -> Iterator[Dict[str, Any]]:
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        point = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if is_valid_coordinate(point.get("lat"), point.get("lon")):
                        yield point
        except OSError:
            return

    @staticmethod
    def _track_id(timestamp: Any) -> str:
        try:
            seconds = float(timestamp)
        except (TypeError, ValueError):
            seconds = time.time()
        return _dt.datetime.fromtimestamp(seconds, _dt.timezone.utc).strftime("%Y-%m-%d")

    @staticmethod
    def _clean_point(point: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "t": float(point.get("t") or time.time()),
            "lat": float(point["lat"]),
            "lon": float(point["lon"]),
            "acc": point.get("acc"),
            "alt": point.get("alt"),
            "spd": point.get("spd"),
            "course": point.get("course"),
            "fix": int(point.get("fix") or 0),
            "sat": int(point.get("sat") or 0),
            "src": point.get("src") or "dx_gp21",
            "cs": point.get("cs") or "wgs84",
        }

    @staticmethod
    def _compact_point(point: Dict[str, Any]) -> List[Any]:
        return [
            point.get("t"),
            point.get("lat"),
            point.get("lon"),
            point.get("acc"),
            point.get("spd"),
            point.get("course"),
        ]


class BleNusServer:
    """Minimal BlueZ GATT server exposing Nordic UART Service."""

    NUS_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
    NUS_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
    NUS_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

    def __init__(self, name: str, on_rx: Callable[[str], None]):
        self.name = name
        self.on_rx = on_rx
        self.ready = False
        self.tx = None
        self.mainloop = None
        self.GLib = None
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        try:
            import dbus
            import dbus.exceptions
            import dbus.mainloop.glib
            import dbus.service
            from gi.repository import GLib
        except Exception as exc:  # pragma: no cover - target Linux only.
            raise RuntimeError("BLE needs BlueZ Python packages: python3-dbus and python3-gi") from exc

        self.GLib = GLib
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SystemBus()

        BLUEZ = "org.bluez"
        DBUS_OM = "org.freedesktop.DBus.ObjectManager"
        DBUS_PROP = "org.freedesktop.DBus.Properties"
        GATT_MANAGER = "org.bluez.GattManager1"
        GATT_SERVICE = "org.bluez.GattService1"
        GATT_CHRC = "org.bluez.GattCharacteristic1"
        LE_ADV_MANAGER = "org.bluez.LEAdvertisingManager1"
        LE_ADV = "org.bluez.LEAdvertisement1"

        class InvalidArgsException(dbus.exceptions.DBusException):
            _dbus_error_name = "org.freedesktop.DBus.Error.InvalidArgs"

        class Application(dbus.service.Object):
            PATH = "/"

            def __init__(self, system_bus: Any):
                self.services: List[Any] = []
                dbus.service.Object.__init__(self, system_bus, self.PATH)

            def get_path(self) -> Any:
                return dbus.ObjectPath(self.PATH)

            def add_service(self, service: Any) -> None:
                self.services.append(service)

            @dbus.service.method(DBUS_OM, out_signature="a{oa{sa{sv}}}")
            def GetManagedObjects(self) -> Dict[Any, Any]:
                response: Dict[Any, Any] = {}
                for service in self.services:
                    response[service.get_path()] = service.get_properties()
                    for chrc in service.characteristics:
                        response[chrc.get_path()] = chrc.get_properties()
                return response

        class Service(dbus.service.Object):
            PATH_BASE = "/org/bluez/example/service"

            def __init__(self, system_bus: Any, index: int, uuid: str, primary: bool):
                self.path = self.PATH_BASE + str(index)
                self.uuid = uuid
                self.primary = primary
                self.characteristics: List[Any] = []
                dbus.service.Object.__init__(self, system_bus, self.path)

            def get_properties(self) -> Dict[str, Dict[str, Any]]:
                return {
                    GATT_SERVICE: {
                        "UUID": self.uuid,
                        "Primary": self.primary,
                        "Characteristics": dbus.Array([chrc.get_path() for chrc in self.characteristics], signature="o"),
                    }
                }

            def get_path(self) -> Any:
                return dbus.ObjectPath(self.path)

            def add_characteristic(self, characteristic: Any) -> None:
                self.characteristics.append(characteristic)

            @dbus.service.method(DBUS_PROP, in_signature="s", out_signature="a{sv}")
            def GetAll(self, interface: str) -> Dict[str, Any]:
                if interface != GATT_SERVICE:
                    raise InvalidArgsException()
                return self.get_properties()[GATT_SERVICE]

        class Characteristic(dbus.service.Object):
            def __init__(self, system_bus: Any, index: int, uuid: str, flags: Iterable[str], service: Any):
                self.path = service.path + "/char" + str(index)
                self.uuid = uuid
                self.service = service
                self.flags = list(flags)
                dbus.service.Object.__init__(self, system_bus, self.path)

            def get_properties(self) -> Dict[str, Dict[str, Any]]:
                return {GATT_CHRC: {"Service": self.service.get_path(), "UUID": self.uuid, "Flags": dbus.Array(self.flags, signature="s")}}

            def get_path(self) -> Any:
                return dbus.ObjectPath(self.path)

            @dbus.service.method(DBUS_PROP, in_signature="s", out_signature="a{sv}")
            def GetAll(self, interface: str) -> Dict[str, Any]:
                if interface != GATT_CHRC:
                    raise InvalidArgsException()
                return self.get_properties()[GATT_CHRC]

            @dbus.service.method(GATT_CHRC, in_signature="a{sv}", out_signature="ay")
            def ReadValue(self, options: Dict[str, Any]) -> List[Any]:
                return []

            @dbus.service.method(GATT_CHRC, in_signature="aya{sv}")
            def WriteValue(self, value: List[Any], options: Dict[str, Any]) -> None:
                return None

            @dbus.service.method(GATT_CHRC)
            def StartNotify(self) -> None:
                return None

            @dbus.service.method(GATT_CHRC)
            def StopNotify(self) -> None:
                return None

            @dbus.service.signal(DBUS_PROP, signature="sa{sv}as")
            def PropertiesChanged(self, interface: str, changed: Dict[str, Any], invalidated: List[str]) -> None:
                return None

        outer = self

        class TxCharacteristic(Characteristic):
            def __init__(self, system_bus: Any, index: int, service: Any):
                super().__init__(system_bus, index, outer.NUS_TX_UUID, ["notify"], service)
                self.notifying = False

            @dbus.service.method(GATT_CHRC)
            def StartNotify(self) -> None:
                self.notifying = True

            @dbus.service.method(GATT_CHRC)
            def StopNotify(self) -> None:
                self.notifying = False

            def notify_bytes(self, data: bytes) -> None:
                if not self.notifying:
                    return
                value = dbus.Array([dbus.Byte(b) for b in data], signature="y")
                self.PropertiesChanged(GATT_CHRC, {"Value": value}, [])

        class RxCharacteristic(Characteristic):
            def __init__(self, system_bus: Any, index: int, service: Any):
                super().__init__(system_bus, index, outer.NUS_RX_UUID, ["write", "write-without-response"], service)

            @dbus.service.method(GATT_CHRC, in_signature="aya{sv}")
            def WriteValue(self, value: List[Any], options: Dict[str, Any]) -> None:
                data = bytes(bytearray(value)).decode("utf-8", errors="ignore")
                for line in data.splitlines():
                    command = line.strip()
                    if command:
                        outer.on_rx(command)

        class NusService(Service):
            def __init__(self, system_bus: Any, index: int):
                super().__init__(system_bus, index, outer.NUS_SERVICE_UUID, True)
                self.tx = TxCharacteristic(system_bus, 0, self)
                self.rx = RxCharacteristic(system_bus, 1, self)
                self.add_characteristic(self.tx)
                self.add_characteristic(self.rx)

        class Advertisement(dbus.service.Object):
            PATH_BASE = "/org/bluez/example/advertisement"

            def __init__(self, system_bus: Any, index: int, local_name: str):
                self.path = self.PATH_BASE + str(index)
                self.local_name = local_name
                dbus.service.Object.__init__(self, system_bus, self.path)

            def get_path(self) -> Any:
                return dbus.ObjectPath(self.path)

            @dbus.service.method(DBUS_PROP, in_signature="s", out_signature="a{sv}")
            def GetAll(self, interface: str) -> Dict[str, Any]:
                if interface != LE_ADV:
                    raise InvalidArgsException()
                return {
                    "Type": "peripheral",
                    "ServiceUUIDs": dbus.Array([outer.NUS_SERVICE_UUID], signature="s"),
                    "LocalName": self.local_name,
                    "Includes": dbus.Array(["tx-power"], signature="s"),
                }

            @dbus.service.method(LE_ADV, in_signature="", out_signature="")
            def Release(self) -> None:
                return None

        manager_object = bus.get_object(BLUEZ, "/")
        object_manager = dbus.Interface(manager_object, DBUS_OM)
        adapter_path = None
        for path, interfaces in object_manager.GetManagedObjects().items():
            if GATT_MANAGER in interfaces and LE_ADV_MANAGER in interfaces:
                adapter_path = path
                break
        if adapter_path is None:
            raise RuntimeError("No BlueZ adapter with GATT/advertising found. Run: bluetoothctl power on")

        adapter_obj = bus.get_object(BLUEZ, adapter_path)
        gatt_manager = dbus.Interface(adapter_obj, GATT_MANAGER)
        adv_manager = dbus.Interface(adapter_obj, LE_ADV_MANAGER)

        app = Application(bus)
        service = NusService(bus, 0)
        app.add_service(service)
        adv = Advertisement(bus, 0, self.name)
        self.tx = service.tx
        self.mainloop = GLib.MainLoop()

        def ok_register(msg: str) -> Callable[[], None]:
            def _ok() -> None:
                print(msg, flush=True)
            return _ok

        def err_register(prefix: str) -> Callable[[Any], None]:
            def _err(error: Any) -> None:
                print(f"WARN {prefix}: {error}", file=sys.stderr, flush=True)
            return _err

        gatt_manager.RegisterApplication(app.get_path(), {}, reply_handler=ok_register("BLE GATT registered"), error_handler=err_register("BLE GATT registration failed"))
        adv_manager.RegisterAdvertisement(adv.get_path(), {}, reply_handler=ok_register("BLE advertisement registered"), error_handler=err_register("BLE advertisement failed"))
        self.thread = threading.Thread(target=self.mainloop.run, daemon=True)
        self.thread.start()
        self.ready = True

    def send_line(self, line: str) -> None:
        if not self.ready or self.tx is None or self.GLib is None:
            return
        payload = (line.rstrip() + "\n").encode("utf-8", errors="replace")

        def _send() -> bool:
            if self.tx is None:
                return False
            for start in range(0, len(payload), 20):
                self.tx.notify_bytes(payload[start : start + 20])
            return False

        self.GLib.idle_add(_send)

    def stop(self) -> None:
        if self.mainloop is not None and self.GLib is not None:
            self.GLib.idle_add(self.mainloop.quit)


class SerialLineReader:
    def __init__(self, device: str, baud: int):
        self.device = device
        self.baud = baud
        self.fd: Optional[int] = None

    def __enter__(self) -> "SerialLineReader":
        self.fd = self._open()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def lines(self) -> Iterator[str]:
        if self.fd is None:
            raise RuntimeError("serial device is not open")
        buf = b""
        while True:
            try:
                data = os.read(self.fd, 256)
            except BlockingIOError:
                time.sleep(0.02)
                continue
            if not data:
                time.sleep(0.02)
                continue
            buf += data
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("ascii", errors="ignore").strip()
                if line:
                    yield line

    def _open(self) -> int:
        import termios

        fd = os.open(self.device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(fd)
        speed = self._baud_flag(termios)
        attrs[0] = 0
        attrs[1] = 0
        attrs[2] = termios.CLOCAL | termios.CREAD | termios.CS8
        attrs[3] = 0
        attrs[4] = speed
        attrs[5] = speed
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 5
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIOFLUSH)
        return fd

    def _baud_flag(self, termios_module: Any) -> int:
        name = "B" + str(int(self.baud))
        if not hasattr(termios_module, name):
            raise RuntimeError(f"unsupported baud rate: {self.baud}")
        return int(getattr(termios_module, name))


class TrackerApp:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.serial_device = str(cfg["serial"]["device"])
        self.baud = int(cfg["serial"]["baud"])
        self.chunk_size = int(cfg["track"].get("chunk_size", 25))
        self.location = NmeaLocationTracker()
        self.store = TrackStore(str(cfg["track"]["data_dir"]))
        self.live_enabled = False
        self.last_live_emit = 0.0
        self.ble: Optional[BleNusServer] = None
        self.stop_requested = False

    def start_ble(self) -> None:
        self.ble = BleNusServer(str(self.cfg["output"]["ble_name"]), self.handle_command)
        self.ble.start()
        print(f"BLE enabled as {self.cfg['output']['ble_name']}", flush=True)

    def handle_command(self, command: str) -> None:
        for line in command.splitlines():
            text = line.strip()
            if not text:
                continue
            self._handle_one_command(text)

    def _handle_one_command(self, command: str) -> None:
        parts = command.split()
        op = parts[0].upper()
        try:
            if op == "TL":
                self.send_frame({"typ": "tl", "items": self.store.list_tracks()})
            elif op == "TG":
                track_index = int(parts[1]) if len(parts) > 1 else 0
                offset = int(parts[2]) if len(parts) > 2 else 0
                self.send_frame(self.store.chunk(track_index, offset, self.chunk_size))
            elif op == "TF":
                self.live_enabled = len(parts) < 2 or parts[1] not in ("0", "off", "OFF")
                frame = self.status_frame()
                frame["live"] = 1 if self.live_enabled else 0
                self.send_frame(frame)
            elif op == "TS":
                self.send_frame(self.status_frame())
            else:
                self.send_text("ERR unknown command " + command)
        except (IndexError, ValueError) as exc:
            self.send_text("ERR bad command " + command + " " + str(exc))

    def status_frame(self) -> Dict[str, Any]:
        return self.location.status(self.serial_device, self.baud, self.store.count())

    def send_frame(self, frame: Dict[str, Any]) -> None:
        self.send_text(json.dumps(frame, ensure_ascii=False, separators=(",", ":")))

    def send_text(self, text: str) -> None:
        if bool(self.cfg["output"].get("console", True)):
            print(text, flush=True)
        if self.ble is not None:
            self.ble.send_line(text)

    def handle_nmea_line(self, line: str) -> Optional[Dict[str, Any]]:
        if bool(self.cfg["serial"].get("dump_nmea", False)):
            print(line, flush=True)
        point = self.location.update(line)
        if point is None:
            return None
        self.store.append(point)
        live_hz = max(0.1, float(self.cfg["output"].get("live_hz", 1.0)))
        now = time.monotonic()
        if self.live_enabled and now - self.last_live_emit >= 1.0 / live_hz:
            self.send_frame(point)
            self.last_live_emit = now
        return point

    def run_serial(self) -> None:
        with SerialLineReader(self.serial_device, self.baud) as reader:
            for line in reader.lines():
                if self.stop_requested:
                    break
                self.handle_nmea_line(line)

    def run_simulation(self, once: bool = False) -> None:
        samples = [
            "$GPGGA,073028.600,2236.40101,N,11349.73472,E,1,19,0.8,42.0,M,0.0,M,,*58",
            "$GPRMC,073028.600,A,2236.40101,N,11349.73472,E,000.8,092.0,090724,000.0,E*61",
            "$GPGGA,073029.600,2236.40150,N,11349.73520,E,1,19,0.8,42.3,M,0.0,M,,*58",
            "$GPRMC,073029.600,A,2236.40150,N,11349.73520,E,001.0,094.0,090724,000.0,E*6D",
        ]
        self.live_enabled = True
        while not self.stop_requested:
            for line in samples:
                self.handle_nmea_line(line)
                time.sleep(0.05)
            self.send_frame({"typ": "tl", "items": self.store.list_tracks()})
            self.send_frame(self.store.chunk(0, 0, self.chunk_size))
            self.send_frame(self.status_frame())
            if once:
                break
            time.sleep(1.0)

    def stop(self) -> None:
        self.stop_requested = True
        if self.ble is not None:
            self.ble.stop()


def apply_overrides(cfg: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    result = deep_merge({}, cfg)
    if args.serial_device:
        result["serial"]["device"] = args.serial_device
    if args.baud:
        result["serial"]["baud"] = args.baud
    if args.track_dir:
        result["track"]["data_dir"] = args.track_dir
    if args.ble_name:
        result["output"]["ble_name"] = args.ble_name
    if args.no_ble:
        result["output"]["ble_enabled"] = False
    if args.ble:
        result["output"]["ble_enabled"] = True
    if args.dump_nmea:
        result["serial"]["dump_nmea"] = True
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DX-GP21 GNSS tracker for SS928")
    parser.add_argument("--config", help="JSON config path")
    parser.add_argument("--serial-device", help="UART device, for example /dev/ttyAMA4")
    parser.add_argument("--baud", type=int, help="UART baud rate")
    parser.add_argument("--track-dir", help="Track JSONL directory")
    parser.add_argument("--ble-name", help="BLE advertisement name")
    parser.add_argument("--ble", action="store_true", help="Force BLE on")
    parser.add_argument("--no-ble", action="store_true", help="Disable BLE")
    parser.add_argument("--dump-nmea", action="store_true", help="Print raw NMEA lines")
    parser.add_argument("--simulate", action="store_true", help="Run without UART using sample NMEA")
    parser.add_argument("--once", action="store_true", help="Exit after one simulated batch")
    parser.add_argument("--command-stdin", action="store_true", help="Read TL/TG/TF/TS commands from stdin for the unified board service")
    return parser


def start_command_stdin(app: TrackerApp) -> threading.Thread:
    def _reader() -> None:
        for line in sys.stdin:
            if app.stop_requested:
                break
            text = line.strip()
            if text:
                app.handle_command(text)

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    return thread


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = apply_overrides(load_config(args.config), args)
    app = TrackerApp(cfg)

    def _stop(signum: int, frame: Any) -> None:
        app.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    if args.command_stdin:
        start_command_stdin(app)

    if bool(cfg["output"].get("ble_enabled", False)) and not args.simulate:
        try:
            app.start_ble()
        except RuntimeError as exc:
            print(f"WARN BLE disabled: {exc}", file=sys.stderr, flush=True)

    if args.simulate:
        app.run_simulation(once=args.once)
    else:
        app.run_serial()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
