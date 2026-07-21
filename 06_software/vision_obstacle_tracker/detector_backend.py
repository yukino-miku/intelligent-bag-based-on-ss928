from __future__ import annotations

from abc import ABC, abstractmethod
import ctypes
from dataclasses import dataclass, replace
import os
from pathlib import Path
import sys
import time
from typing import Any, Iterable


COCO_CLASS_NAMES = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange", "broccoli",
    "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant",
    "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard",
    "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
    "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
)


@dataclass(frozen=True)
class PortableDetection:
    bbox_xyxy: tuple[float, float, float, float]
    confidence: float
    class_id: int
    track_id: int | None = None


@dataclass
class PortableDetectionResult:
    detections: list[PortableDetection]
    names: dict[int, str]
    orig_shape: tuple[int, int]

    @property
    def boxes(self) -> list[PortableDetection]:
        return self.detections

    def translated_y(self, offset_px: float) -> "PortableDetectionResult":
        if offset_px <= 0:
            return self
        self.detections = [
            replace(
                detection,
                bbox_xyxy=(
                    detection.bbox_xyxy[0],
                    detection.bbox_xyxy[1] + offset_px,
                    detection.bbox_xyxy[2],
                    detection.bbox_xyxy[3] + offset_px,
                ),
            )
            for detection in self.detections
        ]
        self.orig_shape = (self.orig_shape[0] + int(round(offset_px)), self.orig_shape[1])
        return self


@dataclass
class _TrackMemory:
    track_id: int
    class_id: int
    bbox_xyxy: tuple[float, float, float, float]
    missed_frames: int = 0


