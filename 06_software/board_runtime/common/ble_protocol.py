from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BleRoute:
    namespace: str
    command: str
    legacy: bool = False


def route_ble_command(text: str) -> BleRoute:
    command = str(text or "").strip()
    if not command:
        raise ValueError("empty BLE command")
    parts = command.split(maxsplit=1)
    namespace = parts[0].upper()
    payload = parts[1].strip() if len(parts) == 2 else ""

    if namespace in ("AL", "GNSS", "IMU", "SYS"):
        if not payload:
            raise ValueError(f"{namespace} command requires a payload")
        return BleRoute(namespace, payload)

    op = namespace
    if op in ("TL", "TG", "TF", "TS"):
        return BleRoute("GNSS", command, legacy=True)
    if op in (
        "STATUS",
        "ZERO",
        "ZERO_V",
        "RESET",
        "RESET_V",
        "SET",
        "HELP",
        "CAL_START",
        "CAL_STOP",
        "CAL_STATUS",
        "CAL_MODES",
        "CS",
        "CE",
        "C?",
        "CM",
    ):
        return BleRoute("IMU", command, legacy=True)
    raise ValueError(f"unsupported BLE command namespace: {namespace}")
