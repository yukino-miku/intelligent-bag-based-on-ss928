from __future__ import annotations

import sys
import threading
from typing import Any, Callable, Dict, Iterable, List, Optional


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
            raise RuntimeError(
                "BLE needs BlueZ Python packages: python3-dbus and python3-gi"
            ) from exc

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
            PATH_BASE = "/org/bluez/smartbag/service"

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
                        "Characteristics": dbus.Array(
                            [chrc.get_path() for chrc in self.characteristics],
                            signature="o",
                        ),
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
            def __init__(
                self,
                system_bus: Any,
                index: int,
                uuid: str,
                flags: Iterable[str],
                service: Any,
            ):
                self.path = service.path + "/char" + str(index)
                self.uuid = uuid
                self.service = service
                self.flags = list(flags)
                dbus.service.Object.__init__(self, system_bus, self.path)

            def get_properties(self) -> Dict[str, Dict[str, Any]]:
                return {
                    GATT_CHRC: {
                        "Service": self.service.get_path(),
                        "UUID": self.uuid,
                        "Flags": dbus.Array(self.flags, signature="s"),
                    }
                }

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
            def PropertiesChanged(
                self, interface: str, changed: Dict[str, Any], invalidated: List[str]
            ) -> None:
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
                super().__init__(
                    system_bus,
                    index,
                    outer.NUS_RX_UUID,
                    ["write", "write-without-response"],
                    service,
                )

            @dbus.service.method(GATT_CHRC, in_signature="aya{sv}")
            def WriteValue(self, value: List[Any], options: Dict[str, Any]) -> None:
                data = bytes(bytearray(value)).decode("utf-8", errors="ignore").strip()
                if data:
                    outer.on_rx(data)

        class NusService(Service):
            def __init__(self, system_bus: Any, index: int):
                super().__init__(system_bus, index, outer.NUS_SERVICE_UUID, True)
                self.tx = TxCharacteristic(system_bus, 0, self)
                self.rx = RxCharacteristic(system_bus, 1, self)
                self.add_characteristic(self.tx)
                self.add_characteristic(self.rx)

        class Advertisement(dbus.service.Object):
            PATH_BASE = "/org/bluez/smartbag/advertisement"

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
            raise RuntimeError(
                "No BlueZ adapter with GATT/advertising found. Run: bluetoothctl power on"
            )

        adapter_obj = bus.get_object(BLUEZ, adapter_path)
        gatt_manager = dbus.Interface(adapter_obj, GATT_MANAGER)
        adv_manager = dbus.Interface(adapter_obj, LE_ADV_MANAGER)

        app = Application(bus)
        service = NusService(bus, 0)
        app.add_service(service)
        adv = Advertisement(bus, 0, self.name)
        self.tx = service.tx

        def ok_register(msg: str) -> Callable[[], None]:
            def _ok() -> None:
                print(msg, file=sys.stderr, flush=True)

            return _ok

        def err_register(prefix: str) -> Callable[[Any], None]:
            def _err(error: Any) -> None:
                print(f"WARN {prefix}: {error}", file=sys.stderr, flush=True)

            return _err

        self.mainloop = GLib.MainLoop()
        gatt_manager.RegisterApplication(
            app.get_path(),
            {},
            reply_handler=ok_register("BLE GATT registered"),
            error_handler=err_register("BLE GATT registration failed"),
        )
        adv_manager.RegisterAdvertisement(
            adv.get_path(),
            {},
            reply_handler=ok_register("BLE advertisement registered"),
            error_handler=err_register("BLE advertisement failed"),
        )
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