def _bbox_iou(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    ix1 = max(first[0], second[0])
    iy1 = max(first[1], second[1])
    ix2 = min(first[2], second[2])
    iy2 = min(first[3], second[3])
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union > 0.0 else 0.0


def _normalized_center_distance(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    frame_shape: tuple[int, int],
) -> float:
    first_center = ((first[0] + first[2]) * 0.5, (first[1] + first[3]) * 0.5)
    second_center = ((second[0] + second[2]) * 0.5, (second[1] + second[3]) * 0.5)
    distance = ((first_center[0] - second_center[0]) ** 2 + (first_center[1] - second_center[1]) ** 2) ** 0.5
    diagonal = max(1.0, (frame_shape[0] ** 2 + frame_shape[1] ** 2) ** 0.5)
    return distance / diagonal


class IndependentIouTracker:
    """Small dependency-free tracker for SS928 detections.

    It is intentionally side-local. StableTrackIdManager remains the second
    association layer used by the risk pipeline.
    """

    def __init__(
        self,
        *,
        iou_threshold: float = 0.15,
        center_distance_threshold: float = 0.10,
        max_missed_frames: int = 5,
    ) -> None:
        self.iou_threshold = float(iou_threshold)
        self.center_distance_threshold = float(center_distance_threshold)
        self.max_missed_frames = max(1, int(max_missed_frames))
        self._next_track_id = 1
        self._tracks: dict[int, _TrackMemory] = {}

    def update_effective_fps(self, _effective_fps: float) -> None:
        return

    def update(self, result: Any, _image: object = None) -> Any:
        if not isinstance(result, PortableDetectionResult):
            raise TypeError("IndependentIouTracker requires PortableDetectionResult")

        for memory in self._tracks.values():
            memory.missed_frames += 1

        assigned_tracks: set[int] = set()
        tracked_detections: list[PortableDetection] = []
        for detection in sorted(result.detections, key=lambda item: item.confidence, reverse=True):
            best_track_id: int | None = None
            best_score = float("-inf")
            for track_id, memory in self._tracks.items():
                if track_id in assigned_tracks or memory.class_id != detection.class_id:
                    continue
                iou = _bbox_iou(memory.bbox_xyxy, detection.bbox_xyxy)
                center_distance = _normalized_center_distance(
                    memory.bbox_xyxy,
                    detection.bbox_xyxy,
                    result.orig_shape,
                )
                if iou < self.iou_threshold and center_distance > self.center_distance_threshold:
                    continue
                score = iou - center_distance
                if score > best_score:
                    best_score = score
                    best_track_id = track_id

            if best_track_id is None:
                best_track_id = self._next_track_id
                self._next_track_id += 1
                self._tracks[best_track_id] = _TrackMemory(
                    best_track_id,
                    detection.class_id,
                    detection.bbox_xyxy,
                )
            else:
                memory = self._tracks[best_track_id]
                memory.bbox_xyxy = detection.bbox_xyxy
                memory.missed_frames = 0
            assigned_tracks.add(best_track_id)
            tracked_detections.append(replace(detection, track_id=best_track_id))

        self._tracks = {
            track_id: memory
            for track_id, memory in self._tracks.items()
            if memory.missed_frames <= self.max_missed_frames
        }
        result.detections = tracked_detections
        return result


class DetectorBackend(ABC):
    @property
    @abstractmethod
    def names(self) -> object:
        raise NotImplementedError

    @abstractmethod
    def predict(self, frame: object, **kwargs: object) -> object:
        raise NotImplementedError

    @abstractmethod
    def track(self, frame: object, **kwargs: object) -> object:
        raise NotImplementedError

    def close(self) -> None:
        return


class UltralyticsBackend(DetectorBackend):
    def __init__(self, model: Any) -> None:
        self.model = model

    @property
    def names(self) -> object:
        return self.model.names

    def predict(self, frame: object, **kwargs: object) -> object:
        return self.model.predict(frame, **kwargs)

    def track(self, frame: object, **kwargs: object) -> object:
        return self.model.track(frame, **kwargs)


class _TensorInfo(ctypes.Structure):
    _fields_ = [
        ("data_type", ctypes.c_int32),
        ("data_format", ctypes.c_int32),
        ("dim_count", ctypes.c_uint32),
        ("dims", ctypes.c_int64 * 8),
        ("byte_size", ctypes.c_uint64),
    ]


class _NativeSs928Runtime:
    ERROR_BUFFER_SIZE = 1024

    def __init__(self, library_path: Path, model_path: Path, acl_config_path: Path | None) -> None:
        self.library_path = library_path
        self.library = ctypes.CDLL(str(library_path))
        self._configure_signatures()
        self.handle = ctypes.c_void_p()
        error = ctypes.create_string_buffer(self.ERROR_BUFFER_SIZE)
        config_bytes = os.fsencode(acl_config_path) if acl_config_path is not None else None
        status = self.library.smartbag_ss928_create(
            os.fsencode(model_path),
            config_bytes,
            ctypes.byref(self.handle),
            error,
            len(error),
        )
        if status != 0 or not self.handle:
            message = error.value.decode("utf-8", errors="replace") or f"status={status}"
            raise RuntimeError(f"failed to initialize SS928 ACL runtime: {message}")
        try:
            self.input_info = self._tensor_info(self.library.smartbag_ss928_get_input_info)
            self.output_info = self._tensor_info(self.library.smartbag_ss928_get_output_info)
        except Exception:
            self.close()
            raise

    def _configure_signatures(self) -> None:
        library = self.library
        library.smartbag_ss928_create.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_char_p,
            ctypes.c_size_t,
        ]
        library.smartbag_ss928_create.restype = ctypes.c_int
        for name in ("smartbag_ss928_get_input_info", "smartbag_ss928_get_output_info"):
            function = getattr(library, name)
            function.argtypes = [ctypes.c_void_p, ctypes.POINTER(_TensorInfo)]
            function.restype = ctypes.c_int
        library.smartbag_ss928_infer.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_char_p,
            ctypes.c_size_t,
        ]
        library.smartbag_ss928_infer.restype = ctypes.c_int
        library.smartbag_ss928_destroy.argtypes = [ctypes.c_void_p]
        library.smartbag_ss928_destroy.restype = None

    def _tensor_info(self, function: Any) -> _TensorInfo:
        info = _TensorInfo()
        status = function(self.handle, ctypes.byref(info))
        if status != 0:
            raise RuntimeError(f"failed to query SS928 model tensor metadata: status={status}")
        return info

    def infer(self, input_array: Any, output_array: Any) -> float:
        input_array = input_array.copy(order="C") if not input_array.flags.c_contiguous else input_array
        if int(input_array.nbytes) != int(self.input_info.byte_size):
            raise ValueError(
                f"SS928 input byte size mismatch: got {input_array.nbytes}, "
                f"expected {self.input_info.byte_size}"
            )
        if int(output_array.nbytes) < int(self.output_info.byte_size):
            raise ValueError("SS928 output buffer is too small")
        infer_ms = ctypes.c_double()
        error = ctypes.create_string_buffer(self.ERROR_BUFFER_SIZE)
        status = self.library.smartbag_ss928_infer(
            self.handle,
            ctypes.c_void_p(int(input_array.ctypes.data)),
            input_array.nbytes,
            ctypes.c_void_p(int(output_array.ctypes.data)),
            output_array.nbytes,
            ctypes.byref(infer_ms),
            error,
            len(error),
        )
        if status != 0:
            message = error.value.decode("utf-8", errors="replace") or f"status={status}"
            raise RuntimeError(f"SS928 ACL inference failed: {message}")
        return float(infer_ms.value)

    def close(self) -> None:
        if self.handle:
            self.library.smartbag_ss928_destroy(self.handle)
            self.handle = ctypes.c_void_p()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def _default_ss928_library_candidates() -> Iterable[Path]:
    configured = os.environ.get("SS928_OM_RUNTIME_LIBRARY", "").strip()
    if configured:
        yield Path(configured)
    module_dir = Path(__file__).resolve().parent
    yield module_dir / "ss928_backend" / "lib" / "libsmartbag_ss928_acl.so"
    yield Path("/root/smartbag/vision/lib/libsmartbag_ss928_acl.so")
    yield Path("/usr/local/lib/libsmartbag_ss928_acl.so")


