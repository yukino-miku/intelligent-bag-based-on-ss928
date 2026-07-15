#!/usr/bin/env python3
"""
BMI270 backpack posture monitor for embedded Linux.

The program reads a BMI270 through Linux IIO, estimates posture and rough
velocity, emits alert pulses, and optionally publishes data through BLE
Nordic UART Service using BlueZ.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import queue
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from fall_bridge import FallEventBridge

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows simulation only.
    fcntl = None  # type: ignore[assignment]


G = 9.80665


DEFAULT_CONFIG: Dict[str, Any] = {
    "device": {
        "backend": "auto",
        "iio_path": "auto",
        "i2c_bus": 0,
        "i2c_addr": "0x68",
        "config_blob": "auto",
        "init_sensor": True,
        "sample_hz": 50.0,
    },
    "filter": {
        "gyro_alpha": 0.98,
        "linear_acc_deadband_mps2": 0.18,
        "stationary_accel_tolerance_g": 0.06,
        "stationary_gyro_dps": 3.0,
        "stationary_hold_s": 0.45,
        "velocity_damping_per_s": 0.15,
        "max_speed_mps": 8.0,
    },
    "posture": {
        "enabled": False,
        "roll_zero_deg": 0.0,
        "pitch_zero_deg": 0.0,
        "yaw_zero_deg": 0.0,
    },
    "thresholds": {
        "tilt_enabled": True,
        "pitch_forward_deg": 35.0,
        "pitch_backward_deg": -35.0,
        "roll_left_deg": -45.0,
        "roll_right_deg": 45.0,
        "tilt_hold_s": 0.8,
        "hunch_enabled": True,
        "hunch_pitch_deg": -15.5,
        "hunch_hold_s": 3.0,
        "hunch_max_gyro_dps": 30.0,
        "hunch_accel_min_g": 0.75,
        "hunch_accel_max_g": 1.25,
        "impact_g": 2.8,
        "freefall_g": 0.35,
        "freefall_hold_s": 0.25,
        "speed_warn_mps": 2.5,
        "speed_hold_s": 1.0,
        "alert_cooldown_s": 3.0,
    },
    "output": {
        "console_hz": 5.0,
        "ble_enabled": False,
        "ble_hz": 10.0,
        "ble_name": "SS928-SmartBag",
        "alert_file": "",
        "alert_active_value": "1",
        "alert_inactive_value": "0",
        "alert_pulse_ms": 300,
        "alert_command": [],
    },
    "calibration": {
        "data_dir": "/var/lib/smartbag/calibration",
        "modes": {
            "straight": {
                "label": "straight standing with backpack",
                "prefix": "straight",
                "duration_s": 15.0,
            },
            "hunch": {
                "label": "hunched standing with backpack",
                "prefix": "hunch",
                "duration_s": 15.0,
            },
            "straight_walk": {
                "label": "normal standing and walking",
                "prefix": "straight_walk",
                "duration_s": 30.0,
            },
            "hunch_walk": {
                "label": "hunched walking",
                "prefix": "hunch_walk",
                "duration_s": 30.0,
            },
            "bend_pickup": {
                "label": "bend, pick up, adjust backpack",
                "prefix": "bend_pickup",
                "duration_s": 30.0,
            },
        },
    },
    "fall_detection": {
        "enabled": True,
    },
}


@dataclass
class ImuSample:
    t: float
    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float


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
            user_cfg = json.load(f)
        cfg = deep_merge(DEFAULT_CONFIG, user_cfg)
    return cfg


def read_number(path: Path) -> Optional[float]:
    try:
        text = path.read_text(encoding="ascii", errors="ignore").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        return float(text.split()[0])
    except ValueError:
        return None


def norm3(v: Tuple[float, float, float]) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def wrap_pi(value: float) -> float:
    while value > math.pi:
        value -= 2.0 * math.pi
    while value < -math.pi:
        value += 2.0 * math.pi
    return value


def wrap_deg(value: float) -> float:
    while value > 180.0:
        value -= 360.0
    while value < -180.0:
        value += 360.0
    return value


def apply_posture_correction(state: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    posture = cfg.get("posture", {})
    if not bool(posture.get("enabled", False)):
        return state

    corrected = dict(state)
    raw_roll = float(state.get("roll_deg", 0.0))
    raw_pitch = float(state.get("pitch_deg", 0.0))
    raw_yaw = float(state.get("yaw_deg", 0.0))
    corrected["raw_roll_deg"] = raw_roll
    corrected["raw_pitch_deg"] = raw_pitch
    corrected["raw_yaw_deg"] = raw_yaw
    corrected["roll_deg"] = wrap_deg(raw_roll - float(posture.get("roll_zero_deg", 0.0)))
    corrected["pitch_deg"] = raw_pitch - float(posture.get("pitch_zero_deg", 0.0))
    corrected["yaw_deg"] = wrap_deg(raw_yaw - float(posture.get("yaw_zero_deg", 0.0)))
    corrected["posture_corrected"] = True
    return corrected


def parse_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    return int(str(value), 0)


def find_i2c_buses() -> List[int]:
    buses: List[int] = []
    for path in sorted(Path("/dev").glob("i2c-*")):
        try:
            buses.append(int(path.name.split("-", 1)[1]))
        except (IndexError, ValueError):
            pass
    return buses


def load_bmi270_config_blob(path_value: Any) -> bytes:
    if path_value and str(path_value) != "auto":
        return Path(str(path_value)).read_bytes()

    base = Path(__file__).resolve().parent
    candidates = [
        base / "bmi270_config.bin",
        base.parent / "STM32(HAL库)keil" / "Extend" / "inc" / "BMI270_config.h",
        base.parent / "STM32(标准库)keil" / "Extend" / "inc" / "BMI270_config.h",
    ]
    for path in candidates:
        if not path.exists():
            continue
        if path.suffix.lower() == ".bin":
            return path.read_bytes()
        numbers = re.findall(
            r"0x([0-9a-fA-F]{1,2})",
            path.read_text(encoding="ascii", errors="ignore"),
        )
        data = bytes(int(item, 16) for item in numbers)
        if data:
            return data
    raise RuntimeError(
        "BMI270 config blob not found. Copy bmi270_config.bin next to this script "
        "or set device.config_blob."
    )


class IioImu:
    """Read accel and gyro channels from /sys/bus/iio/devices/iio:deviceX."""

    REQUIRED = (
        "in_accel_x_raw",
        "in_accel_y_raw",
        "in_accel_z_raw",
        "in_anglvel_x_raw",
        "in_anglvel_y_raw",
        "in_anglvel_z_raw",
    )

    # Fallback values match the STM32 example: accel +-16 g, gyro +-2000 dps.
    FALLBACK_ACCEL_SCALE = G / 2048.0
    FALLBACK_GYRO_SCALE = (math.pi / 180.0) / 16.4

    def __init__(self, path: str):
        self.path = Path(path)
        missing = [name for name in self.REQUIRED if not (self.path / name).exists()]
        if missing:
            raise RuntimeError(
                "IIO device is missing channels: " + ", ".join(missing)
            )
        self.accel_scale = self._scale("in_accel", self.FALLBACK_ACCEL_SCALE)
        self.gyro_scale = self._scale("in_anglvel", self.FALLBACK_GYRO_SCALE)
        self.accel_offset = self._offsets("in_accel")
        self.gyro_offset = self._offsets("in_anglvel")

    @staticmethod
    def list_devices(root: Path = Path("/sys/bus/iio/devices")) -> List[Dict[str, str]]:
        devices: List[Dict[str, str]] = []
        if not root.exists():
            return devices
        for path in sorted(root.glob("iio:device*")):
            name = ""
            try:
                name = (path / "name").read_text(encoding="ascii", errors="ignore").strip()
            except OSError:
                pass
            channels = [p.name for p in path.glob("in_*_raw")]
            devices.append(
                {
                    "path": str(path),
                    "name": name,
                    "channels": ",".join(sorted(channels)),
                }
            )
        return devices

    @classmethod
    def auto_find(cls) -> str:
        candidates = cls.list_devices()
        for item in candidates:
            path = Path(item["path"])
            name = item["name"].lower()
            has_required = all((path / channel).exists() for channel in cls.REQUIRED)
            if has_required and ("bmi270" in name or "bmi2" in name or "bmi" in name):
                return str(path)
        for item in candidates:
            path = Path(item["path"])
            if all((path / channel).exists() for channel in cls.REQUIRED):
                return str(path)
        raise RuntimeError(
            "No BMI270 IIO device found. Try --list-iio or set device.iio_path."
        )

    def _scale(self, prefix: str, fallback: float) -> Tuple[float, float, float]:
        common = read_number(self.path / f"{prefix}_scale")
        values = []
        for axis in ("x", "y", "z"):
            axis_value = read_number(self.path / f"{prefix}_{axis}_scale")
            values.append(axis_value if axis_value is not None else common)
        return tuple(value if value is not None else fallback for value in values)  # type: ignore[return-value]

    def _offsets(self, prefix: str) -> Tuple[float, float, float]:
        values = []
        for axis in ("x", "y", "z"):
            values.append(read_number(self.path / f"{prefix}_{axis}_offset") or 0.0)
        return tuple(values)  # type: ignore[return-value]

    def _read_axis(self, prefix: str, axis: str, scale: float, offset: float) -> float:
        raw = read_number(self.path / f"{prefix}_{axis}_raw")
        if raw is None:
            raise RuntimeError(f"Failed to read {prefix}_{axis}_raw")
        return (raw + offset) * scale

    def read(self) -> ImuSample:
        ax = self._read_axis("in_accel", "x", self.accel_scale[0], self.accel_offset[0])
        ay = self._read_axis("in_accel", "y", self.accel_scale[1], self.accel_offset[1])
        az = self._read_axis("in_accel", "z", self.accel_scale[2], self.accel_offset[2])
        gx = self._read_axis("in_anglvel", "x", self.gyro_scale[0], self.gyro_offset[0])
        gy = self._read_axis("in_anglvel", "y", self.gyro_scale[1], self.gyro_offset[1])
        gz = self._read_axis("in_anglvel", "z", self.gyro_scale[2], self.gyro_offset[2])
        return ImuSample(time.monotonic(), ax, ay, az, gx, gy, gz)


class UserspaceI2cBmi270:
    """BMI270 reader using /dev/i2c-X directly when no kernel IIO driver exists."""

    I2C_SLAVE = 0x0703

    CHIP_ID = 0x00
    EXPECTED_CHIP_ID = 0x24
    ACC_X_LSB = 0x0C
    INTERNAL_STATUS = 0x21
    ACC_CONF = 0x40
    ACC_RANGE = 0x41
    GYR_CONF = 0x42
    GYR_RANGE = 0x43
    INIT_CTRL = 0x59
    INIT_ADDR_0 = 0x5B
    INIT_ADDR_1 = 0x5C
    INIT_DATA = 0x5E
    IF_CONF = 0x6B
    NV_CONF = 0x70
    PWR_CONF = 0x7C
    PWR_CTRL = 0x7D

    ACC_RANGE_16G = 0x03
    GYR_RANGE_2000_DPS = 0x00
    ACC_GYRO_RATE_200HZ_WITH_FILTER = 0x09 | 0x20 | 0x80

    ACC_SCALE = G / 2048.0
    GYRO_SCALE = (math.pi / 180.0) / 16.4

    def __init__(
        self,
        bus: int,
        addr: int,
        config_blob: Any = "auto",
        init_sensor: bool = True,
    ):
        if fcntl is None:
            raise RuntimeError("Userspace I2C backend needs Linux fcntl/i2c-dev")
        self.bus = bus
        self.addr = addr
        self.dev_path = f"/dev/i2c-{bus}"
        self.fd = os.open(self.dev_path, os.O_RDWR)
        fcntl.ioctl(self.fd, self.I2C_SLAVE, addr)
        chip_id = self.read_reg(self.CHIP_ID)
        if chip_id != self.EXPECTED_CHIP_ID:
            raise RuntimeError(
                f"BMI270 chip id mismatch on {self.dev_path} addr 0x{addr:02x}: "
                f"got 0x{chip_id:02x}, expected 0x{self.EXPECTED_CHIP_ID:02x}"
            )
        if init_sensor:
            self.initialize(config_blob)

    def close(self) -> None:
        os.close(self.fd)

    def write_reg(self, reg: int, value: int) -> None:
        os.write(self.fd, bytes([reg & 0xFF, value & 0xFF]))

    def write_block(self, reg: int, data: bytes) -> None:
        os.write(self.fd, bytes([reg & 0xFF]) + data)

    def read_reg(self, reg: int) -> int:
        return self.read_block(reg, 1)[0]

    def read_block(self, reg: int, length: int) -> bytes:
        os.write(self.fd, bytes([reg & 0xFF]))
        data = os.read(self.fd, length)
        if len(data) != length:
            raise RuntimeError(f"Short I2C read: wanted {length}, got {len(data)}")
        return data

    def initialize(self, config_blob: Any = "auto") -> None:
        blob = load_bmi270_config_blob(config_blob)
        if len(blob) < 1024:
            raise RuntimeError(f"BMI270 config blob is too small: {len(blob)} bytes")

        self.write_reg(self.PWR_CONF, 0x00)
        time.sleep(0.002)
        self.write_reg(self.INIT_CTRL, 0x00)
        time.sleep(0.001)

        # BMI270 loads its feature firmware through INIT_DATA. Set the internal
        # load address for each chunk to avoid adapter transfer-size limits.
        chunk_size = 32
        for offset in range(0, len(blob), chunk_size):
            init_addr = offset // 2
            self.write_reg(self.INIT_ADDR_0, init_addr & 0x0F)
            self.write_reg(self.INIT_ADDR_1, (init_addr >> 4) & 0xFF)
            self.write_block(self.INIT_DATA, blob[offset : offset + chunk_size])
            time.sleep(0.0005)

        self.write_reg(self.INIT_CTRL, 0x01)
        time.sleep(0.04)
        status = self.read_reg(self.INTERNAL_STATUS)
        if (status & 0x01) == 0:
            raise RuntimeError(f"BMI270 init failed, INTERNAL_STATUS=0x{status:02x}")

        # Match the STM32 example: accel +-16 g, gyro +-2000 dps, 200 Hz.
        self.write_reg(self.PWR_CTRL, 0x0E)
        time.sleep(0.05)
        self.write_reg(self.NV_CONF, 0x00)
        self.write_reg(self.IF_CONF, 0x00)
        self.write_reg(self.GYR_RANGE, self.GYR_RANGE_2000_DPS)
        self.write_reg(self.GYR_CONF, self.ACC_GYRO_RATE_200HZ_WITH_FILTER)
        self.write_reg(self.ACC_RANGE, self.ACC_RANGE_16G)
        self.write_reg(self.ACC_CONF, self.ACC_GYRO_RATE_200HZ_WITH_FILTER)
        time.sleep(0.01)

    @staticmethod
    def _int16_le(data: bytes, offset: int) -> int:
        return int.from_bytes(data[offset : offset + 2], "little", signed=True)

    def read(self) -> ImuSample:
        data = self.read_block(self.ACC_X_LSB, 12)
        acc_x = self._int16_le(data, 0)
        acc_y = self._int16_le(data, 2)
        acc_z = self._int16_le(data, 4)
        gyro_x = self._int16_le(data, 6)
        gyro_y = self._int16_le(data, 8)
        gyro_z = self._int16_le(data, 10)
        return ImuSample(
            time.monotonic(),
            acc_x * self.ACC_SCALE,
            acc_y * self.ACC_SCALE,
            acc_z * self.ACC_SCALE,
            gyro_x * self.GYRO_SCALE,
            gyro_y * self.GYRO_SCALE,
            gyro_z * self.GYRO_SCALE,
        )


class SimulatedImu:
    """Sensor source used for PC testing without hardware."""

    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.last_t = self.t0
        self.last_roll = 0.0
        self.last_pitch = 0.0
        self.last_yaw = 0.0

    def read(self) -> ImuSample:
        now = time.monotonic()
        t = now - self.t0
        dt = max(now - self.last_t, 0.001)
        phase = t % 24.0
        roll = math.radians(6.0 * math.sin(0.8 * t))
        pitch = math.radians(8.0 * math.sin(0.5 * t))
        yaw = math.radians(15.0 * math.sin(0.2 * t))
        if 8.0 < phase < 12.0:
            pitch = math.radians(48.0)
        if 17.0 < phase < 17.25:
            shock = 2.5 * G
        else:
            shock = 0.0

        gx = (roll - self.last_roll) / dt
        gy = (pitch - self.last_pitch) / dt
        gz = (yaw - self.last_yaw) / dt
        ax, ay, az = gravity_body(roll, pitch)
        ax += 0.25 * math.sin(2.2 * t) + shock
        ay += 0.12 * math.sin(1.7 * t)
        az += 0.20 * math.sin(2.0 * t)

        self.last_t = now
        self.last_roll = roll
        self.last_pitch = pitch
        self.last_yaw = yaw
        return ImuSample(now, ax, ay, az, gx, gy, gz)


def gravity_body(roll: float, pitch: float) -> Tuple[float, float, float]:
    return (
        -math.sin(pitch) * G,
        math.sin(roll) * math.cos(pitch) * G,
        math.cos(roll) * math.cos(pitch) * G,
    )


def rotate_body_to_world(
    v: Tuple[float, float, float], roll: float, pitch: float, yaw: float
) -> Tuple[float, float, float]:
    cr = math.cos(roll)
    sr = math.sin(roll)
    cp = math.cos(pitch)
    sp = math.sin(pitch)
    cy = math.cos(yaw)
    sy = math.sin(yaw)

    x1 = v[0]
    y1 = cr * v[1] - sr * v[2]
    z1 = sr * v[1] + cr * v[2]
    x2 = cp * x1 + sp * z1
    y2 = y1
    z2 = -sp * x1 + cp * z1
    return (cy * x2 - sy * y2, sy * x2 + cy * y2, z2)


class MotionEstimator:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.roll = 0.0
        self.pitch = 0.0
        self.yaw = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.vz = 0.0
        self.last_t: Optional[float] = None
        self.stationary_time = 0.0
        self.initialized = False

    def reset_velocity(self) -> None:
        self.vx = self.vy = self.vz = 0.0
        self.stationary_time = 0.0

    def reset_yaw(self) -> None:
        self.yaw = 0.0

    def update(self, sample: ImuSample) -> Dict[str, Any]:
        accel = (sample.ax, sample.ay, sample.az)
        gyro = (sample.gx, sample.gy, sample.gz)
        acc_norm = max(norm3(accel), 1e-6)
        gyro_norm = norm3(gyro)

        roll_acc = math.atan2(sample.ay, sample.az)
        pitch_acc = math.atan2(-sample.ax, math.sqrt(sample.ay * sample.ay + sample.az * sample.az))

        if not self.initialized:
            self.roll = roll_acc
            self.pitch = pitch_acc
            self.yaw = 0.0
            self.last_t = sample.t
            self.initialized = True

        assert self.last_t is not None
        dt = max(min(sample.t - self.last_t, 0.2), 0.001)
        self.last_t = sample.t

        cr = math.cos(self.roll)
        sr = math.sin(self.roll)
        cp = max(abs(math.cos(self.pitch)), 1e-3)
        tp = math.tan(self.pitch)

        roll_gyro = self.roll + (sample.gx + sr * tp * sample.gy + cr * tp * sample.gz) * dt
        pitch_gyro = self.pitch + (cr * sample.gy - sr * sample.gz) * dt
        yaw_gyro = self.yaw + (sr / cp * sample.gy + cr / cp * sample.gz) * dt

        alpha = float(self.cfg["filter"]["gyro_alpha"])
        if 0.55 * G < acc_norm < 1.45 * G:
            self.roll = alpha * roll_gyro + (1.0 - alpha) * roll_acc
            self.pitch = alpha * pitch_gyro + (1.0 - alpha) * pitch_acc
        else:
            self.roll = roll_gyro
            self.pitch = pitch_gyro
        self.yaw = wrap_pi(yaw_gyro)

        gb = gravity_body(self.roll, self.pitch)
        lin_body = (sample.ax - gb[0], sample.ay - gb[1], sample.az - gb[2])
        lin_world = rotate_body_to_world(lin_body, self.roll, self.pitch, self.yaw)
        lin_norm = norm3(lin_world)

        deadband = float(self.cfg["filter"]["linear_acc_deadband_mps2"])
        if lin_norm < deadband:
            lin_world = (0.0, 0.0, 0.0)
            lin_norm = 0.0

        accel_tol = float(self.cfg["filter"]["stationary_accel_tolerance_g"]) * G
        gyro_limit = math.radians(float(self.cfg["filter"]["stationary_gyro_dps"]))
        stationary = abs(acc_norm - G) < accel_tol and gyro_norm < gyro_limit and lin_norm < deadband * 1.5
        if stationary:
            self.stationary_time += dt
        else:
            self.stationary_time = 0.0

        hold = float(self.cfg["filter"]["stationary_hold_s"])
        damping = float(self.cfg["filter"]["velocity_damping_per_s"])
        if self.stationary_time >= hold:
            self.vx = self.vy = self.vz = 0.0
        else:
            self.vx = (self.vx + lin_world[0] * dt) * math.exp(-damping * dt)
            self.vy = (self.vy + lin_world[1] * dt) * math.exp(-damping * dt)
            self.vz = (self.vz + lin_world[2] * dt) * math.exp(-damping * dt)

        speed = norm3((self.vx, self.vy, self.vz))
        max_speed = float(self.cfg["filter"]["max_speed_mps"])
        if speed > max_speed:
            scale = max_speed / speed
            self.vx *= scale
            self.vy *= scale
            self.vz *= scale
            speed = max_speed

        return {
            "t_mono": sample.t,
            "dt": dt,
            "roll_deg": math.degrees(self.roll),
            "pitch_deg": math.degrees(self.pitch),
            "yaw_deg": math.degrees(self.yaw),
            "ax_g": sample.ax / G,
            "ay_g": sample.ay / G,
            "az_g": sample.az / G,
            "gx_dps": math.degrees(sample.gx),
            "gy_dps": math.degrees(sample.gy),
            "gz_dps": math.degrees(sample.gz),
            "accel_g": acc_norm / G,
            "gyro_dps": math.degrees(gyro_norm),
            "linear_acc_mps2": lin_norm,
            "vx_mps": self.vx,
            "vy_mps": self.vy,
            "vz_mps": self.vz,
            "speed_mps": speed,
            "stationary": stationary,
            "speed_quality": "rough_imu_integration",
        }


class AnomalyDetector:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.hold_start: Dict[str, float] = {}
        self.last_emit: Dict[str, float] = {}

    def update(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        th = self.cfg["thresholds"]
        checks = []

        if bool(th.get("hunch_enabled", True)):
            accel_g = float(state.get("accel_g", 0.0))
            gyro_dps = float(state.get("gyro_dps", 0.0))
            hunch_active = (
                state["pitch_deg"] < float(th.get("hunch_pitch_deg", -15.5))
                and gyro_dps <= float(th.get("hunch_max_gyro_dps", 30.0))
                and accel_g >= float(th.get("hunch_accel_min_g", 0.75))
                and accel_g <= float(th.get("hunch_accel_max_g", 1.25))
            )
            checks.append(
                (
                    "HUNCH",
                    hunch_active,
                    float(th.get("hunch_hold_s", 3.0)),
                    2,
                    "sustained hunched backpack posture",
                )
            )

        if bool(th.get("tilt_enabled", True)):
            checks.extend(
                [
                    (
                        "TILT_FORWARD",
                        state["pitch_deg"] > float(th["pitch_forward_deg"]),
                        float(th["tilt_hold_s"]),
                        2,
                        "pitch too far forward",
                    ),
                    (
                        "TILT_BACKWARD",
                        state["pitch_deg"] < float(th["pitch_backward_deg"]),
                        float(th["tilt_hold_s"]),
                        2,
                        "pitch too far backward",
                    ),
                    (
                        "ROLL_LEFT",
                        state["roll_deg"] < float(th["roll_left_deg"]),
                        float(th["tilt_hold_s"]),
                        2,
                        "roll too far left",
                    ),
                    (
                        "ROLL_RIGHT",
                        state["roll_deg"] > float(th["roll_right_deg"]),
                        float(th["tilt_hold_s"]),
                        2,
                        "roll too far right",
                    ),
                ]
            )

        checks.extend(
            [
                (
                    "IMPACT",
                    state["accel_g"] > float(th["impact_g"]),
                    0.0,
                    3,
                    "large impact acceleration",
                ),
                (
                    "FREEFALL",
                    state["accel_g"] < float(th["freefall_g"]),
                    float(th["freefall_hold_s"]),
                    3,
                    "low-g/freefall detected",
                ),
                (
                    "SPEED_WARN",
                    state["speed_mps"] > float(th["speed_warn_mps"]),
                    float(th["speed_hold_s"]),
                    1,
                    "estimated speed above threshold",
                ),
            ]
        )

        alerts: List[Dict[str, Any]] = []
        for code, active, hold_s, level, message in checks:
            alert = self._check(code, active, hold_s, level, message, state)
            if alert is not None:
                alerts.append(alert)
        return alerts

    def _check(
        self,
        code: str,
        active: bool,
        hold_s: float,
        level: int,
        message: str,
        state: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        now = state["t_mono"]
        if not active:
            self.hold_start.pop(code, None)
            return None

        start = self.hold_start.setdefault(code, now)
        if now - start < hold_s:
            return None

        cooldown = float(self.cfg["thresholds"]["alert_cooldown_s"])
        last = self.last_emit.get(code, -1e9)
        if now - last < cooldown:
            return None

        self.last_emit[code] = now
        return {
            "code": code,
            "level": level,
            "message": message,
            "pitch_deg": state["pitch_deg"],
            "roll_deg": state["roll_deg"],
            "speed_mps": state["speed_mps"],
            "accel_g": state["accel_g"],
            "wall_time": time.time(),
        }


class AlertOutput:
    def __init__(self, cfg: Dict[str, Any]):
        out = cfg["output"]
        self.alert_file = str(out.get("alert_file") or "")
        self.active_value = str(out.get("alert_active_value", "1"))
        self.inactive_value = str(out.get("alert_inactive_value", "0"))
        self.pulse_s = float(out.get("alert_pulse_ms", 300)) / 1000.0
        command = out.get("alert_command", [])
        if isinstance(command, str):
            self.command = shlex.split(command)
        else:
            self.command = list(command)

    def emit(self, alert: Dict[str, Any]) -> None:
        print(
            "ALERT,{code},level={level},pitch={pitch:.1f},roll={roll:.1f},"
            "speed={speed:.2f},accel_g={accel:.2f}".format(
                code=alert["code"],
                level=alert["level"],
                pitch=alert["pitch_deg"],
                roll=alert["roll_deg"],
                speed=alert["speed_mps"],
                accel=alert["accel_g"],
            ),
            flush=True,
        )
        if self.alert_file:
            threading.Thread(target=self._pulse_file, daemon=True).start()
        if self.command:
            self._run_command(alert)

    def _pulse_file(self) -> None:
        try:
            Path(self.alert_file).write_text(self.active_value, encoding="ascii")
            time.sleep(self.pulse_s)
            Path(self.alert_file).write_text(self.inactive_value, encoding="ascii")
        except OSError as exc:
            print(f"WARN alert_file failed: {exc}", file=sys.stderr, flush=True)

    def _run_command(self, alert: Dict[str, Any]) -> None:
        env = os.environ.copy()
        env["BMI270_ALERT_CODE"] = str(alert["code"])
        env["BMI270_ALERT_LEVEL"] = str(alert["level"])
        try:
            subprocess.Popen(self.command, env=env)
        except OSError as exc:
            print(f"WARN alert_command failed: {exc}", file=sys.stderr, flush=True)



class CalibrationRecorder:
    CSV_FIELDS = [
        "wall_time",
        "elapsed_s",
        "mode",
        "roll_deg",
        "pitch_deg",
        "yaw_deg",
        "raw_roll_deg",
        "raw_pitch_deg",
        "raw_yaw_deg",
        "speed_mps",
        "accel_g",
        "gyro_dps",
        "stationary",
        "ax_g",
        "ay_g",
        "az_g",
        "gx_dps",
        "gy_dps",
        "gz_dps",
        "alerts",
    ]

    def __init__(self, cfg: Dict[str, Any]):
        cal_cfg = cfg.get("calibration", {})
        self.data_dir = Path(str(cal_cfg.get("data_dir", "/root/bmi270_calibration")))
        self.modes = dict(DEFAULT_CONFIG["calibration"]["modes"])
        user_modes = cal_cfg.get("modes", {})
        if isinstance(user_modes, dict):
            for key, value in user_modes.items():
                if isinstance(value, dict):
                    merged = dict(self.modes.get(key, {}))
                    merged.update(value)
                    self.modes[key] = merged
        self.file: Optional[Any] = None
        self.writer: Optional[csv.DictWriter[Any]] = None
        self.path: Optional[Path] = None
        self.mode_key = ""
        self.mode_label = ""
        self.duration_s: Optional[float] = None
        self.started_mono = 0.0
        self.rows = 0
        self.last_completed: Optional[Dict[str, Any]] = None

    @property
    def active(self) -> bool:
        return self.file is not None and self.writer is not None and self.path is not None

    def available_modes(self) -> List[str]:
        return list(self.modes.keys())

    def start(self, mode_key: str, duration_s: Optional[float] = None) -> Dict[str, Any]:
        if self.active:
            raise RuntimeError(f"already recording {self.mode_key}")
        if mode_key not in self.modes:
            raise RuntimeError("unknown mode " + mode_key)
        mode = self.modes[mode_key]
        prefix = str(mode.get("prefix") or mode_key)
        default_duration = float(mode.get("duration_s") or 0.0)
        duration = default_duration if duration_s is None else float(duration_s)
        if duration <= 0.0:
            duration = 0.0

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self._next_path(prefix)
        self.file = self.path.open("w", encoding="utf-8", newline="", buffering=1)
        self.writer = csv.DictWriter(self.file, fieldnames=self.CSV_FIELDS)
        self.writer.writeheader()
        self.mode_key = mode_key
        self.mode_label = str(mode.get("label") or mode_key)
        self.duration_s = duration if duration > 0.0 else None
        self.started_mono = time.monotonic()
        self.rows = 0
        self.last_completed = None
        return self.status()

    def stop(self, reason: str = "manual") -> Dict[str, Any]:
        if not self.active:
            raise RuntimeError("not recording")
        assert self.file is not None and self.path is not None
        elapsed = max(time.monotonic() - self.started_mono, 0.0)
        summary = {
            "active": False,
            "mode": self.mode_key,
            "label": self.mode_label,
            "path": str(self.path),
            "filename": self.path.name,
            "rows": self.rows,
            "elapsed_s": elapsed,
            "duration_s": self.duration_s,
            "reason": reason,
        }
        try:
            self.file.flush()
            os.fsync(self.file.fileno())
        finally:
            self.file.close()
            self.file = None
            self.writer = None
            self.path = None
            self.mode_key = ""
            self.mode_label = ""
            self.duration_s = None
            self.started_mono = 0.0
            self.rows = 0
        self.last_completed = summary
        return summary

    def close_if_active(self, reason: str = "shutdown") -> Optional[Dict[str, Any]]:
        if not self.active:
            return None
        return self.stop(reason)

    def write_sample(self, state: Dict[str, Any], alerts: List[Dict[str, Any]]) -> None:
        if not self.active:
            return
        assert self.writer is not None
        alert_codes = [str(alert.get("code", "")) for alert in alerts if alert.get("code")]
        row = {
            "wall_time": f"{time.time():.3f}",
            "elapsed_s": f"{max(time.monotonic() - self.started_mono, 0.0):.3f}",
            "mode": self.mode_key,
            "roll_deg": self._fmt(state.get("roll_deg")),
            "pitch_deg": self._fmt(state.get("pitch_deg")),
            "yaw_deg": self._fmt(state.get("yaw_deg")),
            "raw_roll_deg": self._fmt(state.get("raw_roll_deg", state.get("roll_deg"))),
            "raw_pitch_deg": self._fmt(state.get("raw_pitch_deg", state.get("pitch_deg"))),
            "raw_yaw_deg": self._fmt(state.get("raw_yaw_deg", state.get("yaw_deg"))),
            "speed_mps": self._fmt(state.get("speed_mps")),
            "accel_g": self._fmt(state.get("accel_g")),
            "gyro_dps": self._fmt(state.get("gyro_dps")),
            "stationary": "1" if state.get("stationary") else "0",
            "ax_g": self._fmt(state.get("ax_g")),
            "ay_g": self._fmt(state.get("ay_g")),
            "az_g": self._fmt(state.get("az_g")),
            "gx_dps": self._fmt(state.get("gx_dps")),
            "gy_dps": self._fmt(state.get("gy_dps")),
            "gz_dps": self._fmt(state.get("gz_dps")),
            "alerts": ";".join(alert_codes),
        }
        self.writer.writerow(row)
        self.rows += 1

    def tick(self) -> Optional[Dict[str, Any]]:
        if not self.active or self.duration_s is None:
            return None
        if time.monotonic() - self.started_mono >= self.duration_s:
            return self.stop("duration")
        return None

    def status(self) -> Dict[str, Any]:
        if not self.active:
            return {"active": False, "last_completed": self.last_completed}
        assert self.path is not None
        elapsed = max(time.monotonic() - self.started_mono, 0.0)
        return {
            "active": True,
            "mode": self.mode_key,
            "label": self.mode_label,
            "path": str(self.path),
            "filename": self.path.name,
            "rows": self.rows,
            "elapsed_s": elapsed,
            "duration_s": self.duration_s,
        }

    def compact_status(self) -> Dict[str, Any]:
        if self.active:
            status = self.status()
            return {
                "a": 1,
                "m": status["mode"],
                "e": round(float(status["elapsed_s"]), 1),
                "n": int(status["rows"]),
                "d": round(float(status.get("duration_s") or 0.0), 1),
                "f": status["filename"],
            }
        if self.last_completed:
            return {
                "a": 0,
                "m": self.last_completed["mode"],
                "e": round(float(self.last_completed["elapsed_s"]), 1),
                "n": int(self.last_completed["rows"]),
                "d": round(float(self.last_completed.get("duration_s") or 0.0), 1),
                "f": self.last_completed["filename"],
                "done": 1,
            }
        return {}

    def _next_path(self, prefix: str) -> Path:
        safe_prefix = re.sub(r"[^A-Za-z0-9_\-]+", "_", prefix).strip("_") or "capture"
        for index in range(1, 1000):
            path = self.data_dir / f"{safe_prefix}_{index:02d}.csv"
            if not path.exists():
                return path
        return self.data_dir / f"{safe_prefix}_{int(time.time())}.csv"

    @staticmethod
    def _fmt(value: Any) -> str:
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return ""


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
        except Exception as exc:  # pragma: no cover - depends on target Linux.
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
            PATH_BASE = "/org/bluez/example/service"

            def __init__(self, system_bus: Any, index: int, uuid: str, primary: bool):
                self.path = self.PATH_BASE + str(index)
                self.bus = system_bus
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
                self.bus = system_bus
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
                super().__init__(
                    system_bus,
                    index,
                    outer.NUS_TX_UUID,
                    ["notify"],
                    service,
                )
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
            PATH_BASE = "/org/bluez/example/advertisement"

            def __init__(self, system_bus: Any, index: int, local_name: str):
                self.path = self.PATH_BASE + str(index)
                self.bus = system_bus
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
        managed = object_manager.GetManagedObjects()
        adapter_path = None
        for path, interfaces in managed.items():
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
                print(msg, flush=True)

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


def compact_frame(
    state: Dict[str, Any],
    alerts: List[Dict[str, Any]],
    recorder: Optional[CalibrationRecorder] = None,
) -> str:
    frame = {
        "t": round(time.time(), 3),
        "r": round(state["roll_deg"], 1),
        "p": round(state["pitch_deg"], 1),
        "y": round(state["yaw_deg"], 1),
        "s": round(state["speed_mps"], 2),
        "ag": round(state["accel_g"], 2),
        "gyr": round(state["gyro_dps"], 1),
        "st": 1 if state["stationary"] else 0,
        "a": [round(state["ax_g"], 2), round(state["ay_g"], 2), round(state["az_g"], 2)],
        "w": [
            round(state["gx_dps"], 1),
            round(state["gy_dps"], 1),
            round(state["gz_dps"], 1),
        ],
    }
    if state.get("posture_corrected"):
        frame["raw"] = [round(float(state.get("raw_roll_deg", 0.0)), 1), round(float(state.get("raw_pitch_deg", 0.0)), 1)]
    if alerts:
        frame["al"] = [a["code"] for a in alerts]
    if recorder is not None:
        rec_status = recorder.compact_status()
        if rec_status:
            frame["rec"] = rec_status
    return json.dumps(frame, separators=(",", ":"), ensure_ascii=True)



def format_calibration_start_response(status: Dict[str, Any]) -> str:
    return (
        "OK cal_start mode={mode} file={filename} duration={duration:.1f}"
        .format(
            mode=status.get("mode", ""),
            filename=status.get("filename", ""),
            duration=float(status.get("duration_s") or 0.0),
        )
    )


def format_calibration_stop_response(status: Dict[str, Any]) -> str:
    return (
        "OK cal_stop mode={mode} file={filename} rows={rows} elapsed={elapsed:.1f} reason={reason}"
        .format(
            mode=status.get("mode", ""),
            filename=status.get("filename", ""),
            rows=int(status.get("rows") or 0),
            elapsed=float(status.get("elapsed_s") or 0.0),
            reason=status.get("reason", ""),
        )
    )


def format_calibration_status_response(recorder: CalibrationRecorder) -> str:
    status = recorder.status()
    if status.get("active"):
        return (
            "OK cal_status active=1 mode={mode} file={filename} rows={rows} "
            "elapsed={elapsed:.1f} duration={duration:.1f}"
            .format(
                mode=status.get("mode", ""),
                filename=status.get("filename", ""),
                rows=int(status.get("rows") or 0),
                elapsed=float(status.get("elapsed_s") or 0.0),
                duration=float(status.get("duration_s") or 0.0),
            )
        )
    last = status.get("last_completed")
    if isinstance(last, dict):
        return "OK cal_status active=0 last={filename} rows={rows}".format(
            filename=last.get("filename", ""),
            rows=int(last.get("rows") or 0),
        )
    return "OK cal_status active=0"


def process_command(
    text: str,
    cfg: Dict[str, Any],
    estimator: MotionEstimator,
    ble: Optional[BleNusServer],
    recorder: Optional[CalibrationRecorder] = None,
) -> str:
    cmd = text.strip()
    try:
        tokens = shlex.split(cmd)
    except ValueError as exc:
        tokens = []
        response = f"ERR parse {exc}"
    else:
        response = ""

    op = tokens[0].upper() if tokens else ""
    upper = cmd.upper()
    if response:
        pass
    elif not cmd:
        response = "ERR empty command"
    elif upper in ("ZERO", "RESET"):
        estimator.reset_velocity()
        estimator.reset_yaw()
        response = "OK zero"
    elif upper in ("ZERO_V", "RESET_V"):
        estimator.reset_velocity()
        response = "OK zero velocity"
    elif upper == "STATUS":
        response = json.dumps(
            {"thresholds": cfg["thresholds"], "posture": cfg.get("posture", {})},
            separators=(",", ":"),
            ensure_ascii=True,
        )
    elif op in ("CAL_START", "CS"):
        if recorder is None:
            response = "ERR calibration unavailable"
        elif len(tokens) < 2:
            response = "ERR use CAL_START <mode> [duration=15] or CS <mode> 15"
        else:
            duration_s: Optional[float] = None
            for token in tokens[2:]:
                if token.startswith("duration="):
                    value_text = token.split("=", 1)[1]
                else:
                    value_text = token
                try:
                    duration_s = float(value_text)
                except ValueError:
                    response = "ERR invalid duration"
                    break
            if not response:
                try:
                    response = format_calibration_start_response(recorder.start(tokens[1], duration_s))
                except Exception as exc:
                    response = f"ERR cal_start {exc}"
    elif op in ("CAL_STOP", "CE"):
        if recorder is None:
            response = "ERR calibration unavailable"
        else:
            try:
                response = format_calibration_stop_response(recorder.stop("manual"))
            except Exception as exc:
                response = f"ERR cal_stop {exc}"
    elif op in ("CAL_STATUS", "C?"):
        if recorder is None:
            response = "ERR calibration unavailable"
        else:
            response = format_calibration_status_response(recorder)
    elif op in ("CAL_MODES", "CM"):
        if recorder is None:
            response = "ERR calibration unavailable"
        else:
            parts = []
            for key in recorder.available_modes():
                mode = recorder.modes[key]
                parts.append(f"{key}:{float(mode.get('duration_s') or 0.0):.0f}")
            response = "OK cal_modes " + ",".join(parts)
    elif upper.startswith("SET "):
        payload = cmd[4:].strip()
        if "=" not in payload:
            response = "ERR use SET key=value"
        else:
            key, value_text = payload.split("=", 1)
            key = key.strip()
            try:
                value = float(value_text.strip())
            except ValueError:
                response = "ERR value must be numeric"
            else:
                updated = False
                for section in ("thresholds", "filter", "posture"):
                    if key in cfg[section]:
                        cfg[section][key] = value
                        updated = True
                        response = f"OK {key}={value}"
                        break
                if not updated:
                    response = f"ERR unknown key {key}"
    elif upper == "HELP":
        response = (
            "CMD: STATUS | ZERO | ZERO_V | CM | CS <mode> 15 | CE | C? | "
            "CAL_START <mode> duration=15 | CAL_STOP | SET hunch_pitch_deg=-15.5"
        )
    else:
        response = "ERR unknown command; send HELP"

    print(f"CMD,{cmd},{response}", flush=True)
    if ble is not None:
        ble.send_line(response)
    return response


def print_iio_devices() -> None:
    devices = IioImu.list_devices()
    if not devices:
        print("No /sys/bus/iio/devices/iio:device* found")
        return
    for item in devices:
        print(f"{item['path']} name={item['name']} channels={item['channels']}")


def probe_bmi270_i2c(bus: Optional[int] = None) -> None:
    if fcntl is None:
        print("I2C probe needs Linux fcntl/i2c-dev")
        return
    buses = [bus] if bus is not None else find_i2c_buses()
    if not buses:
        print("No /dev/i2c-* devices found")
        return
    found = False
    for bus_id in buses:
        for addr in (0x68, 0x69):
            dev = f"/dev/i2c-{bus_id}"
            try:
                fd = os.open(dev, os.O_RDWR)
                try:
                    fcntl.ioctl(fd, UserspaceI2cBmi270.I2C_SLAVE, addr)
                    os.write(fd, bytes([UserspaceI2cBmi270.CHIP_ID]))
                    chip = os.read(fd, 1)
                finally:
                    os.close(fd)
                if chip:
                    mark = "BMI270" if chip[0] == UserspaceI2cBmi270.EXPECTED_CHIP_ID else "unknown"
                    print(f"{dev} addr=0x{addr:02x} chip_id=0x{chip[0]:02x} {mark}")
                    if chip[0] == UserspaceI2cBmi270.EXPECTED_CHIP_ID:
                        found = True
            except OSError:
                continue
    if not found:
        print("No BMI270 chip id 0x24 found at 0x68/0x69")


def make_imu_source(cfg: Dict[str, Any], args: argparse.Namespace) -> Any:
    if args.simulate:
        print("Using simulated IMU source", flush=True)
        return SimulatedImu()

    dev_cfg = cfg["device"]
    backend = str(args.backend or dev_cfg.get("backend", "auto")).lower()

    if backend in ("auto", "iio"):
        try:
            iio_path = str(dev_cfg.get("iio_path", "auto"))
            if iio_path == "auto":
                iio_path = IioImu.auto_find()
            print(f"Using IIO device {iio_path}", flush=True)
            return IioImu(iio_path)
        except Exception as exc:
            if backend == "iio":
                raise
            print(f"WARN IIO backend unavailable: {exc}", file=sys.stderr, flush=True)

    if backend in ("auto", "i2c"):
        bus = args.i2c_bus if args.i2c_bus is not None else int(dev_cfg.get("i2c_bus", 0))
        addr = parse_int(args.i2c_addr if args.i2c_addr else dev_cfg.get("i2c_addr", "0x68"))
        config_blob = dev_cfg.get("config_blob", "auto")
        init_sensor = bool(dev_cfg.get("init_sensor", True))
        print(
            f"Using userspace I2C {bus=} addr=0x{addr:02x} init={init_sensor}",
            flush=True,
        )
        return UserspaceI2cBmi270(bus, addr, config_blob, init_sensor)

    raise RuntimeError(f"Unknown device backend: {backend}")


def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    if args.no_ble:
        cfg["output"]["ble_enabled"] = False
    if args.ble:
        cfg["output"]["ble_enabled"] = True
    if args.alert_file:
        cfg["output"]["alert_file"] = args.alert_file

    imu: Any = make_imu_source(cfg, args)

    estimator = MotionEstimator(cfg)
    detector = AnomalyDetector(cfg)
    alert_output = AlertOutput(cfg)
    calibration_recorder = CalibrationRecorder(cfg)
    fall_bridge = (
        FallEventBridge(float(cfg["device"]["sample_hz"]))
        if bool(cfg.get("fall_detection", {}).get("enabled", True))
        else None
    )
    commands: "queue.Queue[str]" = queue.Queue()
    if args.command_stdin:
        def _command_reader() -> None:
            for line in sys.stdin:
                text = line.strip()
                if text:
                    commands.put(text)

        threading.Thread(target=_command_reader, daemon=True).start()

    ble: Optional[BleNusServer] = None
    if bool(cfg["output"]["ble_enabled"]):
        ble = BleNusServer(str(cfg["output"]["ble_name"]), commands.put)
        try:
            ble.start()
            print(f"BLE enabled as {cfg['output']['ble_name']}", flush=True)
        except Exception as exc:
            print(f"WARN BLE disabled: {exc}", file=sys.stderr, flush=True)
            ble = None

    stop_event = threading.Event()

    def _stop(signum: int, frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    sample_hz = max(float(cfg["device"]["sample_hz"]), 1.0)
    period = 1.0 / sample_hz
    console_hz = max(float(cfg["output"]["console_hz"]), 0.1)
    ble_hz = max(float(cfg["output"]["ble_hz"]), 0.1)
    next_console = time.monotonic()
    next_ble = time.monotonic()
    next_sample = time.monotonic()

    while not stop_event.is_set():
        now = time.monotonic()
        if now < next_sample:
            time.sleep(min(next_sample - now, 0.02))
            continue
        next_sample += period
        if next_sample < now - period:
            next_sample = now + period

        try:
            sample = imu.read()
            state = estimator.update(sample)
            state = apply_posture_correction(state, cfg)
            alerts = detector.update(state)
            fall_events = fall_bridge.update_jsonl(sample) if fall_bridge is not None else []
        except Exception as exc:
            print(f"ERR read/process failed: {exc}", file=sys.stderr, flush=True)
            time.sleep(0.2)
            continue

        while True:
            try:
                process_command(commands.get_nowait(), cfg, estimator, ble, calibration_recorder)
            except queue.Empty:
                break

        for alert in alerts:
            alert_output.emit(alert)
        for fall_event in fall_events:
            print(fall_event, flush=True)

        calibration_recorder.write_sample(state, alerts)
        completed_capture = calibration_recorder.tick()
        if completed_capture is not None:
            response = format_calibration_stop_response(completed_capture)
            print(f"CMD,AUTO_CAL_STOP,{response}", flush=True)
            if ble is not None:
                ble.send_line(response)

        frame = compact_frame(state, alerts, calibration_recorder)
        now = time.monotonic()
        if now >= next_console:
            print(frame, flush=True)
            next_console = now + 1.0 / console_hz
        if ble is not None and now >= next_ble:
            ble.send_line(frame)
            next_ble = now + 1.0 / ble_hz

    calibration_recorder.close_if_active("shutdown")
    if ble is not None:
        ble.stop()
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BMI270 backpack posture monitor")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to JSON config. Defaults are built in.",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Use generated IMU data; useful for PC tests.",
    )
    parser.add_argument(
        "--list-iio",
        action="store_true",
        help="List IIO devices and exit.",
    )
    parser.add_argument(
        "--probe-i2c",
        action="store_true",
        help="Probe /dev/i2c-* for BMI270 chip id at 0x68/0x69 and exit.",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "iio", "i2c"),
        default=None,
        help="Sensor backend. auto tries IIO first, then userspace I2C.",
    )
    parser.add_argument(
        "--i2c-bus",
        type=int,
        default=None,
        help="I2C bus number for userspace I2C, for example 0 for /dev/i2c-0.",
    )
    parser.add_argument(
        "--i2c-addr",
        default="",
        help="BMI270 I2C address, usually 0x68 or 0x69.",
    )
    parser.add_argument("--ble", action="store_true", help="Force BLE on.")
    parser.add_argument("--no-ble", action="store_true", help="Force BLE off.")
    parser.add_argument("--command-stdin", action="store_true", help="Read STATUS/ZERO/SET commands from stdin for the unified board service.")
    parser.add_argument(
        "--alert-file",
        default="",
        help="Override output.alert_file, for example /tmp/bmi270_alert.",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.list_iio:
        print_iio_devices()
        return 0
    if args.probe_i2c:
        probe_bmi270_i2c(args.i2c_bus)
        return 0
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
