from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


class ResourceSampler:
    """Read lightweight Linux resource metrics without adding psutil."""

    def __init__(self) -> None:
        self._last_cpu_total: int | None = None
        self._last_cpu_idle: int | None = None
        self._lock = threading.Lock()

    def sample(self) -> dict[str, float | None]:
        with self._lock:
            return {
                "cpu_percent": self._cpu_percent(),
                "memory_percent": self._memory_percent(),
                "temperature_c": self._temperature_c(),
                "load_1m": self._load_1m(),
            }

    def _cpu_percent(self) -> float | None:
        try:
            fields = Path("/proc/stat").read_text(encoding="ascii").splitlines()[0].split()[1:]
            values = [int(value) for value in fields]
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            total = sum(values)
        except (OSError, ValueError, IndexError):
            return None

        previous_total = self._last_cpu_total
        previous_idle = self._last_cpu_idle
        self._last_cpu_total = total
        self._last_cpu_idle = idle
        if previous_total is None or previous_idle is None or total <= previous_total:
            return None
        total_delta = total - previous_total
        idle_delta = max(0, idle - previous_idle)
        return round(100.0 * (1.0 - idle_delta / total_delta), 1)

    @staticmethod
    def _memory_percent() -> float | None:
        try:
            values: dict[str, int] = {}
            for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
                key, value = line.split(":", 1)
                values[key] = int(value.strip().split()[0])
            total = values["MemTotal"]
            available = values.get("MemAvailable", values.get("MemFree", 0))
            return round(100.0 * (total - available) / max(total, 1), 1)
        except (OSError, ValueError, KeyError):
            return None

    @staticmethod
    def _temperature_c() -> float | None:
        temperatures: list[float] = []
        for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
            try:
                value = float(path.read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                continue
            if value > 1000.0:
                value /= 1000.0
            if -20.0 <= value <= 150.0:
                temperatures.append(value)
        return round(max(temperatures), 1) if temperatures else None

    @staticmethod
    def _load_1m() -> float | None:
        try:
            return round(float(os.getloadavg()[0]), 2)
        except (AttributeError, OSError):
            return None


def atomic_write_json(path: str | os.PathLike[str], payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=output_path.name + ".", dir=str(output_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, separators=(",", ":"))
            handle.write("\n")
        os.replace(temporary_name, output_path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def status_timestamp() -> float:
    return round(time.monotonic(), 6)
