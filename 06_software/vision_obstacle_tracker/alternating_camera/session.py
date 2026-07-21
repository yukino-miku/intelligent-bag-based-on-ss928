from __future__ import annotations

import csv
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import time
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Iterable

from .scheduler import CapturedFrame, SwitchEvent, percentile

try:
    import resource
except ImportError:  # pragma: no cover - Windows development host
    resource = None


SWITCH_EVENT_FIELDS = (
    "session_id",
    "slice_id",
    "switch_index",
    "from_side",
    "to_side",
    "switch_start_monotonic_s",
    "capture_slice_start_s",
    "capture_slice_end_s",
    "streamoff_complete_s",
    "streamoff_start_s",
    "streamoff_end_s",
    "streamoff_latency_ms",
    "streamon_start_s",
    "streamon_end_s",
    "streamon_latency_ms",
    "first_frame_s",
    "first_frame_latency_ms",
    "warmup_frames_requested",
    "warmup_frames_received",
    "warmup_frames_discarded",
    "valid_frames",
    "slice_duration_ms",
    "requested_fps",
    "actual_slice_fps",
    "left_blind_interval_ms",
    "right_blind_interval_ms",
    "connection_state",
    "disconnect_time_s",
    "offline_detect_latency_ms",
    "reconnect_start_s",
    "reconnect_success_s",
    "reconnect_duration_ms",
    "tracker_reset",
    "first_recovered_frame_latency_ms",
    "success",
    "error_type",
    "error_message",
)

CAMERA_EVENT_FIELDS = (
    "session_id",
    "side",
    "frame_sequence",
    "captured_monotonic_s",
    "processed_monotonic_s",
    "frame_age_ms",
    "width",
    "height",
    "pixel_format",
    "slice_id",
    "selected_for_inference",
    "capture_slice_start_s",
    "capture_slice_end_s",
    "streamoff_complete_s",
    "decode_start_s",
    "decode_end_s",
    "inference_start_s",
    "inference_end_s",
    "tracking_start_s",
    "tracking_end_s",
    "risk_start_s",
    "risk_end_s",
    "overlay_start_s",
    "overlay_end_s",
    "jpeg_encode_start_s",
    "jpeg_encode_end_s",
    "next_camera_streamon_s",
    "next_camera_first_frame_s",
    "processing_complete_s",
    "end_to_end_observation_gap_ms",
    "side_to_side_latency_ms",
    "decode_ms",
    "camera_online",
    "active_side",
    "dropped_frames",
    "reconnect_count",
    "last_error",
)

PERFORMANCE_FIELDS = (
    "timestamp",
    "active_side",
    "left_effective_fps",
    "right_effective_fps",
    "left_last_frame_age_ms",
    "right_last_frame_age_ms",
    "switches_per_minute",
    "mean_switch_latency_ms",
    "p95_switch_latency_ms",
    "inference_fps",
    "inference_ms",
    "detector_preprocess_ms",
    "npu_inference_ms",
    "detector_postprocess_ms",
    "tracking_ms",
    "risk_ms",
    "draw_ms",
    "jpeg_encode_ms",
    "gateway_clients",
    "cpu_percent",
    "memory_used_mb",
    "memory_percent",
    "process_rss_mb",
    "temperature_c",
    "load_1m",
    "usb_errors",
    "camera_errors",
    "capture_only_max_blind_ms",
    "end_to_end_left_max_gap_ms",
    "end_to_end_right_max_gap_ms",
    "end_to_end_max_gap_ms",
    "end_to_end_p50_gap_ms",
    "end_to_end_p95_gap_ms",
    "end_to_end_p99_gap_ms",
    "left_to_right_p95_latency_ms",
    "right_to_left_p95_latency_ms",
    "captured_valid_frames",
    "selected_inference_frames",
    "skipped_inference_frames",
    "inference_frames_per_slice",
    "inference_queue_depth",
    "oldest_pending_frame_age_ms",
)

ALERT_FIELDS = (
    "timestamp",
    "side",
    "track_id",
    "class",
    "distance_m",
    "raw_level",
    "visual_level",
    "haptic_level",
    "score",
    "path_conflict",
    "moving_away",
    "cpa_time_s",
    "cpa_distance_m",
    "corridor_entry_time_s",
    "approach_consistency",
    "path_conflict_consistency",
    "stabilizer_pending_level",
    "stabilizer_pending_count",
    "stabilizer_required_frames",
    "slice_id",
    "pending_slice_count",
    "required_slices",
    "confirmed_across_slices",
    "fast_path_reason",
    "event_kind",
    "clear_reason",
    "observation_age_ms",
)


