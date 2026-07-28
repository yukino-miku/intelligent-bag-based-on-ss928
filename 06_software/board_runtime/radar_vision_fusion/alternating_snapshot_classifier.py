from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

try:
    from .models import ClassificationFrame, VehicleDetection
except ImportError:
    from models import ClassificationFrame, VehicleDetection


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
    target_classes: tuple[str, ...] = DEFAULT_TARGET_CLASSES


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
        self.camera_factory = camera_factory or OpenCvSnapshotCamera
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_id = 0
        self._latest: dict[str, ClassificationFrame] = {}
        self._active_side: str | None = None
        self._state_lock = threading.Lock()
        self._errors: dict[str, str] = {}

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="alternating-snapshot-classifier", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        close = getattr(self.backend, "close", None)
        if callable(close):
            close()

    def run_once(self, side: str) -> ClassificationFrame:
        camera_config = next((item for item in self.cameras if item.side == side), None)
        if camera_config is None:
            raise ValueError(f"camera side is not configured: {side}")
        capture_started = time.perf_counter()
        camera = self.camera_factory(camera_config)
        frame = None
        captured_mono_s = time.monotonic()
        camera_state = "OFFLINE"
        camera_error = ""
        with self._state_lock:
            if self._active_side is not None:
                raise RuntimeError(f"camera {self._active_side} is already STREAMON")
            self._active_side = side
        try:
            try:
                if camera.open():
                    camera_state = "LIVE"
                    read_count = max(1, camera_config.warmup_frames + camera_config.capture_frames)
                    for _index in range(read_count):
                        ok, candidate = camera.read(camera_config.first_frame_timeout_ms / 1000.0)
                        if not ok or candidate is None:
                            frame = None
                            camera_state = "OFFLINE"
                            camera_error = "camera read timed out"
                            break
                        frame = candidate
                        captured_mono_s = time.monotonic()
                else:
                    camera_state = "OFFLINE"
                    camera_error = "camera open failed"
            except Exception as exc:
                camera_state = "OFFLINE"
                camera_error = str(exc)
        finally:
            close_started = time.perf_counter()
            try:
                camera.close()
            except Exception as exc:
                camera_state = "OFFLINE"
                camera_error = f"camera close failed: {exc}"
            close_latency_ms = (time.perf_counter() - close_started) * 1000.0
            if close_latency_ms > camera_config.switch_timeout_ms:
                camera_state = "SWITCH_TIMEOUT"
                camera_error = (
                    f"camera STREAMOFF took {close_latency_ms:.1f} ms "
                    f"(limit {camera_config.switch_timeout_ms} ms)"
                )
            with self._state_lock:
                self._active_side = None
        capture_latency_ms = (time.perf_counter() - capture_started) * 1000.0

        inference_latency_ms = 0.0
        detections: tuple[VehicleDetection, ...] = ()
        width = camera_config.width
        height = camera_config.height
        if frame is not None:
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
        )
        self._frame_id += 1
        with self._state_lock:
            self._latest[side] = output
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
        now_s = time.monotonic()
        return {
            "active_side": active_side,
            "model_instances": 1,
            "sides": {
                side: {
                    "state": frame.camera_state,
                    "frame_id": frame.frame_id,
                    "age_ms": round((now_s - frame.captured_mono_s) * 1000.0, 1),
                    "capture_latency_ms": round(frame.capture_latency_ms, 1),
                    "inference_latency_ms": round(frame.inference_latency_ms, 1),
                    "detections": len(frame.detections),
                    "error": errors.get(side, ""),
                }
                for side, frame in latest.items()
            },
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            cycle_started = time.monotonic()
            for camera in self.cameras:
                if self._stop.is_set():
                    break
                try:
                    self.run_once(camera.side)
                except Exception as exc:
                    self._errors[camera.side] = str(exc)
            interval_s = max(0.0, self.config.snapshot_interval_ms / 1000.0)
            remaining_s = interval_s - (time.monotonic() - cycle_started)
            if remaining_s > 0.0:
                self._stop.wait(remaining_s)


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
