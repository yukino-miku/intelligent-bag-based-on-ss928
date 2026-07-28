from __future__ import annotations

import os
import statistics
import threading
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

try:
    from .models import ClassificationFrame, VehicleDetection
    from .v4l2_snapshot_camera import NativeV4L2Config, NativeV4L2SnapshotCamera
except ImportError:
    from models import ClassificationFrame, VehicleDetection
    from v4l2_snapshot_camera import NativeV4L2Config, NativeV4L2SnapshotCamera


DEFAULT_TARGET_CLASSES = ("bicycle", "motorcycle", "car", "truck", "bus")


@dataclass(frozen=True)
class SnapshotCameraConfig:
    side: str
    device: str
    width: int = 640
    height: int = 480
    fps: float = 10.0
    warmup_frames: int = 2
    capture_frames: int = 1
    first_frame_timeout_ms: int = 1000
    switch_timeout_ms: int = 1000
    rotation_deg: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False


@dataclass(frozen=True)
class SnapshotClassifierConfig:
    imgsz: int = 640
    confidence: float = 0.25
    max_det: int = 30
    snapshot_interval_ms: int = 0
    target_switch_interval_s: float = 0.20
    initial_warmup_frames: int = 2
    switch_warmup_frames: int = 0
    capture_timeout_ms: int = 1000
    streamoff_timeout_ms: int = 1000
    camera_reset_backoff_s: float = 1.0
    target_classes: tuple[str, ...] = DEFAULT_TARGET_CLASSES


class _MetricSeries:
    def __init__(self, limit: int = 512) -> None:
        self.limit = limit
        self.values: list[float] = []

    def add(self, value: float) -> None:
        self.values.append(float(value))
        del self.values[:-self.limit]

    def summary(self) -> dict[str, float | int]:
        if not self.values:
            return {"count": 0, "p50": 0.0, "p95": 0.0, "max": 0.0}
        ordered = sorted(self.values)
        p95_index = min(len(ordered) - 1, max(0, int(round(0.95 * len(ordered) + 0.5)) - 1))
        return {
            "count": len(ordered),
            "p50": round(float(statistics.median(ordered)), 3),
            "p95": round(float(ordered[p95_index]), 3),
            "max": round(float(ordered[-1]), 3),
        }


class OpenCvSnapshotCamera:
    def __init__(self, config: SnapshotCameraConfig) -> None:
        self.config = config
        self._capture = None

    def open(self) -> bool:
        import cv2

        capture = cv2.VideoCapture(self.config.device, cv2.CAP_V4L2)
        if not capture.isOpened():
            capture.release()
            return False
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        capture.set(cv2.CAP_PROP_FPS, self.config.fps)
        self._capture = capture
        return True

    def read(self, timeout_s: float) -> tuple[bool, object | None]:
        if self._capture is None:
            return False, None
        deadline = time.monotonic() + max(0.01, timeout_s)
        while time.monotonic() < deadline:
            ok, frame = self._capture.read()
            if ok and frame is not None:
                return True, frame
            time.sleep(0.005)
        return False, None

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None


def default_snapshot_camera_factory(config: SnapshotCameraConfig) -> object:
    if os.name == "posix" and config.device.startswith("/dev/"):
        return NativeV4L2SnapshotCamera(
            NativeV4L2Config(
                device=config.device,
                width=config.width,
                height=config.height,
                fps=config.fps,
            )
        )
    return OpenCvSnapshotCamera(config)