class _BufferedCsv:
    def __init__(self, path: Path, fieldnames: Iterable[str], flush_interval_s: float = 1.0) -> None:
        self.path = path
        self.file = path.open("w", encoding="utf-8", newline="")
        self.writer = csv.DictWriter(self.file, fieldnames=tuple(fieldnames), extrasaction="ignore")
        self.writer.writeheader()
        self.flush_interval_s = flush_interval_s
        self.last_flush_s = time.monotonic()
        self.pending_rows = 0

    def write(self, row: dict[str, object]) -> None:
        self.writer.writerow(row)
        self.pending_rows += 1
        now_s = time.monotonic()
        if self.pending_rows >= 64 or now_s - self.last_flush_s >= self.flush_interval_s:
            self.flush()

    def flush(self) -> None:
        self.file.flush()
        self.pending_rows = 0
        self.last_flush_s = time.monotonic()

    def close(self) -> None:
        self.flush()
        self.file.close()


class AlternatingSessionRecorder:
    """Buffered experiment log writer; raw sessions stay below an ignored media root."""

    def __init__(
        self,
        output_root: str | os.PathLike[str],
        session_id: str,
        *,
        latest_summary_path: str | os.PathLike[str] | None = None,
        clock=time.monotonic,
    ) -> None:
        self.output_root = Path(output_root)
        self.session_id = session_id
        self.session_dir = self.output_root / session_id
        self.session_dir.mkdir(parents=True, exist_ok=False)
        self.snapshots_dir = self.session_dir / "snapshots"
        self.snapshots_dir.mkdir()
        self.latest_summary_path = Path(latest_summary_path) if latest_summary_path else None
        self.clock = clock
        self.started_monotonic_s = float(clock())
        self.started_utc = datetime.now(timezone.utc)
        self.started_local = datetime.now().astimezone()
        self.switch_csv = _BufferedCsv(self.session_dir / "switch-events.csv", SWITCH_EVENT_FIELDS)
        self.camera_csv = _BufferedCsv(self.session_dir / "camera-events.csv", CAMERA_EVENT_FIELDS)
        self.performance_csv = _BufferedCsv(self.session_dir / "performance.csv", PERFORMANCE_FIELDS)
        self.alerts_csv = _BufferedCsv(self.session_dir / "alerts.csv", ALERT_FIELDS)
        self.errors_file = (self.session_dir / "errors.log").open("w", encoding="utf-8")
        self.switch_events: deque[SwitchEvent] = deque(maxlen=TELEMETRY_WINDOW_SIZE)
        self.performance_rows: deque[dict[str, object]] = deque(maxlen=PERFORMANCE_WINDOW_SIZE)
        self.total_switch_count = 0
        self.successful_switch_count = 0
        self.switch_error_counts: dict[str, int] = {}
        self.usb_error_count = 0
        self.camera_error_count = 0
        self.blind_interval_sum_ms = {"left": 0.0, "right": 0.0}
        self.blind_interval_count = {"left": 0, "right": 0}
        self.blind_interval_max_ms = {"left": 0.0, "right": 0.0}
        self.frame_counts = {"left": 0, "right": 0}
        self.selected_frame_counts = {"left": 0, "right": 0}
        self.skipped_inference_frames = 0
        self.end_to_end_gaps_ms = {
            "left": deque(maxlen=TELEMETRY_WINDOW_SIZE),
            "right": deque(maxlen=TELEMETRY_WINDOW_SIZE),
        }
        self.end_to_end_max_ms = {"left": 0.0, "right": 0.0}
        self.side_to_side_latencies_ms = {
            "left_to_right": deque(maxlen=TELEMETRY_WINDOW_SIZE),
            "right_to_left": deque(maxlen=TELEMETRY_WINDOW_SIZE),
        }
        self._performance_totals: dict[str, float] = {}
        self._performance_counts: dict[str, int] = {}
        self._performance_maxima: dict[str, float] = {}
        self.camera_reconnect_counts = {"left": 0, "right": 0}
        self.camera_reconnects = 0
        self.camera_offline_clear_verified: bool | None = None
        self.alert_count = 0
        self.clear_count = 0
        self.state_change_count = 0
        self.heartbeat_count = 0
        self.stale_clear_count = 0
        self.observed_safe_clear_count = 0
        self.detector_exit_clear_count = 0
        self.camera_disconnect_clear_count = 0
        self.cross_slice_confirmed_count = 0
        self.fast_path_count = 0
        self.risk_level_counts = {str(level): 0 for level in range(5)}
        self.single_frame_jump_suppressed_count = 0
        self.dropped_frame_count = 0
        self._last_sequence_by_side: dict[str, int] = {}
        self._last_process_time_s = time.process_time()
        self._last_cpu_wall_s = self.started_monotonic_s
        self.metadata: dict[str, object] = self._base_metadata()
        self._closed = False

    def _base_metadata(self) -> dict[str, object]:
        memory = read_memory_info()
        git = git_snapshot()
        return {
            "session_id": self.session_id,
            "start_utc": self.started_utc.isoformat(),
            "start_local": self.started_local.isoformat(),
            "git_branch": git["branch"],
            "git_commit": git["commit"],
            "git_worktree_status": git["status"],
            "board_model": read_first(("/proc/device-tree/model", "/sys/firmware/devicetree/base/model")),
            "os": read_os_release(),
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "cpu_count": os.cpu_count(),
            "mem_total_mb": round(memory.get("MemTotal", 0) / 1024.0, 3),
            "mem_available_mb": round(memory.get("MemAvailable", 0) / 1024.0, 3),
            "swap_total_mb": round(memory.get("SwapTotal", 0) / 1024.0, 3),
            "python_version": platform.python_version(),
            "opencv_version": package_version("opencv-python", import_name="cv2"),
            "torch_version": package_version("torch"),
            "ultralytics_version": package_version("ultralytics"),
            "lap_version": package_version("lap"),
            "usb_topology": command_output(["lsusb", "-t"]),
        }

    def update_metadata(self, values: dict[str, object]) -> None:
        self.metadata.update(values)
        self._write_json(self.session_dir / "session.json", self.metadata)

    def record_switch(self, event: SwitchEvent) -> None:
        row = {"session_id": self.session_id, **event.as_dict()}
        self.switch_csv.write(row)
        self.switch_events.append(event)
        self.total_switch_count += 1
        if event.success:
            self.successful_switch_count += 1
        else:
            self.camera_error_count += 1
        if event.error_type:
            self.switch_error_counts[event.error_type] = self.switch_error_counts.get(event.error_type, 0) + 1
            if event.error_type == "enospc" or event.error_type.startswith("oserror_"):
                self.usb_error_count += 1
        for side in ("left", "right"):
            value = getattr(event, f"{side}_blind_interval_ms")
            if value is None:
                continue
            numeric_value = float(value)
            self.blind_interval_sum_ms[side] += numeric_value
            self.blind_interval_count[side] += 1
            self.blind_interval_max_ms[side] = max(self.blind_interval_max_ms[side], numeric_value)
        if not event.success:
            self.error(f"switch {event.switch_index} {event.to_side}: {event.error_type}: {event.error_message}")

    def record_frame(
        self,
        frame: CapturedFrame,
        *,
        active_side: str | None,
        decode_ms: float | str = "",
        selected_for_inference: bool = True,
        timeline: object | None = None,
        end_to_end_observation_gap_ms: float | None = None,
        side_to_side_latency_ms: float | None = None,
        dropped_frames: int = 0,
        reconnect_count: int = 0,
        last_error: str = "",
    ) -> None:
        previous_sequence = self._last_sequence_by_side.get(frame.side)
        sequence_gap = (
            max(0, int(frame.sequence) - previous_sequence - 1)
            if previous_sequence is not None and int(frame.sequence) > previous_sequence
            else 0
        )
        self._last_sequence_by_side[frame.side] = int(frame.sequence)
        frame_drops = max(0, int(dropped_frames)) + sequence_gap
        self.dropped_frame_count += frame_drops
        self.frame_counts[frame.side] += 1
        if selected_for_inference:
            self.selected_frame_counts[frame.side] += 1
        else:
            self.skipped_inference_frames += 1
        if end_to_end_observation_gap_ms is not None:
            gap_ms = float(end_to_end_observation_gap_ms)
            self.end_to_end_gaps_ms[frame.side].append(gap_ms)
            self.end_to_end_max_ms[frame.side] = max(self.end_to_end_max_ms[frame.side], gap_ms)
        if side_to_side_latency_ms is not None:
            other = "right" if frame.side == "left" else "left"
            self.side_to_side_latencies_ms[f"{other}_to_{frame.side}"].append(float(side_to_side_latency_ms))
        self.camera_reconnect_counts[frame.side] = max(
            self.camera_reconnect_counts[frame.side],
            int(reconnect_count),
        )
        self.camera_reconnects = sum(self.camera_reconnect_counts.values())
        timeline_values = timeline.as_dict() if timeline is not None else {}
        self.camera_csv.write(
            {
                "session_id": self.session_id,
                "side": frame.side,
                "frame_sequence": frame.sequence,
                "captured_monotonic_s": round(frame.captured_at_s, 9),
                "processed_monotonic_s": round(frame.processed_at_s, 9),
                "frame_age_ms": round(max(0.0, frame.processed_at_s - frame.captured_at_s) * 1000.0, 3),
                "width": frame.width,
                "height": frame.height,
                "pixel_format": frame.pixel_format,
                "slice_id": frame.slice_id,
                "selected_for_inference": bool(selected_for_inference),
                **timeline_values,
                "end_to_end_observation_gap_ms": (
                    round(float(end_to_end_observation_gap_ms), 3)
                    if end_to_end_observation_gap_ms is not None
                    else ""
                ),
                "side_to_side_latency_ms": (
                    round(float(side_to_side_latency_ms), 3)
                    if side_to_side_latency_ms is not None
                    else ""
                ),
                "decode_ms": round(float(decode_ms), 3) if decode_ms != "" else "",
                "camera_online": True,
                "active_side": active_side or "none",
                "dropped_frames": frame_drops,
                "reconnect_count": reconnect_count,
                "last_error": last_error,
            }
        )

    def mark_camera_offline_clear_verified(self) -> None:
        self.camera_offline_clear_verified = True

    def record_single_frame_jump_suppressed(self, count: int = 1) -> None:
        self.single_frame_jump_suppressed_count += max(0, int(count))

    def record_performance(
        self,
        status: dict[str, object],
        *,
        gateway_clients: int = 0,
        usb_errors: int | None = None,
        camera_errors: int | None = None,
        stage_metrics: dict[str, float] | None = None,
    ) -> dict[str, object]:
        stage_metrics = stage_metrics or {}
        now_s = float(self.clock())
        process_now_s = time.process_time()
        elapsed_s = max(now_s - self._last_cpu_wall_s, 1e-6)
        cpu_percent = max(0.0, (process_now_s - self._last_process_time_s) / elapsed_s * 100.0)
        self._last_cpu_wall_s = now_s
        self._last_process_time_s = process_now_s
        memory = read_memory_info()
        total_kb = memory.get("MemTotal", 0)
        available_kb = memory.get("MemAvailable", 0)
        used_mb = max(0, total_kb - available_kb) / 1024.0
        memory_percent = (total_kb - available_kb) / total_kb * 100.0 if total_kb else 0.0
        row = {
            "timestamp": round(now_s, 6),
            "active_side": status.get("active_camera") or "none",
            "left_effective_fps": status.get("left_effective_fps", 0.0),
            "right_effective_fps": status.get("right_effective_fps", 0.0),
            "left_last_frame_age_ms": status.get("left_last_frame_age_ms"),
            "right_last_frame_age_ms": status.get("right_last_frame_age_ms"),
            "switches_per_minute": round(float(status.get("switch_count", 0)) / max(now_s - self.started_monotonic_s, 1e-6) * 60.0, 3),
            "mean_switch_latency_ms": status.get("average_switch_latency_ms"),
            "p95_switch_latency_ms": status.get("p95_switch_latency_ms"),
            "inference_fps": round(float(stage_metrics.get("inference_fps", 0.0)), 3),
            "inference_ms": round(float(stage_metrics.get("inference_ms", 0.0)), 3),
            "detector_preprocess_ms": round(
                float(stage_metrics.get("detector_preprocess_ms", 0.0)), 3
            ),
            "npu_inference_ms": round(float(stage_metrics.get("npu_inference_ms", 0.0)), 3),
            "detector_postprocess_ms": round(
                float(stage_metrics.get("detector_postprocess_ms", 0.0)), 3
            ),
            "tracking_ms": round(float(stage_metrics.get("tracking_ms", 0.0)), 3),
            "risk_ms": round(float(stage_metrics.get("risk_ms", 0.0)), 3),
            "draw_ms": round(float(stage_metrics.get("draw_ms", 0.0)), 3),
            "jpeg_encode_ms": round(float(stage_metrics.get("jpeg_encode_ms", 0.0)), 3),
            "gateway_clients": gateway_clients,
            "cpu_percent": round(cpu_percent, 3),
            "memory_used_mb": round(used_mb, 3),
            "memory_percent": round(memory_percent, 3),
            "process_rss_mb": round(process_rss_mb(), 3),
            "temperature_c": read_temperature_c(),
            "load_1m": round(os.getloadavg()[0], 3) if hasattr(os, "getloadavg") else "",
            "usb_errors": self._usb_error_count() if usb_errors is None else usb_errors,
            "camera_errors": self._camera_error_count() if camera_errors is None else camera_errors,
            "capture_only_max_blind_ms": stage_metrics.get("capture_only_max_blind_ms", 0.0),
            "end_to_end_left_max_gap_ms": stage_metrics.get("end_to_end_left_max_gap_ms", 0.0),
            "end_to_end_right_max_gap_ms": stage_metrics.get("end_to_end_right_max_gap_ms", 0.0),
            "end_to_end_max_gap_ms": stage_metrics.get("end_to_end_max_gap_ms", 0.0),
            "end_to_end_p50_gap_ms": stage_metrics.get("end_to_end_p50_gap_ms", ""),
            "end_to_end_p95_gap_ms": stage_metrics.get("end_to_end_p95_gap_ms", ""),
            "end_to_end_p99_gap_ms": stage_metrics.get("end_to_end_p99_gap_ms", ""),
            "left_to_right_p95_latency_ms": stage_metrics.get("left_to_right_p95_latency_ms", ""),
            "right_to_left_p95_latency_ms": stage_metrics.get("right_to_left_p95_latency_ms", ""),
            "captured_valid_frames": stage_metrics.get(
                "captured_valid_frames", sum(self.frame_counts.values())
            ),
            "selected_inference_frames": stage_metrics.get(
                "selected_inference_frames", sum(self.selected_frame_counts.values())
            ),
            "skipped_inference_frames": stage_metrics.get(
                "skipped_inference_frames", self.skipped_inference_frames
            ),
            "inference_frames_per_slice": stage_metrics.get("inference_frames_per_slice", ""),
            "inference_queue_depth": stage_metrics.get("inference_queue_depth", 0),
            "oldest_pending_frame_age_ms": stage_metrics.get("oldest_pending_frame_age_ms", 0.0),
        }
        self.performance_csv.write(row)
        self.performance_rows.append(row)
        for name in (
            "cpu_percent",
            "process_rss_mb",
            "memory_used_mb",
            "temperature_c",
            "inference_fps",
            "jpeg_encode_ms",
        ):
            value = row.get(name)
            if not isinstance(value, (int, float)):
                continue
            numeric_value = float(value)
            self._performance_totals[name] = self._performance_totals.get(name, 0.0) + numeric_value
            self._performance_counts[name] = self._performance_counts.get(name, 0) + 1
            self._performance_maxima[name] = max(
                numeric_value,
                self._performance_maxima.get(name, numeric_value),
            )
        return row

    def record_alert(self, row: dict[str, object]) -> None:
        self.alerts_csv.write(row)
        self.alert_count += 1
        level_value = int(row.get("haptic_level", 0) or 0)
        event_kind = str(row.get("event_kind", "state_change"))
        clear_reason = str(row.get("clear_reason", ""))
        if level_value == 0:
            self.clear_count += 1
            if clear_reason == "stale_observation":
                self.stale_clear_count += 1
            elif clear_reason == "observed_safe":
                self.observed_safe_clear_count += 1
            elif clear_reason == "camera_disconnect":
                self.camera_disconnect_clear_count += 1
            elif clear_reason == "shutdown":
                self.detector_exit_clear_count += 1
        if event_kind == "state_change":
            self.state_change_count += 1
            level = str(level_value)
            self.risk_level_counts[level] = self.risk_level_counts.get(level, 0) + 1
        elif event_kind == "heartbeat":
            self.heartbeat_count += 1
        if event_kind == "state_change" and _as_bool(row.get("confirmed_across_slices")):
            self.cross_slice_confirmed_count += 1
        if event_kind == "state_change" and row.get("fast_path_reason"):
            self.fast_path_count += 1

    def _usb_error_count(self) -> int:
        return self.usb_error_count

    def _camera_error_count(self) -> int:
        return self.camera_error_count

    def save_snapshot(self, frame: CapturedFrame, switch_index: int) -> Path:
        path = self.snapshots_dir / f"{switch_index:06d}-{frame.side}.jpg"
        path.write_bytes(frame.data)
        return path

    def error(self, message: str) -> None:
        timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
        self.errors_file.write(f"{timestamp} {message}\n")
        self.errors_file.flush()

    def finish(
        self,
        *,
        acceptance_min_duration_s: float = 1800.0,
        acceptance_max_blind_interval_ms: float | None = None,
    ) -> dict[str, object]:
        elapsed_s = max(float(self.clock()) - self.started_monotonic_s, 0.0)
        switch_latencies = [event.streamoff_latency_ms + event.streamon_latency_ms for event in self.switch_events]
        first_frame_latencies = [
            float(event.first_frame_latency_ms)
            for event in self.switch_events
            if event.first_frame_latency_ms is not None
        ]
        blind_by_side = {
            side: [
                float(getattr(event, f"{side}_blind_interval_ms"))
                for event in self.switch_events
                if getattr(event, f"{side}_blind_interval_ms") is not None
            ]
            for side in ("left", "right")
        }
        capture_blind_by_switch = [
            max(values)
            for event in self.switch_events
            if (
                values := [
                    float(value)
                    for side in ("left", "right")
                    if (value := getattr(event, f"{side}_blind_interval_ms")) is not None
                ]
            )
        ]
        success_rate = (
            self.successful_switch_count / self.total_switch_count * 100.0
            if self.total_switch_count
            else 0.0
        )
        streamon_failures = self.switch_error_counts.get("enospc", 0) + self.switch_error_counts.get(
            "streamon_failure", 0
        )
        first_frame_timeouts = self.switch_error_counts.get("first_frame_timeout", 0)
        maximum_blind = max(self.blind_interval_max_ms.values(), default=0.0)
        end_to_end_combined = list(self.end_to_end_gaps_ms["left"]) + list(
            self.end_to_end_gaps_ms["right"]
        )
        end_to_end_maximum = max(self.end_to_end_max_ms.values(), default=0.0)
        acceptance_gap = end_to_end_maximum if end_to_end_combined else maximum_blind
        acceptance_gap_metric = (
            "end_to_end_observation_gap_ms" if end_to_end_combined else "capture_switch_blind_interval_ms"
        )
        has_enospc = self.switch_error_counts.get("enospc", 0) > 0
        acceptance_met = (
            elapsed_s >= acceptance_min_duration_s
            and success_rate >= 99.0
            and not has_enospc
            and self.frame_counts["left"] > 0
            and self.frame_counts["right"] > 0
            and first_frame_timeouts == 0
            and (
                acceptance_max_blind_interval_ms is None
                or acceptance_gap <= acceptance_max_blind_interval_ms
            )
        )
        summary = {
            "session_id": self.session_id,
            "duration_s": round(elapsed_s, 3),
            "switch_count": self.total_switch_count,
            "successful_switches": self.successful_switch_count,
            "switch_success_rate_percent": round(success_rate, 3),
            "streamon_failures": streamon_failures,
            "streamoff_failures": self.switch_error_counts.get("streamoff_failure", 0),
            "first_frame_timeouts": first_frame_timeouts,
            "camera_reconnects": self.camera_reconnects,
            "dropped_frames": self.dropped_frame_count,
            "usb_errors": self._usb_error_count(),
            "camera_errors": self._camera_error_count(),
            "left_valid_frames": self.frame_counts["left"],
            "right_valid_frames": self.frame_counts["right"],
            "captured_valid_frames": sum(self.frame_counts.values()),
            "selected_inference_frames": sum(self.selected_frame_counts.values()),
            "skipped_inference_frames": self.skipped_inference_frames,
            "left_effective_fps": round(self.frame_counts["left"] / max(elapsed_s, 1e-9), 3),
            "right_effective_fps": round(self.frame_counts["right"] / max(elapsed_s, 1e-9), 3),
            "left_max_blind_interval_ms": round(self.blind_interval_max_ms["left"], 3),
            "right_max_blind_interval_ms": round(self.blind_interval_max_ms["right"], 3),
            "maximum_blind_interval_ms": round(maximum_blind, 3),
            "capture_only_max_blind_ms": round(maximum_blind, 3),
            "capture_only_p50_blind_ms": (
                round(percentile(capture_blind_by_switch, 0.50), 3)
                if capture_blind_by_switch
                else None
            ),
            "capture_only_p95_blind_ms": (
                round(percentile(capture_blind_by_switch, 0.95), 3)
                if capture_blind_by_switch
                else None
            ),
            "capture_only_p99_blind_ms": (
                round(percentile(capture_blind_by_switch, 0.99), 3)
                if capture_blind_by_switch
                else None
            ),
            "end_to_end_left_max_gap_ms": round(self.end_to_end_max_ms["left"], 3),
            "end_to_end_right_max_gap_ms": round(self.end_to_end_max_ms["right"], 3),
            "end_to_end_left_p50_gap_ms": self._window_percentile(
                self.end_to_end_gaps_ms["left"], 0.50
            ),
            "end_to_end_left_p95_gap_ms": self._window_percentile(
                self.end_to_end_gaps_ms["left"], 0.95
            ),
            "end_to_end_left_p99_gap_ms": self._window_percentile(
                self.end_to_end_gaps_ms["left"], 0.99
            ),
            "end_to_end_right_p50_gap_ms": self._window_percentile(
                self.end_to_end_gaps_ms["right"], 0.50
            ),
            "end_to_end_right_p95_gap_ms": self._window_percentile(
                self.end_to_end_gaps_ms["right"], 0.95
            ),
            "end_to_end_right_p99_gap_ms": self._window_percentile(
                self.end_to_end_gaps_ms["right"], 0.99
            ),
            "end_to_end_max_gap_ms": round(end_to_end_maximum, 3),
            "end_to_end_p50_gap_ms": (
                round(percentile(end_to_end_combined, 0.50), 3) if end_to_end_combined else None
            ),
            "end_to_end_p95_gap_ms": (
                round(percentile(end_to_end_combined, 0.95), 3) if end_to_end_combined else None
            ),
            "end_to_end_p99_gap_ms": (
                round(percentile(end_to_end_combined, 0.99), 3) if end_to_end_combined else None
            ),
            "left_to_right_p95_latency_ms": (
                round(percentile(self.side_to_side_latencies_ms["left_to_right"], 0.95), 3)
                if self.side_to_side_latencies_ms["left_to_right"]
                else None
            ),
            "right_to_left_p95_latency_ms": (
                round(percentile(self.side_to_side_latencies_ms["right_to_left"], 0.95), 3)
                if self.side_to_side_latencies_ms["right_to_left"]
                else None
            ),
            "mean_blind_interval_ms": round(
                sum(self.blind_interval_sum_ms.values())
                / max(sum(self.blind_interval_count.values()), 1),
                3,
            ),
            "switch_latency_ms": percentile_summary(switch_latencies),
            "first_frame_latency_ms": percentile_summary(first_frame_latencies),
            "max_process_rss_mb": self._performance_max("process_rss_mb"),
            "average_process_rss_mb": self._performance_average("process_rss_mb"),
            "max_memory_used_mb": self._performance_max("memory_used_mb"),
            "average_memory_used_mb": self._performance_average("memory_used_mb"),
            "max_cpu_percent": self._performance_max("cpu_percent"),
            "average_cpu_percent": self._performance_average("cpu_percent"),
            "max_temperature_c": self._performance_max("temperature_c", default=None),
            "inference_fps": self._performance_average("inference_fps"),
            "jpeg_encode_ms": self._performance_average("jpeg_encode_ms"),
            "alert_count": self.alert_count,
            "clear_count": self.clear_count,
            "alerts_by_level": dict(self.risk_level_counts),
            "state_change_count": self.state_change_count,
            "heartbeat_count": self.heartbeat_count,
            "stale_clear_count": self.stale_clear_count,
            "observed_safe_clear_count": self.observed_safe_clear_count,
            "detector_exit_clear_count": self.detector_exit_clear_count,
            "camera_disconnect_clear_count": self.camera_disconnect_clear_count,
            "single_frame_jump_suppressed_count": self.single_frame_jump_suppressed_count,
            "cross_slice_confirmed_count": self.cross_slice_confirmed_count,
            "emergency_fast_path_count": self.fast_path_count,
            "fast_path_count": self.fast_path_count,
            "risk_level_counts": dict(self.risk_level_counts),
            "camera_offline_clear_verified": self.camera_offline_clear_verified,
            "enospc_observed": has_enospc,
            "acceptance_min_duration_s": acceptance_min_duration_s,
            "acceptance_max_blind_interval_ms": acceptance_max_blind_interval_ms,
            "acceptance_gap_metric": acceptance_gap_metric,
            "acceptance_gap_ms": round(acceptance_gap, 3),
            "acceptance_met": acceptance_met,
            "recommended_next_parameters": "Run the 2-minute matrix, then select the lowest p95 switch latency without incomplete slices.",
        }
        self._write_json(self.session_dir / "summary.json", summary)
        summary_markdown = render_summary_markdown(summary)
        (self.session_dir / "summary.md").write_text(summary_markdown, encoding="utf-8")
        if self.latest_summary_path:
            self.latest_summary_path.parent.mkdir(parents=True, exist_ok=True)
            self.latest_summary_path.write_text(summary_markdown, encoding="utf-8")
        self.metadata.update(
            {
                "end_utc": datetime.now(timezone.utc).isoformat(),
                "end_local": datetime.now().astimezone().isoformat(),
                "duration_s": round(elapsed_s, 3),
            }
        )
        self._write_json(self.session_dir / "session.json", self.metadata)
        return summary

    def _performance_average(self, name: str) -> float:
        count = self._performance_counts.get(name, 0)
        return round(self._performance_totals.get(name, 0.0) / count, 3) if count else 0.0

    def _performance_max(self, name: str, *, default: float | None = 0.0) -> float | None:
        value = self._performance_maxima.get(name)
        return round(value, 3) if value is not None else default

    @staticmethod
    def _window_percentile(values: Iterable[float], quantile: float) -> float | None:
        window = list(values)
        value = percentile(window, quantile)
        return round(value, 3) if value is not None else None

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def close(self) -> None:
        if self._closed:
            return
        for writer in (self.switch_csv, self.camera_csv, self.performance_csv, self.alerts_csv):
            writer.close()
        self.errors_file.close()
        self._closed = True

    def __enter__(self) -> "AlternatingSessionRecorder":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()


