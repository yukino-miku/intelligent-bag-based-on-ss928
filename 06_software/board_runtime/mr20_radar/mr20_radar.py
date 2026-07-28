"""MR20 Ethernet radar decoding, risk evaluation, and controller workers."""

from __future__ import annotations

import json
import queue
import socket
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

CONTROLLER_DIR = Path(__file__).resolve().parents[1] / "smartbag_alert_controller"
if str(CONTROLLER_DIR) not in sys.path:
    sys.path.insert(0, str(CONTROLLER_DIR))

from alert_core import AlertEvent, normalize_side

FRAME_HEAD = b"\xAA\xAA"
FRAME_TAIL = b"\x55\x55"
FRAME_SIZE = 14
OBJECT_STATUS_ID = b"\x0A\x06"  # CAN 0x60A, little endian.
OBJECT_GENERAL_ID = b"\x0B\x06"  # CAN 0x60B, little endian.


class MR20FrameError(ValueError):
    pass


@dataclass(frozen=True)
class MR20ObjectListStatus:
    target_count: int
    measurement_count: int


@dataclass(frozen=True)
class MR20Target:
    target_id: int
    longitudinal_distance_m: float
    lateral_distance_m: float
    longitudinal_velocity_mps: float
    lateral_velocity_mps: float
    status: str
    radar_name: str = ""
    side: str = ""
    measurement_count: int = 0
    timestamp: float = 0.0


@dataclass(frozen=True)
class RadarScan:
    radar_name: str
    side: str
    measurement_count: int
    captured_mono_s: float
    targets: tuple[MR20Target, ...]


@dataclass(frozen=True)
class RadarConfig:
    name: str
    side: str
    bind_host: str
    port: int
    radar_ip: str
    lateral_min_m: float
    lateral_max_m: float
    longitudinal_min_m: float
    longitudinal_max_m: float
    approaching_velocity_sign: int
    min_consecutive_frames: int
    log_path: str
    mount_x_m: float = 0.0
    mount_z_m: float = 0.0
    mount_yaw_deg: float = 0.0
    invert_lateral: bool = False
    invert_longitudinal: bool = False
    invert_lateral_velocity: bool = False
    invert_longitudinal_velocity: bool = False


@dataclass(frozen=True)
class RiskConfig:
    levels: tuple[tuple[int, float, float, float], ...]


def parse_mr20_frame(frame: bytes) -> MR20ObjectListStatus | MR20Target:
    if len(frame) != FRAME_SIZE:
        raise MR20FrameError(f"MR20 frame must be {FRAME_SIZE} bytes, got {len(frame)}")
    if frame[:2] != FRAME_HEAD or frame[-2:] != FRAME_TAIL:
        raise MR20FrameError("invalid MR20 frame head or tail")
    if frame[2:4] == OBJECT_STATUS_ID:
        return MR20ObjectListStatus(target_count=frame[4], measurement_count=frame[6] | (frame[7] << 8))
    if frame[2:4] != OBJECT_GENERAL_ID:
        raise MR20FrameError(f"unsupported MR20 frame: 0x{frame[3]:02X}{frame[2]:02X}")

    statuses = {0: "stopped", 1: "oncoming", 2: "going", 3: "crossing"}
    return MR20Target(
        target_id=frame[4],
        longitudinal_distance_m=round((frame[5] * 32 + (frame[6] >> 3)) * 0.1 - 500.0, 1),
        lateral_distance_m=round((((frame[6] & 0x07) * 256 + frame[7]) * 0.1) - 102.3, 1),
        longitudinal_velocity_mps=round(((frame[8] << 2) + (frame[9] >> 6)) * 0.25 - 128.0, 2),
        lateral_velocity_mps=round(((frame[9] & 0x3F) * 8 + (frame[10] >> 5)) * 0.25 - 64.0, 2),
        status=statuses.get(frame[10] & 0x07, "unknown"),
    )


