#!/usr/bin/env python3
"""JSON event runner for imu_fall_detector.py.

stdin CSV format:
    t,ax,ay,az,gx,gy,gz

stdin JSONL formats:
    {"t": 1.23, "ax": 0, "ay": 0, "az": 1, "gx": 0, "gy": 0, "gz": 0}
    {"t": 1.23, "a": [0, 0, 1], "w": [0, 0, 0]}
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Iterable, Iterator, Optional

from imu_fall_detector import (
    DetectorConfig,
    FallImpactDetector,
    ImuSample,
    event_to_json,
    load_config,
)


def parse_sample_line(line: str) -> ImuSample:
    text = line.strip()
    if not text:
        raise ValueError("empty input line")
    if text.startswith("{"):
        return _parse_json_sample(json.loads(text))
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 7:
        raise ValueError("CSV input must be: t,ax,ay,az,gx,gy,gz")
    values = [float(part) for part in parts]
    return ImuSample(*values)


def _parse_json_sample(obj: Dict[str, Any]) -> ImuSample:
    t = _required_float(obj, "t")
    if "a" in obj:
        ax, ay, az = _triple(obj["a"], "a")
    else:
        ax = _required_float(obj, "ax")
        ay = _required_float(obj, "ay")
        az = _required_float(obj, "az")
    if "w" in obj:
        gx, gy, gz = _triple(obj["w"], "w")
    elif "g" in obj and not all(k in obj for k in ("gx", "gy", "gz")):
        gx, gy, gz = _triple(obj["g"], "g")
    else:
        gx = _required_float(obj, "gx")
        gy = _required_float(obj, "gy")
        gz = _required_float(obj, "gz")
    return ImuSample(t=t, ax=ax, ay=ay, az=az, gx=gx, gy=gy, gz=gz)


def _required_float(obj: Dict[str, Any], key: str) -> float:
    if key not in obj:
        raise ValueError("missing JSON field: " + key)
    return float(obj[key])


def _triple(value: Any, key: str):
    if not isinstance(value, list) and not isinstance(value, tuple):
        raise ValueError(key + " must be an array")
    if len(value) != 3:
        raise ValueError(key + " must contain 3 numbers")
    return (float(value[0]), float(value[1]), float(value[2]))


def iter_stdin_samples(lines: Iterable[str], keep_bad_lines: bool = False) -> Iterator[ImuSample]:
    for lineno, line in enumerate(lines, 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        try:
            yield parse_sample_line(text)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            if keep_bad_lines:
                print(f"WARN line {lineno}: {exc}", file=sys.stderr, flush=True)
                continue
            raise ValueError(f"line {lineno}: {exc}") from exc


def simulate_fall(sample_hz: float) -> Iterator[ImuSample]:
    t = 0.0
    dt = 1.0 / sample_hz
    for _ in range(int(sample_hz * 0.5)):
        yield ImuSample(t, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
        t += dt
    for _ in range(int(sample_hz * 0.16)):
        yield ImuSample(t, 0.0, 0.0, 0.18, 280.0, 0.0, 0.0)
        t += dt
    for _ in range(2):
        yield ImuSample(t, 0.0, 0.0, 3.4, 420.0, 0.0, 0.0)
        t += dt
    for _ in range(int(sample_hz * 1.0)):
        yield ImuSample(t, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0)
        t += dt


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="IMU fall/impact detector JSON event runner")
    parser.add_argument("--config", help="JSON config file, for example config.example.json")
    parser.add_argument("--sample-hz", type=float, help="override configured sample rate")
    parser.add_argument("--simulate", action="store_true", help="emit events from a built-in fall sequence")
    parser.add_argument(
        "--keep-bad-lines",
        action="store_true",
        help="warn and continue when one input line is malformed",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = load_config(args.config) if args.config else DetectorConfig()
    if args.sample_hz:
        config.sample_hz = args.sample_hz
    detector = FallImpactDetector(config)

    if args.simulate:
        samples = simulate_fall(config.sample_hz)
    else:
        samples = iter_stdin_samples(sys.stdin, keep_bad_lines=args.keep_bad_lines)

    for sample in samples:
        for event in detector.update(sample):
            print(event_to_json(event), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
