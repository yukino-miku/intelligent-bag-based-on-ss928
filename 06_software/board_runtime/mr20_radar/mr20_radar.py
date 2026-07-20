from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

from .mr20_protocol import (
    MR20FrameError,
    MR20ObjectListStatus,
    MR20Target,
    MR20UnknownFrame,
    parse_mr20_datagram,
)


@dataclass(frozen=True)
class RadarConfig:
    name: str
    side: str
    bind_host: str
    bind_port: int
    source_ip: str
    source_port: int | None
    lateral_min_m: float
    lateral_max_m: float
    longitudinal_min_m: float
    longitudinal_max_m: float
    approaching_velocity_sign: int
    min_consecutive_frames: int
    timeout_s: float
    log_jsonl: str = ""


@dataclass(frozen=True)
class RadarRiskConfig:
    levels: tuple[tuple[int, float, float, float], ...]


@dataclass(frozen=True)
class RadarAlert:
    source: str
    source_id: str | None
    side: str
    level: int
    event_kind: str
    ts: float
    ttc_s: float | None = None
    closing_speed_mps: float | None = None
    lateral_distance_m: float | None = None
    longitudinal_distance_m: float | None = None
    clear_reason: str | None = None
    metadata: Mapping[str, object] | None = None


class MR20ScanAssembler:
    def __init__(self) -> None:
        self.measurement_count: int | None = None
        self.expected_targets: int | None = None
        self.targets: list[MR20Target] = []
        self.incomplete_scan_count = 0

    def consume(
        self, frame: MR20ObjectListStatus | MR20Target
    ) -> list[MR20Target] | None:
        if isinstance(frame, MR20ObjectListStatus):
            if self.expected_targets is not None and len(self.targets) != self.expected_targets:
                self.incomplete_scan_count += 1
            self.measurement_count = frame.measurement_count
            self.expected_targets = frame.target_count
            self.targets = []
            if frame.target_count == 0:
                self.expected_targets = None
                return []
            return None
        if self.expected_targets is None:
            self.incomplete_scan_count += 1
            return None
        self.targets.append(frame)
        if len(self.targets) < self.expected_targets:
            return None
        complete = list(self.targets[: self.expected_targets])
        self.expected_targets = None
        self.targets = []
        return complete


class RadarRiskEvaluator:
    def __init__(self, config: RadarConfig, risk: RadarRiskConfig) -> None:
        self.config = config
        self.risk = risk
        self._consecutive: dict[int, int] = {}

    def evaluate(self, targets: Iterable[MR20Target]) -> tuple[int, MR20Target | None, float | None, float | None]:
        target_list = list(targets)
        present_ids = {target.target_id for target in target_list}
        self._consecutive = {
            target_id: count
            for target_id, count in self._consecutive.items()
            if target_id in present_ids
        }
        candidates: list[tuple[int, MR20Target, float, float]] = []
        for target in target_list:
            level, ttc_s, closing_speed = self._target_level(target)
            if level <= 0:
                self._consecutive.pop(target.target_id, None)
                continue
            self._consecutive[target.target_id] = self._consecutive.get(target.target_id, 0) + 1
            if self._consecutive[target.target_id] >= self.config.min_consecutive_frames:
                assert ttc_s is not None and closing_speed is not None
                candidates.append((level, target, ttc_s, closing_speed))
        if not candidates:
            return 0, None, None, None
        level, target, ttc_s, closing_speed = max(
            candidates, key=lambda item: (item[0], -item[2], item[3])
        )
        return level, target, round(ttc_s, 3), round(closing_speed, 3)

    def _target_level(self, target: MR20Target) -> tuple[int, float | None, float | None]:
        if not self.config.longitudinal_min_m <= target.longitudinal_distance_m <= self.config.longitudinal_max_m:
            return 0, None, None
        if not self.config.lateral_min_m <= target.lateral_distance_m <= self.config.lateral_max_m:
            return 0, None, None
        closing_speed = max(
            0.0,
            self.config.approaching_velocity_sign * target.longitudinal_velocity_mps,
        )
        if closing_speed <= 0.0:
            return 0, None, None
        ttc_s = target.longitudinal_distance_m / closing_speed
        for level, ttc_limit, distance_limit, min_speed in sorted(
            self.risk.levels, key=lambda item: item[0], reverse=True
        ):
            if closing_speed >= min_speed and (
                ttc_s <= ttc_limit or target.longitudinal_distance_m <= distance_limit
            ):
                return level, ttc_s, closing_speed
        return 0, ttc_s, closing_speed


