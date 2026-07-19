from __future__ import annotations

import errno
import time
from dataclasses import asdict, dataclass, field
from statistics import mean
from typing import Callable, Protocol

from .v4l2_capture import NegotiatedFormat, RawMjpegFrame, V4l2MjpegDevice


VALID_SIDES = ("left", "right")


class CaptureDevice(Protocol):
    backend: str
    path: str
    negotiated: NegotiatedFormat | None
    streamon_failures: int
    streamoff_failures: int
    read_failures: int

    @property
    def is_streaming(self) -> bool: ...

    def open(self) -> NegotiatedFormat: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def read_frame(self, timeout_s: float) -> RawMjpegFrame: ...

    def close(self) -> None: ...

    def enumerate_formats(self) -> list[dict[str, object]]: ...

    def identity(self) -> dict[str, object]: ...


@dataclass(frozen=True)
class AlternatingCaptureConfig:
    width: int = 640
    height: int = 480
    fps: float = 5.0
    slice_ms: int = 500
    frames_per_slice: int = 4
    inference_frames_per_slice: int = 1
    warmup_frames: int = 2
    frame_timeout_ms: int = 1000
    switch_failure_limit: int = 3
    switch_backoff_ms: int = 200
    max_blind_interval_ms: int = 1200
    camera_reconnect_enabled: bool = True
    camera_reconnect_attempts: int = 5
    camera_reconnect_initial_backoff_s: float = 0.5
    camera_reconnect_max_backoff_s: float = 8.0
    tracker_reset_after_disconnect_s: float = 3.0

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("capture dimensions must be positive")
        if self.fps <= 0:
            raise ValueError("fps must be positive")
        if self.slice_ms <= 0:
            raise ValueError("slice_ms must be positive")
        if self.frames_per_slice <= 0:
            raise ValueError("frames_per_slice must be positive")
        if not 1 <= self.inference_frames_per_slice <= self.frames_per_slice:
            raise ValueError("inference_frames_per_slice must be between 1 and frames_per_slice")
        if self.warmup_frames < 0:
            raise ValueError("warmup_frames must be non-negative")
        if self.frame_timeout_ms <= 0:
            raise ValueError("frame_timeout_ms must be positive")
        if self.switch_failure_limit < 1:
            raise ValueError("switch_failure_limit must be at least 1")
        if self.camera_reconnect_attempts < 1:
            raise ValueError("camera_reconnect_attempts must be at least 1")
        if self.camera_reconnect_initial_backoff_s < 0.0:
            raise ValueError("camera_reconnect_initial_backoff_s must be non-negative")
        if self.camera_reconnect_max_backoff_s < self.camera_reconnect_initial_backoff_s:
            raise ValueError("camera_reconnect_max_backoff_s must be >= initial backoff")


@dataclass(frozen=True)
class AlternatingRiskScheduleConfig:
    normal_slice_ms: int = 500
    risk_slice_ms: int = 700
    minimum_other_side_slice_ms: int = 250
    max_blind_interval_ms: int = 1200
    risk_priority_enabled: bool = True
    risk_level_threshold: int = 2


class RiskPrioritySlicePolicy:
    """Choose bounded slices from stabilized haptic levels, never raw risk."""

    def __init__(self, config: AlternatingRiskScheduleConfig | None = None) -> None:
        self.config = config or AlternatingRiskScheduleConfig()
        self._haptic_level = {side: 0 for side in VALID_SIDES}

    def update_haptic_level(self, side: str, level: int) -> None:
        if side not in VALID_SIDES:
            raise ValueError(f"invalid camera side: {side!r}")
        self._haptic_level[side] = max(0, min(4, int(level)))

    def slice_ms_for(self, side: str) -> int:
        if side not in VALID_SIDES:
            raise ValueError(f"invalid camera side: {side!r}")
        config = self.config
        if not config.risk_priority_enabled:
            return config.normal_slice_ms
        other = "right" if side == "left" else "left"
        side_is_risky = self._haptic_level[side] >= config.risk_level_threshold
        other_is_risky = self._haptic_level[other] >= config.risk_level_threshold
        if side_is_risky and not other_is_risky:
            requested_ms = config.risk_slice_ms
        elif other_is_risky and not side_is_risky:
            requested_ms = config.minimum_other_side_slice_ms
        else:
            requested_ms = config.normal_slice_ms
        return max(1, min(int(requested_ms), int(config.max_blind_interval_ms)))