def load_radar_configs(path: str | Path) -> tuple[list[RadarConfig], RiskConfig]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_levels = data["risk"]["levels"]
    levels = tuple(
        (int(item["level"]), float(item["ttc_s"]), float(item["distance_m"]), float(item["closing_speed_mps"]))
        for item in raw_levels
    )
    if sorted(level for level, *_rest in levels) != [1, 2, 3, 4]:
        raise ValueError("MR20 risk levels must define exactly 1..4")
    radars = [
        RadarConfig(
            name=str(item["name"]), side=normalize_side(item["side"]), bind_host=str(item["bind_host"]),
            port=int(item["port"]), radar_ip=str(item["radar_ip"]),
            lateral_min_m=float(item["lateral_min_m"]), lateral_max_m=float(item["lateral_max_m"]),
            longitudinal_min_m=float(item["longitudinal_min_m"]), longitudinal_max_m=float(item["longitudinal_max_m"]),
            approaching_velocity_sign=int(item.get("approaching_velocity_sign", -1)),
            min_consecutive_frames=max(1, int(item.get("min_consecutive_frames", 2))),
            log_path=str(item.get("log_path", f"/var/log/smartbag/{item['name']}.jsonl")),
            mount_x_m=float(item.get("mount_x_m", 0.0)),
            mount_z_m=float(item.get("mount_z_m", 0.0)),
            mount_yaw_deg=float(item.get("mount_yaw_deg", 0.0)),
            invert_lateral=bool(item.get("invert_lateral", False)),
            invert_longitudinal=bool(item.get("invert_longitudinal", False)),
            invert_lateral_velocity=bool(item.get("invert_lateral_velocity", False)),
            invert_longitudinal_velocity=bool(item.get("invert_longitudinal_velocity", False)),
        )
        for item in data.get("radars", []) if item.get("enabled", True)
    ]
    return radars, RiskConfig(levels=levels)


class RadarRiskEvaluator:
    def __init__(self, config: RadarConfig, risk: RiskConfig) -> None:
        self.config = config
        self.risk = risk
        self._consecutive: dict[int, int] = {}

    def evaluate(self, targets: list[MR20Target]) -> tuple[int, MR20Target | None, float | None]:
        candidates: list[tuple[int, MR20Target, float]] = []
        present_ids = {target.target_id for target in targets}
        self._consecutive = {key: value for key, value in self._consecutive.items() if key in present_ids}
        for target in targets:
            level, ttc_s = self._target_level(target)
            if level <= 0:
                self._consecutive.pop(target.target_id, None)
                continue
            self._consecutive[target.target_id] = self._consecutive.get(target.target_id, 0) + 1
            if self._consecutive[target.target_id] >= self.config.min_consecutive_frames:
                candidates.append((level, target, ttc_s))
        if not candidates:
            return 0, None, None
        return max(candidates, key=lambda item: item[0])

    def _target_level(self, target: MR20Target) -> tuple[int, float | None]:
        if not (self.config.longitudinal_min_m <= target.longitudinal_distance_m <= self.config.longitudinal_max_m):
            return 0, None
        if not (self.config.lateral_min_m <= target.lateral_distance_m <= self.config.lateral_max_m):
            return 0, None
        closing_speed = max(0.0, self.config.approaching_velocity_sign * target.longitudinal_velocity_mps)
        if closing_speed <= 0:
            return 0, None
        ttc_s = target.longitudinal_distance_m / closing_speed
        for level, ttc_limit, distance_limit, min_speed in sorted(self.risk.levels, reverse=True):
            if closing_speed >= min_speed and (ttc_s <= ttc_limit or target.longitudinal_distance_m <= distance_limit):
                return level, round(ttc_s, 2)
        return 0, round(ttc_s, 2)