class MR20RadarWorker:
    def __init__(
        self,
        config: RadarConfig,
        risk: RadarRiskConfig,
        emit: Callable[[RadarAlert], None],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.emit = emit
        self.clock = clock
        self.evaluator = RadarRiskEvaluator(config, risk)
        self.assembler = MR20ScanAssembler()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._started = threading.Event()
        self._last_level = 0
        self.metrics: dict[str, int | float | str | None] = {
            "datagram_count": 0,
            "frame_count": 0,
            "status_60a_count": 0,
            "target_60b_count": 0,
            "unknown_frame_count": 0,
            "invalid_frame_count": 0,
            "rejected_source_count": 0,
            "scan_count": 0,
            "last_measurement_count": None,
            "last_error": "",
        }

    def accepts_source(self, ip: str, port: int) -> bool:
        if ip != self.config.source_ip:
            return False
        return self.config.source_port is None or int(port) == self.config.source_port

    def handle_datagram(self, payload: bytes, source: tuple[str, int]) -> None:
        if not self.accepts_source(source[0], source[1]):
            self.metrics["rejected_source_count"] = int(self.metrics["rejected_source_count"]) + 1
            return
        self.metrics["datagram_count"] = int(self.metrics["datagram_count"]) + 1
        try:
            frames = parse_mr20_datagram(payload)
        except MR20FrameError as exc:
            self.metrics["invalid_frame_count"] = int(self.metrics["invalid_frame_count"]) + 1
            self.metrics["last_error"] = str(exc)
            return
        for frame in frames:
            self.metrics["frame_count"] = int(self.metrics["frame_count"]) + 1
            if isinstance(frame, MR20UnknownFrame):
                self.metrics["unknown_frame_count"] = int(self.metrics["unknown_frame_count"]) + 1
                self._log("unknown_frame", {"frame_id": frame.frame_id})
                continue
            if isinstance(frame, MR20ObjectListStatus):
                self.metrics["status_60a_count"] = int(self.metrics["status_60a_count"]) + 1
                self.metrics["last_measurement_count"] = frame.measurement_count
            else:
                self.metrics["target_60b_count"] = int(self.metrics["target_60b_count"]) + 1
            targets = self.assembler.consume(frame)
            if targets is not None:
                self._emit_scan(targets)

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("MR20 worker already started")
        self._thread = threading.Thread(target=self._run, name=f"mr20-{self.config.name}", daemon=True)
        self._thread.start()
        if not self._started.wait(timeout=1.0):
            raise RuntimeError(f"MR20 {self.config.name} did not complete UDP startup")
        if self.metrics["last_error"]:
            raise RuntimeError(f"MR20 {self.config.name} startup failed: {self.metrics['last_error']}")

    def stop(self) -> None:
        self._stop.set()
        if self._socket is not None:
            self._socket.close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._emit_exit_clear()

    def status(self) -> dict[str, object]:
        return {
            **self.metrics,
            "name": self.config.name,
            "side": self.config.side,
            "bind": f"{self.config.bind_host}:{self.config.bind_port}",
            "source": f"{self.config.source_ip}:{self.config.source_port or '*'}",
            "last_level": self._last_level,
            "incomplete_scan_count": self.assembler.incomplete_scan_count,
            "running": bool(self._thread and self._thread.is_alive()),
        }

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket = sock
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(0.2)
            sock.bind((self.config.bind_host, self.config.bind_port))
            self._started.set()
            while not self._stop.is_set():
                try:
                    payload, source = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    raise
                self.handle_datagram(payload, source)
        except Exception as exc:
            self.metrics["last_error"] = f"{type(exc).__name__}: {exc}"
            self._started.set()
        finally:
            try:
                sock.close()
            except OSError:
                pass
            self._emit_exit_clear()

    def _emit_exit_clear(self) -> None:
        if self._last_level <= 0:
            return
        self.emit(
            RadarAlert(
                source=f"radar:{self.config.name}",
                source_id=None,
                side=self.config.side,
                level=0,
                event_kind="state_change",
                ts=self.clock(),
                clear_reason="radar_exit",
            )
        )
        self._last_level = 0

    def _emit_scan(self, targets: list[MR20Target]) -> None:
        self.metrics["scan_count"] = int(self.metrics["scan_count"]) + 1
        level, target, ttc_s, closing_speed = self.evaluator.evaluate(targets)
        event_kind = "state_change" if level != self._last_level else "heartbeat"
        alert = RadarAlert(
            source=f"radar:{self.config.name}",
            source_id=str(target.target_id) if target is not None else None,
            side=self.config.side,
            level=level,
            event_kind=event_kind,
            ts=self.clock(),
            ttc_s=ttc_s,
            closing_speed_mps=closing_speed,
            lateral_distance_m=target.lateral_distance_m if target else None,
            longitudinal_distance_m=target.longitudinal_distance_m if target else None,
            clear_reason="no_confirmed_target" if level == 0 and self._last_level > 0 else None,
            metadata={
                "target_count": len(targets),
                "measurement_count": self.assembler.measurement_count,
                "status": target.status if target else None,
            },
        )
        self._last_level = level
        self.emit(alert)
        self._log("radar_alert", alert.__dict__)

    def _log(self, kind: str, payload: Mapping[str, object]) -> None:
        if not self.config.log_jsonl:
            return
        path = Path(self.config.log_jsonl)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"type": kind, "logged_at": self.clock(), **dict(payload)}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")


