#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import time
from typing import Iterable


TSENSOR_PATTERN = re.compile(r"TSENSOR\[(\d+)\]\s+DATA:\s+(-?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class TemperatureReading:
    status: str
    values_c: dict[str, float]
    source: str
    error: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=True, separators=(",", ":"))


def parse_tsensor_text(text: str, source: str = "/proc/Tsensor") -> TemperatureReading:
    values = {int(index): float(value) for index, value in TSENSOR_PATTERN.findall(text)}
    if not all(index in values for index in (0, 1, 2)):
        return TemperatureReading("invalid", {}, source, "expected TSENSOR channels 0, 1, and 2")
    return TemperatureReading(
        "ok",
        {f"tsensor{index}": values[index] for index in (0, 1, 2)},
        source,
    )


def read_temperature(path: str | Path = "/proc/Tsensor") -> TemperatureReading:
    source = str(path)
    try:
        return parse_tsensor_text(Path(path).read_text(encoding="utf-8"), source)
    except OSError as exc:
        return TemperatureReading("unavailable", {}, source, f"{type(exc).__name__}: {exc}")


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read SS928 /proc/Tsensor with explicit failure status.")
    parser.add_argument("--path", default="/proc/Tsensor")
    parser.add_argument("--interval", type=float, default=0.0, help="Repeat interval; zero prints once.")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    while True:
        reading = read_temperature(args.path)
        print(reading.to_json(), flush=True)
        if args.interval <= 0:
            return 0 if reading.status == "ok" else 1
        time.sleep(max(0.1, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