@dataclass(frozen=True)
class CapturedFrame:
    side: str
    data: bytes
    sequence: int
    captured_at_s: float
    processed_at_s: float
    width: int
    height: int
    pixel_format: str
    warmup: bool = False
    slice_id: int = -1


@dataclass
class SwitchEvent:
    slice_id: int
    switch_index: int
    from_side: str
    to_side: str
    switch_start_monotonic_s: float
    capture_slice_start_s: float | None = None
    capture_slice_end_s: float | None = None
    streamoff_complete_s: float | None = None
    streamoff_start_s: float | None = None
    streamoff_end_s: float | None = None
    streamoff_latency_ms: float = 0.0
    streamon_start_s: float | None = None
    streamon_end_s: float | None = None
    streamon_latency_ms: float = 0.0
    first_frame_s: float | None = None
    first_frame_latency_ms: float | None = None
    warmup_frames_requested: int = 0
    warmup_frames_received: int = 0
    warmup_frames_discarded: int = 0
    valid_frames: int = 0
    slice_duration_ms: float = 0.0
    requested_fps: float = 0.0
    actual_slice_fps: float = 0.0
    left_blind_interval_ms: float | None = None
    right_blind_interval_ms: float | None = None
    connection_state: str = ""
    disconnect_time_s: float | None = None
    offline_detect_latency_ms: float | None = None
    reconnect_start_s: float | None = None
    reconnect_success_s: float | None = None
    reconnect_duration_ms: float | None = None
    tracker_reset: bool | None = None
    first_recovered_frame_latency_ms: float | None = None
    success: bool = False
    error_type: str = ""
    error_message: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SliceResult:
    event: SwitchEvent
    frames: tuple[CapturedFrame, ...]


@dataclass
class _SideState:
    last_frame: CapturedFrame | None = None
    frame_count: int = 0
    dropped_frames: int = 0
    reconnect_count: int = 0
    last_error: str = ""
    capture_times: list[float] = field(default_factory=list)
    connection_state: str = "OFFLINE"
    disconnected_at_s: float | None = None
    reconnect_started_at_s: float | None = None
    recovered_at_s: float | None = None
    recovery_latency_ms: float | None = None
    reopen_attempts: int = 0
    next_reopen_s: float = 0.0
    tracker_reset_required: bool = False
    recovery_event_pending: bool = False
    last_disconnect_s: float | None = None
    last_reconnect_start_s: float | None = None
    last_reconnect_success_s: float | None = None
    last_tracker_reset: bool | None = None


class CameraReconnectPending(RuntimeError):
    pass


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = min(max(float(quantile), 0.0), 1.0) * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    fraction = position - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