class MR20RadarWorker:
    """Receive complete MR20 measurements and expose every target in each scan."""

    def __init__(
        self,
        config: RadarConfig,
        risk: RiskConfig,
        emit: Callable[[AlertEvent], None] | None = None,
        *,
        on_scan: Callable[[RadarScan], None] | None = None,
        scan_queue_size: int = 4,
        evaluate_legacy_risk: bool = True,
    ) -> None:
        self.config = config
        self.emit = emit
        self.on_scan = on_scan
        self.evaluator = RadarRiskEvaluator(config, risk) if evaluate_legacy_risk else None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._targets: list[MR20Target] = []
        self._expected_targets: int | None = None
        self._measurement_count: int | None = None
        self._scan_queue: "queue.Queue[RadarScan]" = queue.Queue(maxsize=max(1, scan_queue_size))

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"mr20-{self.config.name}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._socket is not None:
            self._socket.close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket = sock
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.2)
        try:
            sock.bind((self.config.bind_host, self.config.port))
            while not self._stop.is_set():
                try:
                    payload, source = sock.recvfrom(2048)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not self.accepts_source(source[0]):
                    continue
                try:
                    message = parse_mr20_frame(payload)
                except MR20FrameError:
                    continue
                self._handle_message(message, source[0])
        finally:
            sock.close()
            self._socket = None

    def _handle_message(self, message: MR20ObjectListStatus | MR20Target, source_ip: str) -> None:
        if isinstance(message, MR20ObjectListStatus):
            self._flush(source_ip)
            self._expected_targets = message.target_count
            self._measurement_count = message.measurement_count
            self._targets = []
            if message.target_count == 0:
                self._flush(source_ip)
                self._expected_targets = None
                self._measurement_count = None
            return
        if self._expected_targets is None:
            return
        self._targets.append(message)
        if len(self._targets) >= self._expected_targets:
            self._flush(source_ip)
            self._expected_targets = None
            self._measurement_count = None

    def accepts_source(self, source_ip: str) -> bool:
        return source_ip == self.config.radar_ip

    def get_scan(self, timeout_s: float = 0.0) -> RadarScan | None:
        try:
            return self._scan_queue.get(timeout=max(0.0, timeout_s))
        except queue.Empty:
            return None

    def _flush(self, source_ip: str) -> None:
        if self._expected_targets is None:
            return
        captured_mono_s = time.monotonic()
        measurement_count = int(self._measurement_count or 0)
        targets = tuple(
            replace(
                target,
                radar_name=self.config.name,
                side=self.config.side,
                measurement_count=measurement_count,
                timestamp=captured_mono_s,
            )
            for target in self._targets
        )
        scan = RadarScan(
            radar_name=self.config.name,
            side=self.config.side,
            measurement_count=measurement_count,
            captured_mono_s=captured_mono_s,
            targets=targets,
        )
        self._offer_scan(scan)
        if self.on_scan is not None:
            self.on_scan(scan)

        if self.evaluator is None:
            level, target, ttc_s = 0, None, None
        else:
            level, target, ttc_s = self.evaluator.evaluate(list(targets))
        self._append_log(source_ip, scan, level, target, ttc_s)
        if self.emit is not None:
            self.emit(
                AlertEvent(
                    side=self.config.side,
                    level=level,
                    source=f"radar:{self.config.name}",
                    track_id=target.target_id if target else None,
                    ts=captured_mono_s,
                )
            )

    def _offer_scan(self, scan: RadarScan) -> None:
        try:
            self._scan_queue.put_nowait(scan)
            return
        except queue.Full:
            pass
        try:
            self._scan_queue.get_nowait()
        except queue.Empty:
            pass
        self._scan_queue.put_nowait(scan)

    def _append_log(
        self,
        source_ip: str,
        scan: RadarScan,
        level: int,
        target: MR20Target | None,
        ttc_s: float | None,
    ) -> None:
        path = Path(self.config.log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "type": "radar_scan",
            "ts": time.time(),
            "captured_mono_s": scan.captured_mono_s,
            "source_ip": source_ip,
            "radar": self.config.name,
            "side": self.config.side,
            "measurement_count": scan.measurement_count,
            "targets": [item.__dict__ for item in scan.targets],
            "legacy_evaluation_enabled": self.evaluator is not None,
            "legacy_level": level,
            "legacy_ttc_s": ttc_s,
            "legacy_target": target.__dict__ if target else None,
        }
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