def percentile_summary(values: list[float]) -> dict[str, float | None]:
    return {
        "p50": round(percentile(values, 0.50), 3) if values else None,
        "p95": round(percentile(values, 0.95), 3) if values else None,
        "p99": round(percentile(values, 0.99), 3) if values else None,
        "mean": round(mean(values), 3) if values else None,
    }


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def render_summary_markdown(summary: dict[str, object]) -> str:
    switch_latency = summary["switch_latency_ms"]
    first_latency = summary["first_frame_latency_ms"]
    return f"""# 交替双摄实验摘要

- Session：`{summary['session_id']}`
- 运行时长：{summary['duration_s']} s
- 切换：{summary['successful_switches']}/{summary['switch_count']}，成功率 {summary['switch_success_rate_percent']}%
- 左/右有效采集帧：{summary['left_valid_frames']} / {summary['right_valid_frames']}
- 已选推理帧/跳过旧帧：{summary['selected_inference_frames']} / {summary['skipped_inference_frames']}
- 左/右有效 FPS：{summary['left_effective_fps']} / {summary['right_effective_fps']}
- 纯摄像头切换最大盲区：{summary['capture_only_max_blind_ms']} ms
- 完整处理链端到端最大观测间隔：{summary['end_to_end_max_gap_ms']} ms
- 端到端 p50/p95/p99：{summary['end_to_end_p50_gap_ms']} / {summary['end_to_end_p95_gap_ms']} / {summary['end_to_end_p99_gap_ms']} ms
- 切换延迟 p50/p95/p99：{switch_latency['p50']} / {switch_latency['p95']} / {switch_latency['p99']} ms
- 首帧延迟 p50/p95/p99：{first_latency['p50']} / {first_latency['p95']} / {first_latency['p99']} ms
- STREAMON/STREAMOFF/首帧超时：{summary['streamon_failures']} / {summary['streamoff_failures']} / {summary['first_frame_timeouts']}
- 相机重连：{summary['camera_reconnects']}
- 序列丢帧/USB 错误/相机错误：{summary['dropped_frames']} / {summary['usb_errors']} / {summary['camera_errors']}
- ENOSPC：{summary['enospc_observed']}
- CPU 峰值/平均：{summary['max_cpu_percent']}% / {summary['average_cpu_percent']}%
- RSS 峰值/平均：{summary['max_process_rss_mb']} / {summary['average_process_rss_mb']} MiB
- 内存使用峰值/平均：{summary['max_memory_used_mb']} / {summary['average_memory_used_mb']} MiB
- 温度峰值：{summary['max_temperature_c']}
- 验收指标：{summary['acceptance_gap_metric']} = {summary['acceptance_gap_ms']} ms
- 验收最短时长：{summary['acceptance_min_duration_s']} s
- 验收最大间隔阈值：{summary['acceptance_max_blind_interval_ms']} ms
- 当前验收条件满足：{summary['acceptance_met']}
- 状态变化/心跳：{summary['state_change_count']} / {summary['heartbeat_count']}
- stale/观测安全/相机断开/detector 退出清振：{summary['stale_clear_count']} / {summary['observed_safe_clear_count']} / {summary['camera_disconnect_clear_count']} / {summary['detector_exit_clear_count']}
- 跨时间片确认/单帧跳变抑制/紧急 fast path：{summary['cross_slice_confirmed_count']} / {summary['single_frame_jump_suppressed_count']} / {summary['emergency_fast_path_count']}
- Controller/PWM 相机离线清振闭环确认：{summary['camera_offline_clear_verified']}

时间复用不是同步双摄。纯切换盲区只描述 STREAMOFF/STREAMON/首帧；端到端观测间隔才包含解码、推理、跟踪、风险、overlay、JPEG 和轮回调度。
"""