class AlternatingV4l2Capture:
    """Round-robin capture that never allows both UVC devices to STREAMON."""

    def __init__(
        self,
        left_device: str,
        right_device: str,
        config: AlternatingCaptureConfig,
        *,
        device_factory: Callable[[str, int, int, float], CaptureDevice] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if left_device == right_device:
            raise ValueError("left and right devices must be different")
        self.config = config
        self.clock = clock
        self.sleep = sleep
        factory = device_factory or (
            lambda path, width, height, fps: V4l2MjpegDevice(path, width, height, fps)
        )
        self._device_factory = factory
        self._device_paths = {"left": left_device, "right": right_device}
        self.devices: dict[str, CaptureDevice] = {
            "left": factory(left_device, config.width, config.height, config.fps),
            "right": factory(right_device, config.width, config.height, config.fps),
        }
        self.side_state = {side: _SideState() for side in VALID_SIDES}
        self.active_side: str | None = None
        self.last_side: str | None = None
        self.switch_count = 0
        self.switch_events: list[SwitchEvent] = []
        self.streamon_failures = 0
        self.streamoff_failures = 0
        self.camera_reopen_failures = 0
        self.warmup_discarded_frames = 0
        self._closed = False
        self._opened = False

    @property
    def backend(self) -> str:
        return next(iter(self.devices.values())).backend

    def open(self) -> dict[str, NegotiatedFormat]:
        negotiated: dict[str, NegotiatedFormat] = {}
        try:
            for side in VALID_SIDES:
                negotiated[side] = self.devices[side].open()
                self.side_state[side].connection_state = "ONLINE"
        except Exception:
            self.close()
            raise
        self._opened = True
        self._assert_single_active()
        return negotiated

    def capture_slice(
        self,
        side: str,
        *,
        slice_ms: int | None = None,
        streamoff_after_slice: bool = False,
    ) -> SliceResult:
        self._require_side(side)
        if self._closed:
            raise RuntimeError("alternating capture is closed")
        if not self._opened:
            self.open()
        event = SwitchEvent(
            slice_id=self.switch_count,
            switch_index=self.switch_count,
            from_side=self.active_side or self.last_side or "none",
            to_side=side,
            switch_start_monotonic_s=self.clock(),
            warmup_frames_requested=self.config.warmup_frames,
            requested_fps=self.config.fps,
        )
        event.capture_slice_start_s = event.switch_start_monotonic_s
        frames: list[CapturedFrame] = []
        slice_started_s = event.switch_start_monotonic_s
        streamon_failures_before = self.streamon_failures
        streamoff_failures_before = self.streamoff_failures
        try:
            self._stop_active(event)
            self._ensure_side_ready(side)
            self._start_side(side, event)
            slice_started_s = self.clock()
            requested_slice_ms = self.config.slice_ms if slice_ms is None else max(1, int(slice_ms))
            deadline_s = slice_started_s + requested_slice_ms / 1000.0
            total_needed = self.config.warmup_frames + self.config.frames_per_slice
            received = 0
            while received < total_needed:
                remaining_s = deadline_s - self.clock()
                if remaining_s <= 0.0:
                    break
                timeout_s = min(self.config.frame_timeout_ms / 1000.0, remaining_s)
                raw = self.devices[side].read_frame(timeout_s)
                processed_at_s = self.clock()
                is_warmup = received < self.config.warmup_frames
                captured = CapturedFrame(
                    side=side,
                    data=raw.data,
                    sequence=raw.sequence,
                    captured_at_s=raw.captured_at_s,
                    processed_at_s=processed_at_s,
                    width=raw.width,
                    height=raw.height,
                    pixel_format=raw.pixel_format,
                    warmup=is_warmup,
                    slice_id=event.slice_id,
                )
                if event.first_frame_s is None:
                    event.first_frame_s = raw.captured_at_s
                    assert event.streamon_end_s is not None
                    event.first_frame_latency_ms = max(0.0, (raw.captured_at_s - event.streamon_end_s) * 1000.0)
                if is_warmup:
                    event.warmup_frames_received += 1
                    event.warmup_frames_discarded += 1
                    self.warmup_discarded_frames += 1
                else:
                    frames.append(captured)
                    self._record_frame(captured)
                received += 1
            event.valid_frames = len(frames)
            elapsed_s = max(self.clock() - slice_started_s, 1e-9)
            event.slice_duration_ms = elapsed_s * 1000.0
            event.actual_slice_fps = len(frames) / elapsed_s
            event.success = len(frames) >= self.config.frames_per_slice
            if not event.success:
                event.error_type = "slice_incomplete"
                event.error_message = (
                    f"received {len(frames)}/{self.config.frames_per_slice} valid frames "
                    f"within {requested_slice_ms} ms"
                )
            if streamoff_after_slice:
                self._stop_active(event, update_from_side=False)
                event.streamoff_complete_s = event.streamoff_end_s
        except Exception as exc:
            if self.streamoff_failures > streamoff_failures_before:
                event.error_type = "streamoff_failure"
            elif isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
                event.error_type = "enospc"
            elif self.streamon_failures > streamon_failures_before:
                event.error_type = "streamon_failure"
            else:
                event.error_type = self._error_type(exc)
            event.error_message = str(exc)
            event.success = False
            self.side_state[side].last_error = str(exc)
            if not isinstance(exc, CameraReconnectPending):
                self._mark_side_failed(side, str(exc))
        finally:
            now_s = self.clock()
            event.capture_slice_end_s = now_s
            event.left_blind_interval_ms = self._frame_age_ms("left", now_s)
            event.right_blind_interval_ms = self._frame_age_ms("right", now_s)
            self._annotate_connection_event(event, side)
            self.switch_count += 1
            self.switch_events.append(event)
            self._assert_single_active()
        return SliceResult(event=event, frames=tuple(frames))

    def _stop_active(self, event: SwitchEvent, *, update_from_side: bool = True) -> None:
        if self.active_side is None:
            return
        previous = self.active_side
        if update_from_side:
            event.from_side = previous
        event.streamoff_start_s = self.clock()
        try:
            self.devices[previous].stop()
        except Exception:
            self.streamoff_failures += 1
            self.active_side = None
            event.streamoff_end_s = self.clock()
            event.streamoff_latency_ms = (event.streamoff_end_s - event.streamoff_start_s) * 1000.0
            self._safe_stop_all()
            raise
        event.streamoff_end_s = self.clock()
        event.streamoff_latency_ms = (event.streamoff_end_s - event.streamoff_start_s) * 1000.0
        self.active_side = None
        self.last_side = previous
        self._assert_single_active()

    def _start_side(self, side: str, event: SwitchEvent) -> None:
        if self.active_side is not None:
            raise RuntimeError("refusing STREAMON while another side is active")
        last_error: Exception | None = None
        for attempt in range(self.config.switch_failure_limit):
            event.streamon_start_s = self.clock()
            try:
                self.devices[side].start()
                event.streamon_end_s = self.clock()
                event.streamon_latency_ms = (event.streamon_end_s - event.streamon_start_s) * 1000.0
                self.active_side = side
                self.last_side = side
                self._assert_single_active()
                return
            except Exception as exc:
                last_error = exc
                self.streamon_failures += 1
                self.active_side = None
                try:
                    self.devices[side].stop()
                except Exception:
                    pass
                if attempt + 1 < self.config.switch_failure_limit:
                    self.sleep(self.config.switch_backoff_ms / 1000.0)
        assert last_error is not None
        raise last_error

    def _record_frame(self, frame: CapturedFrame) -> None:
        state = self.side_state[frame.side]
        state.last_frame = frame
        state.frame_count += 1
        state.capture_times.append(frame.captured_at_s)
        if len(state.capture_times) > 240:
            del state.capture_times[:-240]
        state.last_error = ""

    def _mark_side_failed(self, side: str, message: str) -> None:
        state = self.side_state[side]
        state.connection_state = "READ_FAILURE"
        state.last_error = message
        if state.disconnected_at_s is None:
            state.disconnected_at_s = self.clock()
            state.last_disconnect_s = state.disconnected_at_s
            state.reconnect_started_at_s = None
        if self.active_side == side:
            self.active_side = None
        try:
            self.devices[side].close()
        except Exception:
            pass
        if not self.config.camera_reconnect_enabled:
            state.connection_state = "OFFLINE"
            return
        state.connection_state = "REOPEN_WAIT"
        state.reopen_attempts = 0
        state.next_reopen_s = self.clock() + self.config.camera_reconnect_initial_backoff_s

    def _ensure_side_ready(self, side: str) -> None:
        state = self.side_state[side]
        if state.connection_state in ("ONLINE", "RECOVERED"):
            return
        if state.connection_state == "OFFLINE" and not self.config.camera_reconnect_enabled:
            raise CameraReconnectPending(f"{side} camera is offline")
        now_s = self.clock()
        if now_s < state.next_reopen_s:
            raise CameraReconnectPending(
                f"{side} camera reopen waiting {state.next_reopen_s - now_s:.3f}s"
            )
        if state.reopen_attempts >= self.config.camera_reconnect_attempts:
            state.connection_state = "OFFLINE"
            raise CameraReconnectPending(f"{side} camera reopen attempts exhausted")
        state.connection_state = "REOPENING"
        state.reopen_attempts += 1
        if state.reconnect_started_at_s is None:
            state.reconnect_started_at_s = now_s
        try:
            self.devices[side].open()
        except Exception as exc:
            self.camera_reopen_failures += 1
            state.last_error = str(exc)
            try:
                self.devices[side].close()
            except Exception:
                pass
            if state.reopen_attempts >= self.config.camera_reconnect_attempts:
                state.connection_state = "OFFLINE"
            else:
                state.connection_state = "REOPEN_WAIT"
                backoff_s = min(
                    self.config.camera_reconnect_initial_backoff_s
                    * (2 ** max(0, state.reopen_attempts - 1)),
                    self.config.camera_reconnect_max_backoff_s,
                )
                state.next_reopen_s = self.clock() + backoff_s
            raise CameraReconnectPending(f"{side} camera reopen failed: {exc}") from exc
        recovered_s = self.clock()
        disconnected_s = state.disconnected_at_s
        state.connection_state = "RECOVERED"
        state.reconnect_count += 1
        state.recovered_at_s = recovered_s
        state.recovery_latency_ms = (
            max(0.0, recovered_s - disconnected_s) * 1000.0
            if disconnected_s is not None
            else 0.0
        )
        state.tracker_reset_required = bool(
            disconnected_s is not None
            and recovered_s - disconnected_s >= self.config.tracker_reset_after_disconnect_s
        )
        state.recovery_event_pending = True
        state.last_disconnect_s = disconnected_s
        state.last_reconnect_start_s = state.reconnect_started_at_s
        state.last_reconnect_success_s = recovered_s
        state.last_tracker_reset = state.tracker_reset_required
        state.disconnected_at_s = None
        state.reconnect_started_at_s = None
        state.reopen_attempts = 0
        state.last_error = ""

    def _annotate_connection_event(self, event: SwitchEvent, side: str) -> None:
        state = self.side_state[side]
        event.connection_state = state.connection_state
        event.disconnect_time_s = state.disconnected_at_s
        event.reconnect_start_s = state.reconnect_started_at_s
        if not state.recovery_event_pending:
            return
        event.connection_state = "RECOVERED"
        event.disconnect_time_s = state.last_disconnect_s
        event.reconnect_start_s = state.last_reconnect_start_s
        event.reconnect_success_s = state.last_reconnect_success_s
        event.reconnect_duration_ms = state.recovery_latency_ms
        event.tracker_reset = state.last_tracker_reset
        if event.first_frame_s is not None and state.last_reconnect_success_s is not None:
            event.first_recovered_frame_latency_ms = max(
                0.0, event.first_frame_s - state.last_reconnect_success_s
            ) * 1000.0
            state.recovery_event_pending = False
            state.connection_state = "ONLINE"

    def consume_tracker_reset_required(self, side: str) -> bool:
        self._require_side(side)
        required = self.side_state[side].tracker_reset_required
        self.side_state[side].tracker_reset_required = False
        return required

    def latest_frame(self, side: str) -> CapturedFrame | None:
        self._require_side(side)
        return self.side_state[side].last_frame

    def status(self, now_s: float | None = None) -> dict[str, object]:
        now_s = self.clock() if now_s is None else float(now_s)
        latencies = [event.streamoff_latency_ms + event.streamon_latency_ms for event in self.switch_events]
        next_side = "right" if (self.active_side or self.last_side) == "left" else "left"
        return {
            "active_camera": self.active_side,
            "next_camera": next_side,
            "switch_index": max(0, self.switch_count - 1),
            "switch_count": self.switch_count,
            "last_switch_latency_ms": round(latencies[-1], 3) if latencies else None,
            "average_switch_latency_ms": round(mean(latencies), 3) if latencies else None,
            "p95_switch_latency_ms": round(percentile(latencies, 0.95) or 0.0, 3) if latencies else None,
            "left_blind_interval_ms": self._frame_age_ms("left", now_s),
            "right_blind_interval_ms": self._frame_age_ms("right", now_s),
            "left_last_frame_age_ms": self._frame_age_ms("left", now_s),
            "right_last_frame_age_ms": self._frame_age_ms("right", now_s),
            "streamon_failures": self.streamon_failures,
            "streamoff_failures": self.streamoff_failures,
            "camera_reopen_failures": self.camera_reopen_failures,
            "warmup_discarded_frames": self.warmup_discarded_frames,
            "backend": self.backend,
            "left_effective_fps": self._effective_fps("left"),
            "right_effective_fps": self._effective_fps("right"),
            "left_online": self.side_state["left"].connection_state in ("ONLINE", "RECOVERED"),
            "right_online": self.side_state["right"].connection_state in ("ONLINE", "RECOVERED"),
            "left_connection_state": self.side_state["left"].connection_state,
            "right_connection_state": self.side_state["right"].connection_state,
            "left_reconnect_count": self.side_state["left"].reconnect_count,
            "right_reconnect_count": self.side_state["right"].reconnect_count,
            "left_recovery_latency_ms": self.side_state["left"].recovery_latency_ms,
            "right_recovery_latency_ms": self.side_state["right"].recovery_latency_ms,
            "left_last_error": self.side_state["left"].last_error,
            "right_last_error": self.side_state["right"].last_error,
        }

    def _effective_fps(self, side: str) -> float:
        times = self.side_state[side].capture_times
        if len(times) < 2:
            return 0.0
        return round((len(times) - 1) / max(times[-1] - times[0], 1e-9), 3)

    def _frame_age_ms(self, side: str, now_s: float) -> float | None:
        frame = self.side_state[side].last_frame
        return round(max(0.0, now_s - frame.captured_at_s) * 1000.0, 3) if frame else None

    def _assert_single_active(self) -> None:
        active_devices = [side for side, device in self.devices.items() if device.is_streaming]
        if len(active_devices) > 1:
            self._safe_stop_all()
            raise RuntimeError(f"safety invariant violated: simultaneous STREAMON {active_devices}")
        expected = active_devices[0] if active_devices else None
        if expected != self.active_side:
            self.active_side = expected

    def _safe_stop_all(self) -> None:
        for side in VALID_SIDES:
            try:
                self.devices[side].stop()
            except Exception:
                pass
        self.active_side = None

    @staticmethod
    def _require_side(side: str) -> None:
        if side not in VALID_SIDES:
            raise ValueError(f"invalid camera side: {side!r}")

    @staticmethod
    def _error_type(exc: Exception) -> str:
        if isinstance(exc, CameraReconnectPending):
            return "camera_reopen_wait"
        if isinstance(exc, TimeoutError):
            return "first_frame_timeout"
        if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
            return "enospc"
        if isinstance(exc, OSError):
            return f"oserror_{exc.errno}"
        return type(exc).__name__

    def close(self) -> None:
        if self._closed:
            return
        self._safe_stop_all()
        for device in self.devices.values():
            try:
                device.close()
            except Exception:
                pass
        self.active_side = None
        self._closed = True

    def __enter__(self) -> "AlternatingV4l2Capture":
        self.open()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()