def resolve_ss928_runtime_library(explicit_path: str | Path | None = None) -> Path:
    candidates = [Path(explicit_path)] if explicit_path else list(_default_ss928_library_candidates())
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    searched = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(
        "SS928 ACL runtime library was not found. Build the native adapter first. "
        f"Searched: {searched}"
    )


def _acl_numpy_dtype(data_type: int) -> Any:
    import numpy as np

    # ACL_FLOAT=0, ACL_FLOAT16=1, ACL_INT8=2, ACL_INT32=3, ACL_UINT8=4.
    mapping = {0: np.float32, 1: np.float16, 2: np.int8, 3: np.int32, 4: np.uint8}
    if data_type not in mapping:
        raise ValueError(f"unsupported SS928 input data type: {data_type}")
    return mapping[data_type]


def _model_image_shape(info: _TensorInfo) -> tuple[int, int, str]:
    dims = [int(info.dims[index]) for index in range(min(int(info.dim_count), 8))]
    if len(dims) != 4:
        raise ValueError(f"SS928 YOLO input must have 4 dimensions, got {dims}")
    if dims[1] == 3:
        return dims[2], dims[3], "chw"
    if dims[3] == 3:
        return dims[1], dims[2], "hwc"
    raise ValueError(f"cannot determine SS928 YOLO input layout from dimensions {dims}")


def _tensor_dims(info: _TensorInfo) -> tuple[int, ...]:
    return tuple(int(info.dims[index]) for index in range(min(int(info.dim_count), 8)))