def read_memory_info() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            name, remainder = line.split(":", 1)
            values[name] = int(remainder.strip().split()[0])
    except (OSError, ValueError, IndexError):
        pass
    return values


def process_rss_mb() -> float:
    try:
        for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    if resource is None:
        return 0.0
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return float(usage) / (1024.0 if platform.system() != "Darwin" else 1024.0 * 1024.0)


def read_temperature_c() -> float | None:
    values: list[float] = []
    for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            value = float(path.read_text(encoding="ascii").strip())
            values.append(value / 1000.0 if value > 1000.0 else value)
        except (OSError, ValueError):
            continue
    return round(max(values), 3) if values else None


def read_first(paths: Iterable[str]) -> str:
    for path_value in paths:
        try:
            return Path(path_value).read_bytes().rstrip(b"\0\n").decode("utf-8", "replace")
        except OSError:
            continue
    return "unknown"


def read_os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"')
    except OSError:
        values["PRETTY_NAME"] = platform.platform()
    return values


def package_version(distribution: str, *, import_name: str | None = None) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        if import_name:
            try:
                module = __import__(import_name)
                return str(getattr(module, "__version__", "installed"))
            except ImportError:
                pass
        return "not installed"


def command_output(argv: list[str]) -> str:
    if shutil.which(argv[0]) is None:
        return f"unavailable: {argv[0]} not installed"
    try:
        completed = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=5.0)
        return (completed.stdout or completed.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unavailable: {exc}"


def git_snapshot() -> dict[str, str]:
    if shutil.which("git") is None:
        return {"branch": "unavailable", "commit": "unavailable", "status": "git not installed"}
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"], check=False, capture_output=True, text=True, timeout=3.0
        ).stdout.strip()
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], check=False, capture_output=True, text=True, timeout=3.0
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--short"], check=False, capture_output=True, text=True, timeout=3.0
        ).stdout.strip()
        return {"branch": branch or "detached", "commit": commit or "unavailable", "status": status or "clean"}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"branch": "unavailable", "commit": "unavailable", "status": str(exc)}
TELEMETRY_WINDOW_SIZE = 20_000
PERFORMANCE_WINDOW_SIZE = 10_000
