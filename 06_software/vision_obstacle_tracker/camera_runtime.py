from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class FrameSnapshot:
    frame: object
    sequence: int
    captured_at_s: float


class LatestFrameBuffer:
    """A one-frame handoff buffer that never accumulates capture latency."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._snapshot: FrameSnapshot | None = None
        self._sequence = 0
        self._last_taken_sequence = 0
        self._closed = False
        self.overwritten_frames = 0

    def put(self, frame: object, captured_at_s: float | None = None) -> int:
        captured_at_s = time.monotonic() if captured_at_s is None else float(captured_at_s)
        with self._condition:
            if self._closed:
                return self._sequence
            if self._snapshot is not None and self._snapshot.sequence > self._last_taken_sequence:
                self.overwritten_frames += 1
            self._sequence += 1
            self._snapshot = FrameSnapshot(frame, self._sequence, captured_at_s)
            self._condition.notify_all()
            return self._sequence

    def take_latest(self, after_sequence: int = 0, timeout_s: float = 1.0) -> FrameSnapshot | None:
        deadline = time.monotonic() + max(0.0, timeout_s)
        with self._condition:
            while not self._closed and (
                self._snapshot is None or self._snapshot.sequence <= after_sequence
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return None
                self._condition.wait(timeout=remaining)
            if self._snapshot is None or self._snapshot.sequence <= after_sequence:
                return None
            self._last_taken_sequence = max(self._last_taken_sequence, self._snapshot.sequence)
            return self._snapshot

    def peek(self) -> FrameSnapshot | None:
        with self._condition:
            return self._snapshot

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


class LatestOpenCvCameraCapture:
    """Single-owner V4L2 capture with latest-frame delivery and bounded reconnects."""

    def __init__(
        self,
        device: str | int,
        width: int,
        height: int,
        fps: float,
        process_every_n: int = 1,
        inference_fps_limit: float = 0.0,
        max_reconnect_attempts: int = 5,
        reconnect_backoff_s: float = 0.5,
        capture_factory: Callable[[str | int], object] | None = None,
    ) -> None:
        import cv2

        self.device = device
        self.width = int(width)
        self.height = int(height)
        self.requested_fps = max(1.0, float(fps))
        self.process_every_n = max(1, int(process_every_n))
        self.inference_fps_limit = max(0.0, float(inference_fps_limit))
        self.max_reconnect_attempts = max(0, int(max_reconnect_attempts))
        self.reconnect_backoff_s = max(0.05, float(reconnect_backoff_s))
        self._capture_factory = capture_factory or (
            lambda source: cv2.VideoCapture(source, cv2.CAP_ANY)
        )
        self._buffer = LatestFrameBuffer()
        self._state_lock = threading.Lock()
        self._capture_times: deque[float] = deque(maxlen=120)
        self._capture = self._open_capture()
        self._online = bool(self._capture is not None and self._capture.isOpened())
        self._terminal_failure = not self._online and self.max_reconnect_attempts <= 0
        self._closed = False
        self._last_delivered_sequence = 0
        self._last_delivery_s = float("-inf")
        self._source_frames = 0
        self._skipped_frames = 0
        self._actual_width = self.width
        self._actual_height = self.height
        self.reconnect_count = 0
        self.last_error = "" if self._online else f"could not open {self.device}"
        self._reader_thread = threading.Thread(target=self._reader_loop, name=f"camera-{device}", daemon=True)
        self._reader_thread.start()

    def _open_capture(self):
        import cv2

        capture = self._capture_factory(self.device)
        if capture is None:
            return None
        if capture.isOpened():
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            capture.set(cv2.CAP_PROP_FPS, self.requested_fps)
        return capture

    def isOpened(self) -> bool:
        with self._state_lock:
            return self._online or not self._terminal_failure

    def read(self):
        min_interval_s = 1.0 / self.inference_fps_limit if self.inference_fps_limit > 0.0 else 0.0
        while True:
            with self._state_lock:
                terminal = self._terminal_failure
                closed = self._closed
            if terminal or closed:
                return False, None
            wait_s = max(0.0, self._last_delivery_s + min_interval_s - time.monotonic())
            if wait_s > 0.0:
                time.sleep(min(wait_s, 0.2))
                continue
            snapshot = self._buffer.take_latest(self._last_delivered_sequence, timeout_s=1.0)
            if snapshot is None:
                continue
            self._last_delivered_sequence = snapshot.sequence
            self._last_delivery_s = time.monotonic()
            return True, snapshot.frame

    def get(self, prop_id: int) -> float:
        import cv2

        if prop_id == cv2.CAP_PROP_FPS:
            return self.requested_fps
        if prop_id == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self.width)
        if prop_id == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self.height)
        return 0.0

    def status(self) -> dict[str, object]:
        with self._state_lock:
            online = self._online
            reconnect_count = self.reconnect_count
            last_error = self.last_error
            actual_width = self._actual_width
            actual_height = self._actual_height
        snapshot = self._buffer.peek()
        now = time.monotonic()
        capture_fps = 0.0
        if len(self._capture_times) >= 2:
            elapsed = self._capture_times[-1] - self._capture_times[0]
            capture_fps = (len(self._capture_times) - 1) / max(elapsed, 1e-6)
        return {
            "online": online,
            "device": str(self.device),
            "capture_width": actual_width,
            "capture_height": actual_height,
            "capture_fps": round(capture_fps, 2),
            "last_frame_age_ms": round((now - snapshot.captured_at_s) * 1000.0, 1) if snapshot else None,
            "dropped_frames": self._buffer.overwritten_frames + self._skipped_frames,
            "camera_reconnect_count": reconnect_count,
            "last_error": last_error,
        }

    def release(self) -> None:
        with self._state_lock:
            self._closed = True
        self._buffer.close()
        capture = self._capture
        if capture is not None:
            capture.release()
        self._reader_thread.join(timeout=3.0)

    def _reader_loop(self) -> None:
        reconnect_attempt = 0
        while True:
            with self._state_lock:
                if self._closed:
                    break
            capture = self._capture
            if capture is None or not capture.isOpened():
                if reconnect_attempt >= self.max_reconnect_attempts:
                    with self._state_lock:
                        self._online = False
                        self._terminal_failure = True
                    break
                time.sleep(self.reconnect_backoff_s * min(4.0, 2.0**reconnect_attempt))
                reconnect_attempt += 1
                replacement = self._open_capture()
                with self._state_lock:
                    self._capture = replacement
                    self._online = bool(replacement is not None and replacement.isOpened())
                    self.reconnect_count += 1
                    self.last_error = "" if self._online else f"reconnect {reconnect_attempt} failed"
                continue

            ok, frame = capture.read()
            captured_at_s = time.monotonic()
            if not ok or frame is None:
                capture.release()
                with self._state_lock:
                    self._online = False
                    self.last_error = "camera read failed"
                self._capture = None
                continue

            reconnect_attempt = 0
            with self._state_lock:
                self._online = True
                self.last_error = ""
                shape = getattr(frame, "shape", ())
                if len(shape) >= 2:
                    self._actual_height = int(shape[0])
                    self._actual_width = int(shape[1])
            self._source_frames += 1
            self._capture_times.append(captured_at_s)
            if (self._source_frames - 1) % self.process_every_n != 0:
                self._skipped_frames += 1
                continue
            self._buffer.put(frame, captured_at_s)

        self._buffer.close()