def letterbox_for_ss928(
    frame: Any,
    target_height: int,
    target_width: int,
    *,
    layout: str,
    dtype: Any,
) -> tuple[Any, float, float, float]:
    import cv2
    import numpy as np

    source_height, source_width = frame.shape[:2]
    scale = min(target_width / max(source_width, 1), target_height / max(source_height, 1))
    resized_width = max(1, int(round(source_width * scale)))
    resized_height = max(1, int(round(source_height * scale)))
    resized = cv2.resize(frame, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
    pad_x = (target_width - resized_width) / 2.0
    pad_y = (target_height - resized_height) / 2.0
    left = int(round(pad_x - 0.1))
    right = int(round(pad_x + 0.1))
    top = int(round(pad_y - 0.1))
    bottom = int(round(pad_y + 0.1))
    padded = cv2.copyMakeBorder(
        resized,
        top,
        bottom,
        left,
        right,
        cv2.BORDER_CONSTANT,
        value=(114, 114, 114),
    )
    rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
    converted = rgb.astype(dtype, copy=False)
    if np.issubdtype(np.dtype(dtype), np.floating):
        converted = converted / np.array(255.0, dtype=dtype)
    if layout == "chw":
        converted = converted.transpose(2, 0, 1)
    return np.ascontiguousarray(converted), scale, float(left), float(top)


def _class_aware_nms(
    boxes: Any,
    scores: Any,
    class_ids: Any,
    threshold: float,
    max_det: int,
) -> list[int]:
    import numpy as np

    order = np.argsort(scores)[::-1]
    selected: list[int] = []
    while order.size and len(selected) < max_det:
        current = int(order[0])
        selected.append(current)
        if order.size == 1:
            break
        remaining = order[1:]
        xx1 = np.maximum(boxes[current, 0], boxes[remaining, 0])
        yy1 = np.maximum(boxes[current, 1], boxes[remaining, 1])
        xx2 = np.minimum(boxes[current, 2], boxes[remaining, 2])
        yy2 = np.minimum(boxes[current, 3], boxes[remaining, 3])
        intersection = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        current_area = max(0.0, boxes[current, 2] - boxes[current, 0]) * max(
            0.0, boxes[current, 3] - boxes[current, 1]
        )
        remaining_area = np.maximum(0.0, boxes[remaining, 2] - boxes[remaining, 0]) * np.maximum(
            0.0, boxes[remaining, 3] - boxes[remaining, 1]
        )
        union = current_area + remaining_area - intersection
        iou = np.divide(intersection, union, out=np.zeros_like(intersection), where=union > 0.0)
        suppress = (class_ids[remaining] == class_ids[current]) & (iou > threshold)
        order = remaining[~suppress]
    return selected


def decode_yolo_84x8400(
    output: Any,
    *,
    source_shape: tuple[int, int],
    scale: float,
    pad_x: float,
    pad_y: float,
    confidence_threshold: float,
    iou_threshold: float = 0.45,
    class_filter: set[int] | None = None,
    max_det: int = 30,
) -> list[PortableDetection]:
    import numpy as np

    raw = np.asarray(output, dtype=np.float32)
    if raw.size != 84 * 8400:
        raise ValueError(f"SS928 YOLO output must contain 705600 floats, got {raw.size}")
    predictions = raw.reshape(84, 8400)
    class_scores = predictions[4:84]
    class_ids = np.argmax(class_scores, axis=0)
    confidences = class_scores[class_ids, np.arange(class_scores.shape[1])]
    mask = confidences >= float(confidence_threshold)
    if class_filter is not None:
        mask &= np.isin(class_ids, list(class_filter))
    indices = np.nonzero(mask)[0]
    if indices.size == 0:
        return []

    xywh = predictions[:4, indices].T
    boxes = np.empty((indices.size, 4), dtype=np.float32)
    boxes[:, 0] = (xywh[:, 0] - xywh[:, 2] * 0.5 - pad_x) / scale
    boxes[:, 1] = (xywh[:, 1] - xywh[:, 3] * 0.5 - pad_y) / scale
    boxes[:, 2] = (xywh[:, 0] + xywh[:, 2] * 0.5 - pad_x) / scale
    boxes[:, 3] = (xywh[:, 1] + xywh[:, 3] * 0.5 - pad_y) / scale
    source_height, source_width = source_shape
    boxes[:, [0, 2]] = np.clip(boxes[:, [0, 2]], 0.0, float(max(0, source_width - 1)))
    boxes[:, [1, 3]] = np.clip(boxes[:, [1, 3]], 0.0, float(max(0, source_height - 1)))
    filtered_scores = confidences[indices]
    filtered_classes = class_ids[indices]
    selected = _class_aware_nms(
        boxes,
        filtered_scores,
        filtered_classes,
        float(iou_threshold),
        max(1, int(max_det)),
    )
    return [
        PortableDetection(
            bbox_xyxy=tuple(float(value) for value in boxes[index]),
            confidence=float(filtered_scores[index]),
            class_id=int(filtered_classes[index]),
        )
        for index in selected
    ]


class Ss928OmBackend(DetectorBackend):
    def __init__(
        self,
        model_path: str | Path,
        *,
        library_path: str | Path | None = None,
        acl_config_path: str | Path | None = None,
        runtime: Any | None = None,
    ) -> None:
        self.model_path = Path(model_path).resolve()
        if not self.model_path.is_file():
            raise FileNotFoundError(f"SS928 .om model not found: {self.model_path}")
        if self.model_path.suffix.lower() != ".om":
            raise ValueError(f"SS928 backend requires a .om model: {self.model_path}")
        if runtime is None:
            resolved_library = resolve_ss928_runtime_library(library_path)
            config = Path(acl_config_path).resolve() if acl_config_path else None
            runtime = _NativeSs928Runtime(resolved_library, self.model_path, config)
        self.runtime = runtime
        try:
            self._names = {index: name for index, name in enumerate(COCO_CLASS_NAMES)}
            self.input_height, self.input_width, self.input_layout = _model_image_shape(
                runtime.input_info
            )
            self.input_dtype = _acl_numpy_dtype(int(runtime.input_info.data_type))
            if int(runtime.output_info.data_type) != 0:
                raise ValueError(
                    "the verified SS928 YOLO adapter requires FP32 model output, "
                    f"got ACL data type {runtime.output_info.data_type}"
                )
            output_dims = _tensor_dims(runtime.output_info)
            if (
                output_dims != (1, 84, 8400)
                or int(runtime.output_info.byte_size) != 84 * 8400 * 4
            ):
                raise ValueError(
                    "the verified SS928 YOLO adapter requires a 1x84x8400 FP32 output, "
                    f"got dimensions={output_dims} bytes={runtime.output_info.byte_size}"
                )
        except Exception:
            runtime.close()
            raise
        self._tracker = IndependentIouTracker()
        self._output = None
        self._warned_imgsz_mismatch = False
        self.last_preprocess_ms = 0.0
        self.last_npu_ms = 0.0
        self.last_postprocess_ms = 0.0
        self.last_total_ms = 0.0
        print(
            f"Loading SS928 NPU model: {self.model_path} "
            f"input={self.input_layout}:{self.input_height}x{self.input_width} "
            f"output=1x84x8400",
            file=sys.stderr,
            flush=True,
        )

    @property
    def names(self) -> object:
        return self._names

    def predict(self, frame: object, **kwargs: object) -> list[PortableDetectionResult]:
        import numpy as np

        started = time.perf_counter()
        requested_imgsz = kwargs.get("imgsz")
        if (
            not self._warned_imgsz_mismatch
            and requested_imgsz is not None
            and int(requested_imgsz) != self.input_width
        ):
            print(
                f"SS928 .om input is fixed at {self.input_width}x{self.input_height}; "
                f"ignoring requested imgsz={requested_imgsz}",
                file=sys.stderr,
                flush=True,
            )
            self._warned_imgsz_mismatch = True
        preprocess_started = time.perf_counter()
        input_array, scale, pad_x, pad_y = letterbox_for_ss928(
            frame,
            self.input_height,
            self.input_width,
            layout=self.input_layout,
            dtype=self.input_dtype,
        )
        self.last_preprocess_ms = (time.perf_counter() - preprocess_started) * 1000.0
        if self._output is None:
            self._output = np.empty(84 * 8400, dtype=np.float32)
        self.last_npu_ms = self.runtime.infer(input_array, self._output)
        postprocess_started = time.perf_counter()
        raw_classes = kwargs.get("classes")
        class_filter = {int(value) for value in raw_classes} if raw_classes is not None else None
        detections = decode_yolo_84x8400(
            self._output,
            source_shape=tuple(int(value) for value in frame.shape[:2]),
            scale=scale,
            pad_x=pad_x,
            pad_y=pad_y,
            confidence_threshold=float(kwargs.get("conf", 0.25)),
            iou_threshold=float(kwargs.get("iou", 0.45)),
            class_filter=class_filter,
            max_det=int(kwargs.get("max_det", 30)),
        )
        self.last_postprocess_ms = (time.perf_counter() - postprocess_started) * 1000.0
        self.last_total_ms = (time.perf_counter() - started) * 1000.0
        return [
            PortableDetectionResult(
                detections=detections,
                names=self._names,
                orig_shape=tuple(int(value) for value in frame.shape[:2]),
            )
        ]

    def track(self, frame: object, **kwargs: object) -> list[PortableDetectionResult]:
        result = self.predict(frame, **kwargs)[0]
        return [self._tracker.update(result, frame)]

    def close(self) -> None:
        self.runtime.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
