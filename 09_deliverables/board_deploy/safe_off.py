#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def _disable_exported_pwm(root: Path) -> None:
    for enable in root.glob("pwmchip*/pwm*/enable"):
        try:
            enable.write_text("0\n", encoding="ascii")
        except OSError as exc:
            print(f"WARN could not disable {enable}: {exc}", file=sys.stderr)


def _stop_tm6605(config: dict[str, object]) -> None:
    controller = Path("/root/smartbag/controller")
    common = Path("/root/smartbag/common")
    for path in (controller, common):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    from tm6605_haptics import LinuxI2cBus, Tm6605Haptics

    outputs = config.get("outputs", {})
    if not isinstance(outputs, dict) or outputs.get("haptics_backend") != "tm6605":
        return
    mux_value = outputs.get("tm6605_mux_address", "0x70")
    mux_address = int(str(mux_value), 0) if mux_value not in (None, "", False) else None
    haptics = Tm6605Haptics(
        LinuxI2cBus(Path(str(outputs.get("i2c_device", "/dev/i2c-0")))),
        mux_address=mux_address,
        channels={
            "left": int(outputs.get("left_tm6605_channel", 1)),
            "right": int(outputs.get("right_tm6605_channel", 2)),
        },
        connected_sides=tuple(str(side) for side in outputs.get("tm6605_connected_sides", ["left", "right"])),
    )
    haptics.stop_all()


def main() -> int:
    config_path = Path(sys.argv[1] if len(sys.argv) > 1 else "/etc/smartbag/config.json")
    config: dict[str, object] = {}
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"WARN could not read {config_path}: {exc}", file=sys.stderr)
    try:
        _stop_tm6605(config)
    except Exception as exc:
        print(f"WARN could not stop TM6605: {exc}", file=sys.stderr)
    _disable_exported_pwm(Path("/sys/class/pwm"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