class AlternatingSnapshotClassifier:
    """Alternately STREAMON one camera, capture a fresh frame, then STREAMOFF."""

    def __init__(
        self,
        backend: object,
        cameras: Sequence[SnapshotCameraConfig],
        config: SnapshotClassifierConfig | None = None,
        *,
        on_frame: Callable[[ClassificationFrame], None] | None = None,
        camera_factory: Callable[[SnapshotCameraConfig], object] | None = None,
    ) -> None:
        if not cameras:
            raise ValueError("at least one snapshot camera is required")
        sides = [camera.side for camera in cameras]
        if len(sides) != len(set(sides)) or any(side not in {"left", "right"} for side in sides):
            raise ValueError("snapshot cameras must have unique left/right sides")
        self.backend = backend
        self.cameras = tuple(cameras)
        self.config = config or SnapshotClassifierConfig()
        self.on_frame = on_frame
        self.camera_factory = camera_factory or default_snapshot_camera_factory
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_id = 0
        self._latest: dict[str, ClassificationFrame] = {}
        self._active_side: str | None = None
        self._state_lock = threading.Lock()
        self._errors: dict[str, str] = {}
        self._camera_instances: dict[str, object] = {}
        self._prepared_sides: set[str] = set()
        self._retry_after_s: dict[str, float] = {}
        self._last_capture_started_s: float | None = None
        self._side_capture_times: dict[str, list[float]] = {side: [] for side in sides}
        self._metrics: dict[str, _MetricSeries] = {
            name: _MetricSeries()
            for name in (
                "streamon_ms",
                "first_frame_ms",
                "capture_ms",
                "streamoff_ms",
                "inference_ms",
                "association_ms",
                "switch_interval_ms",
            )
        }
        self._overruns = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._prepare_cameras()
        self._thread = threading.Thread(target=self._run, name="alternating-snapshot-classifier", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            shutdown_timeout_s = max(
                3.0,
                (self.config.capture_timeout_ms + self.config.streamoff_timeout_ms) / 1000.0 + 1.0,
            )
            self._thread.join(timeout=shutdown_timeout_s)
            if self._thread.is_alive():
                with self._state_lock:
                    self._errors["scheduler"] = (
                        f"classifier thread did not stop within {shutdown_timeout_s:.1f}s; "
                        "camera resources were left open"
                    )
                return
            self._thread = None
        for camera in tuple(self._camera_instances.values()):
            try:
                camera.close()
            except Exception:
                pass
        self._camera_instances.clear()
        self._prepared_sides.clear()
        close = getattr(self.backend, "close", None)
        if callable(close):
            close()

    def run_once(self, side: str) -> ClassificationFrame:
        camera_config = next((item for item in self.cameras if item.side == side), None)
        if camera_config is None:
            raise ValueError(f"camera side is not configured: {side}")
        capture_started = time.monotonic()
        self._record_capture_start(side, capture_started)
        camera = self._camera_for(camera_config)
        frame = None
        captured_mono_s = time.monotonic()
        camera_state = "OFFLINE"
        camera_error = ""
        streamon_latency_ms = 0.0
        first_frame_latency_ms = 0.0
        with self._state_lock:
            if self._active_side is not None:
                raise RuntimeError(f"camera {self._active_side} is already STREAMON")
            self._active_side = side
        try:
            try:
                streamon_started = time.perf_counter()
                opened = self._stream_on(camera)
                streamon_latency_ms = (time.perf_counter() - streamon_started) * 1000.0
                if opened:
                    camera_state = "LIVE"
                    initial = side not in self._prepared_sides
                    warmup_frames = self.config.initial_warmup_frames if initial else self.config.switch_warmup_frames
                    if not hasattr(camera, "stream_on"):
                        warmup_frames = camera_config.warmup_frames
                    read_count = max(1, warmup_frames + camera_config.capture_frames)
                    first_read_started = time.perf_counter()
                    for _index in range(read_count):
                        timeout_ms = self.config.capture_timeout_ms or camera_config.first_frame_timeout_ms
                        ok, candidate = camera.read(timeout_ms / 1000.0)
                        if not ok or candidate is None:
                            frame = None
                            camera_state = "OFFLINE"
                            camera_error = "camera read timed out"
                            break
                        if first_frame_latency_ms == 0.0:
                            first_frame_latency_ms = (time.perf_counter() - first_read_started) * 1000.0
                        frame = candidate
                        captured_mono_s = time.monotonic()
                    self._prepared_sides.add(side)
                else:
                    camera_state = "OFFLINE"
                    camera_error = "camera open failed"
            except Exception as exc:
                camera_state = "OFFLINE"
                camera_error = str(exc)
        finally:
            close_started = time.perf_counter()
            try:
                self._stream_off(camera)
            except Exception as exc:
                camera_state = "OFFLINE"
                camera_error = f"camera close failed: {exc}"
            close_latency_ms = (time.perf_counter() - close_started) * 1000.0
            streamoff_limit_ms = self.config.streamoff_timeout_ms or camera_config.switch_timeout_ms
            if close_latency_ms > streamoff_limit_ms:
                camera_state = "SWITCH_TIMEOUT"
                camera_error = (
                    f"camera STREAMOFF took {close_latency_ms:.1f} ms "
                    f"(limit {streamoff_limit_ms} ms)"
                )
            with self._state_lock:
                self._active_side = None
        capture_latency_ms = (time.monotonic() - capture_started) * 1000.0

        inference_latency_ms = 0.0
        detections: tuple[VehicleDetection, ...] = ()
        width = camera_config.width
        height = camera_config.height
        if frame is not None:
            self._record_successful_capture(side, captured_mono_s)
            frame = _transform_frame(frame, camera_config)
            height, width = frame.shape[:2]
            inference_started = time.perf_counter()
            try:
                result = self.backend.detect(
                    frame,
                    imgsz=self.config.imgsz,
                    conf=self.config.confidence,
                    max_det=self.config.max_det,
                    verbose=False,
                )
                detections = _normalize_detections(result, self.backend.names, self.config.target_classes)
                self._errors.pop(side, None)
            except Exception as exc:
                camera_state = "MODEL_ERROR"
                self._errors[side] = str(exc)
            inference_latency_ms = (time.perf_counter() - inference_started) * 1000.0
        if camera_error:
            self._errors[side] = camera_error
            self._retry_after_s[side] = time.monotonic() + max(0.0, self.config.camera_reset_backoff_s)

        output = ClassificationFrame(
            side=side,
            frame_id=self._frame_id,
            captured_mono_s=captured_mono_s,
            image_width=width,
            image_height=height,
            detections=detections,
            camera_state=camera_state,
            capture_latency_ms=capture_latency_ms,
            inference_latency_ms=inference_latency_ms,
            image=frame,
            streamon_latency_ms=streamon_latency_ms,
            first_frame_latency_ms=first_frame_latency_ms,
            streamoff_latency_ms=close_latency_ms,
        )
        self._frame_id += 1
        with self._state_lock:
            self._latest[side] = output
            self._metrics["streamon_ms"].add(streamon_latency_ms)
            self._metrics["first_frame_ms"].add(first_frame_latency_ms)
            self._metrics["capture_ms"].add(capture_latency_ms)
            self._metrics["streamoff_ms"].add(close_latency_ms)
            self._metrics["inference_ms"].add(inference_latency_ms)
        if self.on_frame is not None:
            self.on_frame(output)
        return output

    def latest(self, side: str) -> ClassificationFrame | None:
        with self._state_lock:
            return self._latest.get(side)

    def status(self) -> dict[str, object]:
        with self._state_lock:
            latest = dict(self._latest)
            active_side = self._active_side
            errors = dict(self._errors)
            capture_times = {side: tuple(values) for side, values in self._side_capture_times.items()}
            metrics = {name: series.summary() for name, series in self._metrics.items()}
            overruns = self._overruns
        now_s = time.monotonic()
        return {
            "active_side": active_side,
            "model_instances": 1,
            "capture_backend": "native_v4l2" if any(hasattr(item, "stream_on") for item in self._camera_instances.values()) else "opencv",
            "target_switch_interval_s": self.config.target_switch_interval_s,
            "overrun_count": overruns,
            "errors": errors,
            "metrics": metrics,
            "sides": {
                side: {
                    "state": frame.camera_state,
                    "frame_id": frame.frame_id,
                    "age_ms": round((now_s - frame.captured_mono_s) * 1000.0, 1),
                    "capture_latency_ms": round(frame.capture_latency_ms, 1),
                    "inference_latency_ms": round(frame.inference_latency_ms, 1),
                    "streamon_latency_ms": round(frame.streamon_latency_ms, 1),
                    "first_frame_latency_ms": round(frame.first_frame_latency_ms, 1),
                    "streamoff_latency_ms": round(frame.streamoff_latency_ms, 1),
                    "association_latency_ms": round(frame.association_latency_ms, 1),
                    "snapshot_fps": round(_recent_fps(capture_times.get(side, ())), 3),
                    "detections": len(frame.detections),
                    "error": errors.get(side, ""),
                }
                for side, frame in latest.items()
            },
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            attempted = False
            for camera in self.cameras:
                if self._stop.is_set():
                    break
                started_s = time.monotonic()
                if started_s < self._retry_after_s.get(camera.side, 0.0):
                    continue
                attempted = True
                try:
                    self.run_once(camera.side)
                except Exception as exc:
                    self._errors[camera.side] = str(exc)
                    self._retry_after_s[camera.side] = time.monotonic() + max(0.0, self.config.camera_reset_backoff_s)
                elapsed_s = time.monotonic() - started_s
                interval_s = max(
                    0.0,
                    self.config.target_switch_interval_s
                    if self.config.target_switch_interval_s > 0.0
                    else self.config.snapshot_interval_ms / 1000.0,
                )
                if elapsed_s > interval_s > 0.0:
                    with self._state_lock:
                        self._overruns += 1
                else:
                    self._stop.wait(max(0.0, interval_s - elapsed_s))
            if not attempted and not self._stop.is_set():
                retry_times = [self._retry_after_s.get(camera.side, 0.0) for camera in self.cameras]
                next_retry_s = min((value for value in retry_times if value > 0.0), default=time.monotonic() + 0.05)
                self._stop.wait(max(0.001, min(0.05, next_retry_s - time.monotonic())))

    def record_association_latency(self, latency_ms: float) -> None:
        with self._state_lock:
            self._metrics["association_ms"].add(latency_ms)

    def _prepare_cameras(self) -> None:
        for config in self.cameras:
            camera = self._camera_for(config)
            prepare = getattr(camera, "prepare", None)
            if callable(prepare):
                try:
                    prepare()
                except Exception as exc:
                    self._errors[config.side] = str(exc)
                    self._retry_after_s[config.side] = time.monotonic() + max(0.0, self.config.camera_reset_backoff_s)

    def _camera_for(self, config: SnapshotCameraConfig) -> object:
        camera = self._camera_instances.get(config.side)
        if camera is None:
            camera = self.camera_factory(config)
            self._camera_instances[config.side] = camera
        return camera

    @staticmethod
    def _stream_on(camera: object) -> bool:
        stream_on = getattr(camera, "stream_on", None)
        if callable(stream_on):
            stream_on()
            return True
        return bool(camera.open())

    @staticmethod
    def _stream_off(camera: object) -> None:
        stream_off = getattr(camera, "stream_off", None)
        if callable(stream_off):
            stream_off()
        else:
            camera.close()

    def _record_capture_start(self, side: str, timestamp_s: float) -> None:
        del side
        with self._state_lock:
            if self._last_capture_started_s is not None:
                self._metrics["switch_interval_ms"].add((timestamp_s - self._last_capture_started_s) * 1000.0)
            self._last_capture_started_s = timestamp_s

    def _record_successful_capture(self, side: str, timestamp_s: float) -> None:
        with self._state_lock:
            values = self._side_capture_times.setdefault(side, [])
            values.append(timestamp_s)
            del values[:-64]


def _transform_frame(frame: object, config: SnapshotCameraConfig) -> object:
    import cv2

    rotation = config.rotation_deg % 360
    if rotation == 90:
        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    elif rotation == 180:
        frame = cv2.rotate(frame, cv2.ROTATE_180)
    elif rotation == 270:
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if config.flip_horizontal and config.flip_vertical:
        frame = cv2.flip(frame, -1)
    elif config.flip_horizontal:
        frame = cv2.flip(frame, 1)
    elif config.flip_vertical:
        frame = cv2.flip(frame, 0)
    return frame


def _normalize_detections(
    result: object,
    names: object,
    target_classes: Sequence[str],
) -> tuple[VehicleDetection, ...]:
    target_set = {str(item) for item in target_classes}
    detections: list[VehicleDetection] = []
    if isinstance(result, Mapping):
        raw_items = result.get("detections", [])
        for detection_id, item in enumerate(raw_items if isinstance(raw_items, Sequence) else []):
            if not isinstance(item, Mapping):
                continue
            class_name = str(item.get("class_name", "unknown"))
            if class_name not in target_set:
                continue
            bbox = item.get("bbox")
            if not isinstance(bbox, Sequence) or len(bbox) != 4:
                continue
            detections.append(
                VehicleDetection.from_bbox(
                    detection_id,
                    int(item.get("class_id", -1)),
                    class_name,
                    float(item.get("confidence", 0.0)),
                    tuple(float(value) for value in bbox),  # type: ignore[arg-type]
                )
            )
        return tuple(detections)

    results = list(result) if isinstance(result, Sequence) else [result]
    if not results:
        return ()
    boxes = getattr(results[0], "boxes", None)
    if boxes is None:
        return ()
    xyxy = boxes.xyxy.cpu().tolist()
    classes = boxes.cls.cpu().tolist()
    confidences = boxes.conf.cpu().tolist()
    for detection_id, (bbox, class_id_value, confidence) in enumerate(zip(xyxy, classes, confidences)):
        class_id = int(class_id_value)
        class_name = _class_name(names, class_id)
        if class_name not in target_set:
            continue
        detections.append(
            VehicleDetection.from_bbox(
                detection_id,
                class_id,
                class_name,
                float(confidence),
                tuple(float(value) for value in bbox),  # type: ignore[arg-type]
            )
        )
    return tuple(detections)


def _class_name(names: object, class_id: int) -> str:
    if isinstance(names, Mapping):
        return str(names.get(class_id, class_id))
    if isinstance(names, Sequence) and not isinstance(names, (str, bytes)) and 0 <= class_id < len(names):
        return str(names[class_id])
    return str(class_id)


def _recent_fps(timestamps: Sequence[float]) -> float:
    if len(timestamps) < 2:
        return 0.0
    elapsed = timestamps[-1] - timestamps[0]
    return (len(timestamps) - 1) / elapsed if elapsed > 1e-6 else 0.0