def load_mr20_config(path: str | Path) -> tuple[list[RadarConfig], RadarRiskConfig]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    levels = tuple(
        (
            int(item["level"]),
            float(item["ttc_s"]),
            float(item["distance_m"]),
            float(item["closing_speed_mps"]),
        )
        for item in data["risk"]["levels"]
    )
    if sorted(level for level, *_ in levels) != [1, 2, 3, 4]:
        raise ValueError("MR20 risk levels must define exactly levels 1..4")
    radars = []
    for item in data.get("radars", []):
        if not bool(item.get("enabled", True)):
            continue
        side = str(item["side"]).lower()
        if side not in ("left", "right"):
            raise ValueError(f"invalid MR20 side: {side}")
        radars.append(
            RadarConfig(
                name=str(item["name"]),
                side=side,
                bind_host=str(item["bind_host"]),
                bind_port=int(item["bind_port"]),
                source_ip=str(item["source_ip"]),
                source_port=int(item["source_port"]) if item.get("source_port") is not None else None,
                lateral_min_m=float(item["lateral_min_m"]),
                lateral_max_m=float(item["lateral_max_m"]),
                longitudinal_min_m=float(item["longitudinal_min_m"]),
                longitudinal_max_m=float(item["longitudinal_max_m"]),
                approaching_velocity_sign=int(item.get("approaching_velocity_sign", -1)),
                min_consecutive_frames=max(1, int(item.get("min_consecutive_frames", 2))),
                timeout_s=max(0.05, float(item.get("timeout_s", 1.0))),
                log_jsonl=str(item.get("log_jsonl", "")),
            )
        )
    return radars, RadarRiskConfig(levels=levels)
