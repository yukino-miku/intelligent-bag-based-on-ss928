from __future__ import annotations

import argparse
import csv
import os
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path

from alert_output import AlertJsonlEmitter
from camera_runtime import LatestOpenCvCameraCapture
from camera_source import FfmpegCameraConfig, FfmpegMjpegCameraCapture
from calibration import (
    CameraCalibration,
    CameraExtrinsics,
    calibration_from_mapping,
    estimate_ground_point_from_bbox,
    load_calibration_file,
)
from detector_backend import DetectorBackend, Ss928OmBackend, UltralyticsBackend
from risk_model import MotionPattern, RiskAssessment, RiskLevel, RiskModel, corridor_zone_name, motion_pattern_name, warning_action_for_level
from vision_core import DetectionObservation, StableTrackIdManager, TrackState, TrackedObject, compute_observation_quality, format_overlay_label, parse_target_classes, should_keep_class
from video_stream_server import DetectorVideoServer


WINDOW_NAME = "YOLO Tracking Distance Speed"
_LOG_PREFIX = ""


RUNTIME_PROFILES = {
    "realtime": {
        "width": 960,
        "height": 540,
        "fps": 30.0,
        "imgsz": 512,
        "conf": 0.03,
        "max_det": 50,
        "inference_fps_limit": 0.0,
        "process_every_n": 1,
    },
    "cpu_demo": {
        "width": 960,
        "height": 540,
        "fps": 30.0,
        "imgsz": 640,
        "conf": 0.05,
        "max_det": 40,
        "inference_fps_limit": 0.0,
        "process_every_n": 1,
    },
    "balanced": {
        "width": 1280,
        "height": 720,
        "fps": 30.0,
        "imgsz": 1024,
        "conf": 0.02,
        "max_det": 50,
        "inference_fps_limit": 0.0,
        "process_every_n": 1,
    },
    "quality": {
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "imgsz": 1024,
        "conf": 0.02,
        "max_det": 50,
        "inference_fps_limit": 0.0,
        "process_every_n": 1,
    },
    "board_cpu": {
        "width": 640,
        "height": 480,
        "fps": 30.0,
        "imgsz": 416,
        "conf": 0.06,
        "max_det": 30,
        "inference_fps_limit": 0.0,
        "process_every_n": 1,
    },
    "board_dual_balanced": {
        "width": 640,
        "height": 480,
        "fps": 30.0,
        "imgsz": 512,
        "conf": 0.05,
        "max_det": 40,
        "inference_fps_limit": 8.0,
        "process_every_n": 1,
    },
}


def eprint(message: str) -> None:
    prefix = f"[{_LOG_PREFIX}] " if _LOG_PREFIX else ""
    print(prefix + message, file=sys.stderr, flush=True)


@dataclass(frozen=True)
class InferenceFrame:
    image: object
    y_offset_px: int = 0


@dataclass(frozen=True)
class FrameVisualizationPlan:
    should_draw_for_output: bool
    should_show_window: bool
    should_draw_for_stream: bool = False

    @property
    def should_draw_overlay(self) -> bool:
        return self.should_draw_for_output or self.should_show_window or self.should_draw_for_stream


@dataclass(frozen=True)
class EgoMotionEstimate:
    magnitude_px: float = 0.0
    direction_consistency: float = 0.0
    quality_flags: tuple[str, ...] = ()


class SelfObjectFilter:
    SELF_LIKE_CLASSES = {"bicycle", "motorcycle", "person"}

    def __init__(self, bottom_ratio: float = 0.92, enabled: bool = True, fixed_history_frames: int = 5) -> None:
        self.bottom_ratio = min(max(bottom_ratio, 0.0), 0.99)
        self.enabled = enabled
        self.fixed_history_frames = max(2, fixed_history_frames)
        self._history_by_track_id: dict[int, deque[tuple[float, float, float]]] = {}

    def apply(self, targets: list[TrackedObject], frame_shape) -> list[TrackedObject]:
        height = float(frame_shape[0]) if frame_shape else 0.0
        width = float(frame_shape[1]) if frame_shape and len(frame_shape) > 1 else 0.0
        if height <= 0.0 or width <= 0.0:
            return targets

        active_track_ids = {target.track_id for target in targets}
        for stale_id in list(self._history_by_track_id):
            if stale_id not in active_track_ids:
                del self._history_by_track_id[stale_id]

        return [self._with_self_object_diagnostics(target, width, height) for target in targets]

    def _with_self_object_diagnostics(self, target: TrackedObject, width: float, height: float) -> TrackedObject:
        x1, y1, x2, y2 = target.bbox_xyxy
        bbox_width = max(0.0, x2 - x1)
        bbox_height = max(0.0, y2 - y1)
        bbox_area_ratio = (bbox_width * bbox_height) / max(width * height, 1.0)
        bbox_bottom_ratio = min(max(y2 / height, 0.0), 1.5)
        truncated_edges = self._truncated_edges(x1, y1, x2, y2, width, height)
        score, fixed_bottom = self._self_object_score(
            target,
            width,
            height,
            bbox_area_ratio,
            bbox_bottom_ratio,
            bbox_height,
            truncated_edges,
        )

        ignored_reason = getattr(target, "ignored_reason", "")
        if self.enabled and score >= 0.80 and (
            "bottom" in truncated_edges or fixed_bottom or bbox_bottom_ratio >= self.bottom_ratio
        ):
            ignored_reason = "self_object_bottom_foreground"
        elif not self.enabled:
            ignored_reason = ""

        return replace(
            target,
            ignored_reason=ignored_reason,
            self_object_score=score,
            bbox_bottom_ratio=bbox_bottom_ratio,
            bbox_truncated_edges="|".join(truncated_edges),
        )

    @staticmethod
    def _truncated_edges(
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        width: float,
        height: float,
    ) -> tuple[str, ...]:
        margin_x = max(1.0, width * 0.005)
        margin_y = max(1.0, height * 0.005)
        edges: list[str] = []
        if x1 <= margin_x:
            edges.append("left")
        if y1 <= margin_y:
            edges.append("top")
        if x2 >= width - margin_x:
            edges.append("right")
        if y2 >= height - margin_y:
            edges.append("bottom")
        return tuple(edges)

    def _self_object_score(
        self,
        target: TrackedObject,
        width: float,
        height: float,
        bbox_area_ratio: float,
        bbox_bottom_ratio: float,
        bbox_height: float,
        truncated_edges: tuple[str, ...],
    ) -> tuple[float, bool]:
        if target.class_name not in self.SELF_LIKE_CLASSES:
            return 0.0, False

        x1, _y1, x2, y2 = target.bbox_xyxy
        bottom_zone_top = self.bottom_ratio * height
        bottom_overlap_px = max(0.0, min(y2, height) - max(target.bbox_xyxy[1], bottom_zone_top))
        bottom_overlap_ratio = bottom_overlap_px / max(bbox_height, 1.0)
        score = 0.0
        if "bottom" in truncated_edges and bbox_bottom_ratio >= self.bottom_ratio:
            score = max(score, 0.85)
        if bottom_overlap_ratio >= 0.60 and bbox_bottom_ratio >= self.bottom_ratio:
            score = max(score, 0.75)
        if bbox_area_ratio >= 0.14 and bbox_bottom_ratio >= self.bottom_ratio:
            score = max(score, 0.80)

        center_x_ratio = ((x1 + x2) * 0.5) / max(width, 1.0)
        history = self._history_by_track_id.setdefault(target.track_id, deque(maxlen=self.fixed_history_frames))
        history.append((center_x_ratio, bbox_bottom_ratio, bbox_area_ratio))
        fixed_bottom = False
        if len(history) >= self.fixed_history_frames:
            center_values = [value[0] for value in history]
            bottom_values = [value[1] for value in history]
            area_values = [value[2] for value in history]
            fixed_bottom = (
                min(bottom_values) >= self.bottom_ratio
                and max(center_values) - min(center_values) <= 0.04
                and max(bottom_values) - min(bottom_values) <= 0.03
                and max(area_values) - min(area_values) <= 0.05
            )
            if fixed_bottom:
                score = max(score, 0.82)
        return min(score, 1.0), fixed_bottom


class PitchController:
    def __init__(self, initial_pitch_deg: float, step_deg: float = 0.25, smoothing: float = 1.0) -> None:
        self.target_pitch_deg = initial_pitch_deg
        self.current_pitch_deg = initial_pitch_deg
        self.step_deg = max(step_deg, 0.0)
        self.smoothing = min(max(smoothing, 0.0), 1.0)

    def adjust(self, delta_steps: int) -> float:
        self.target_pitch_deg += delta_steps * self.step_deg
        self.current_pitch_deg = self._next_pitch()
        return self.current_pitch_deg

    def update(self) -> float:
        self.current_pitch_deg = self._next_pitch()
        return self.current_pitch_deg

    def _next_pitch(self) -> float:
        if self.smoothing >= 1.0:
            return self.target_pitch_deg
        return self.current_pitch_deg * (1.0 - self.smoothing) + self.target_pitch_deg * self.smoothing


class EgoMotionEstimator:
    def __init__(
        self,
        mode: str = "light",
        max_corners: int = 120,
        quality_level: float = 0.01,
        min_distance: int = 12,
        light_max_dimension_px: int = 320,
    ) -> None:
        self.mode = mode
        self.max_corners = max_corners
        self.quality_level = quality_level
        self.min_distance = min_distance
        self.light_max_dimension_px = light_max_dimension_px
        self._previous_gray = None

    def update(self, frame) -> EgoMotionEstimate:
        import cv2
        import numpy as np

        if self.mode == "off":
            self._previous_gray = None
            return EgoMotionEstimate(quality_flags=("disabled",))

        if self.mode == "light":
            height, width = frame.shape[:2]
            max_dimension = max(height, width)
            if max_dimension > self.light_max_dimension_px:
                scale = self.light_max_dimension_px / max_dimension
                frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self._previous_gray is None:
            self._previous_gray = gray
            return EgoMotionEstimate(quality_flags=("first_frame",))

        points = cv2.goodFeaturesToTrack(
            self._previous_gray,
            maxCorners=self.max_corners,
            qualityLevel=self.quality_level,
            minDistance=self.min_distance,
        )
        if points is None or len(points) < 12:
            self._previous_gray = gray
            return EgoMotionEstimate(quality_flags=("insufficient_features",))

        next_points, status, _error = cv2.calcOpticalFlowPyrLK(self._previous_gray, gray, points, None)
        self._previous_gray = gray
        if next_points is None or status is None:
            return EgoMotionEstimate(quality_flags=("flow_failed",))

        valid = status.reshape(-1) == 1
        if int(valid.sum()) < 8:
            return EgoMotionEstimate(quality_flags=("insufficient_flow",))

        deltas = next_points.reshape(-1, 2)[valid] - points.reshape(-1, 2)[valid]
        magnitudes = np.linalg.norm(deltas, axis=1)
        median_magnitude = float(np.median(magnitudes))
        image_diagonal_px = float(np.hypot(gray.shape[0], gray.shape[1]))
        normalized_magnitude = median_magnitude / max(image_diagonal_px, 1.0)
        mean_delta = deltas.mean(axis=0)
        direction_consistency = float(np.linalg.norm(mean_delta) / max(float(magnitudes.mean()), 1e-6))
        flags: list[str] = []
        if normalized_magnitude >= 0.030:
            flags.append("strong_ego_motion")
        elif normalized_magnitude >= 0.015:
            flags.append("ego_motion")
        if direction_consistency >= 0.70 and normalized_magnitude >= 0.008:
            flags.append("coherent_flow")
        return EgoMotionEstimate(
            magnitude_px=normalized_magnitude,
            direction_consistency=direction_consistency,
            quality_flags=tuple(flags),
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PC-side YOLO tracking, distance, and speed visualization.")
    parser.add_argument("--source", choices=("camera", "video"), default="camera", help="Input source type.")
    parser.add_argument("--video", help="Video file path when --source video is used.")
    parser.add_argument("--camera-index", type=int, default=1, help="OpenCV camera index. USB Camera is usually 1 on this PC.")
    parser.add_argument("--camera-device", default=None, help="Linux camera device path, for example /dev/video0. Overrides --camera-index/backend.")
    parser.add_argument("--camera-backend", choices=("ffmpeg", "opencv"), default="ffmpeg", help="Live camera backend.")
    parser.add_argument("--camera-name", default="USB Camera", help="DirectShow camera device name for --camera-backend ffmpeg.")
    parser.add_argument("--runtime-profile", choices=tuple(RUNTIME_PROFILES), default="balanced", help="Runtime preset: cpu_demo targets PC CPU demos, board_cpu is the SS928 CPU baseline, and quality favors far-object recognition.")
    parser.add_argument("--width", type=int, default=None, help="Requested camera width. Defaults come from --runtime-profile.")
    parser.add_argument("--height", type=int, default=None, help="Requested camera height. Defaults come from --runtime-profile.")
    parser.add_argument("--fps", "--camera-fps", dest="fps", type=float, default=None, help="Requested camera FPS or fallback video FPS.")
    parser.add_argument("--model", default="yolo11n.pt", help="Ultralytics YOLO model path/name.")
    parser.add_argument("--detector-backend", choices=("ultralytics", "ss928_om"), default="ultralytics", help="Detection backend. ss928_om uses the board ACL runtime and a compatible .om model.")
    parser.add_argument("--ss928-runtime-library", default=None, help="Path to libsmartbag_ss928_acl.so. Defaults to the deployed board location or SS928_OM_RUNTIME_LIBRARY.")
    parser.add_argument("--ss928-acl-config", default=None, help="Optional SS928 ACL JSON configuration passed to aclInit().")
    parser.add_argument("--tracker", default="vehicle_botsort.yaml", help="Ultralytics tracker config, for example vehicle_botsort.yaml.")
    parser.add_argument("--conf", type=float, default=None, help="YOLO confidence threshold. Lower values detect farther/smaller objects.")
    parser.add_argument("--imgsz", type=int, default=None, help="YOLO inference image size. Defaults come from --runtime-profile.")
    parser.add_argument("--max-det", type=int, default=None, help="Maximum detections per frame passed to YOLO.")
    parser.add_argument("--export-openvino", action="store_true", help="Export --model to OpenVINO format, then use the exported model for CPU inference.")
    parser.add_argument("--prefer-openvino", action="store_true", help="Prefer an existing OpenVINO export next to a .pt model without exporting automatically.")
    parser.add_argument("--target-classes", default="car,bicycle,motorcycle,bus,truck", help="Comma-separated COCO class names to display, or all.")
    parser.add_argument("--roi-top-ratio", type=float, default=0.0, help="Crop this top fraction of each frame before YOLO inference. 0 keeps full-frame inference.")
    parser.add_argument("--self-mask-bottom-ratio", type=float, default=0.92, help="Ignore self-like bottom foreground boxes that touch the lower frame edge above this image-height ratio.")
    parser.add_argument("--disable-self-object-filter", action="store_true", help="Disable bottom foreground self-object filtering while keeping bbox diagnostics in CSV.")
    parser.add_argument("--device", default=None, help="Ultralytics device, for example cpu, 0, cuda:0. Default: auto.")
    parser.add_argument("--camera-height", type=float, default=1.2, help="Camera height above ground in meters. Default approximates chest mounting.")
    parser.add_argument("--camera-pitch", type=float, default=5.0, help="Camera downward pitch in degrees. Smaller values increase forward distance.")
    parser.add_argument("--calibration-file", help="Optional JSON/YAML camera calibration file with camera_matrix and dist_coeffs.")
    parser.add_argument("--pitch-adjust-step", type=float, default=0.25, help="Pitch adjustment step in degrees for [ and ] display hotkeys.")
    parser.add_argument("--pitch-smoothing", type=float, default=1.0, help="EMA alpha for runtime pitch updates. 1 applies changes immediately.")
    parser.add_argument("--fov", type=float, default=120.0, help="Camera field of view in degrees.")
    parser.add_argument("--fov-type", choices=("diagonal", "horizontal", "vertical"), default="diagonal", help="How --fov is specified.")
    parser.add_argument("--horizontal-fov", type=float, default=None, help="Legacy override for horizontal FOV in degrees.")
    parser.add_argument("--distance-mode", choices=("fused", "ground", "size"), default="fused", help="Distance estimate mode.")
    parser.add_argument("--size-weight", type=float, default=0.75, help="Fallback/debug vehicle-size weight used only when adaptive fused confidence is unavailable.")
    parser.add_argument("--distance-scale", type=float, default=1.0, help="Multiplier for estimated distances after field calibration.")
    parser.add_argument("--speed-scale", type=float, default=1.0, help="Multiplier for estimated relative speed.")
    parser.add_argument("--speed-window", type=float, default=1.5, help="Seconds of track history used for speed estimation.")
    parser.add_argument("--distance-smoothing", type=float, default=0.35, help="EMA alpha for distance smoothing. 1 disables smoothing.")
    parser.add_argument("--max-speed", type=float, default=40.0, help="Reject velocity spikes above this m/s. 0 disables rejection.")
    parser.add_argument("--enhance", choices=("off", "auto", "clahe"), default="off", help="Optional lightweight contrast enhancement before YOLO.")
    parser.add_argument("--ego-motion-mode", choices=("off", "light", "full"), default="light", help="Estimate camera motion quality with optical flow: off, light downscaled, or full resolution.")
    parser.add_argument("--ego-motion-every-n", type=int, default=5, help="Run ego-motion optical flow every N processed frames. Skipped frames use neutral motion quality.")
    parser.add_argument("--display-scale", type=float, default=1.0, help="Scale display window; inference uses original frame.")
    parser.add_argument("--display-every-n", type=int, default=1, help="Refresh the OpenCV preview every N processed frames. Output video still writes every frame.")
    parser.add_argument("--overlay-verbosity", choices=("minimal", "normal", "debug"), default="normal", help="Overlay label detail level.")
    parser.add_argument("--save-output", help="Optional output MP4 path with overlays.")
    parser.add_argument("--risk-log-csv", help="Optional CSV path for per-track risk debugging logs.")
    parser.add_argument("--side", choices=("auto", "left", "right"), default="auto", help="Alert side mode. auto infers left/right from target ground x; dual-camera deployments use fixed left/right.")
    parser.add_argument("--center-side", choices=("both", "strongest", "left", "right"), default="both", help="How single-camera central targets are routed to haptic sides.")
    parser.add_argument("--side-dead-zone", type=float, default=0.35, help="Single-camera center dead zone in ground x meters.")
    parser.add_argument("--emit-alert-jsonl", action="store_true", help="Emit stabilized haptic vision_alert events to stdout; all diagnostics stay on stderr.")
    parser.add_argument("--alert-min-level", type=int, default=1, help="Minimum stabilized haptic level to emit, 0..4.")
    parser.add_argument("--alert-rate-limit", type=float, default=0.25, help="Minimum seconds between repeated same-side/same-level events.")
    parser.add_argument("--process-every-n", type=int, default=None, help="Deliver every Nth captured camera frame to inference; capture keeps draining the device.")
    parser.add_argument("--inference-fps-limit", type=float, default=None, help="Maximum detector loop FPS for live cameras. 0 disables the limit.")
    parser.add_argument("--camera-reconnect-attempts", type=int, default=5, help="Bounded live-camera reconnect attempts after a read failure.")
    parser.add_argument("--camera-reconnect-backoff", type=float, default=0.5, help="Initial seconds between bounded camera reconnect attempts.")
    parser.add_argument("--stream-bind", default="127.0.0.1", help="Detector-local HTTP bind address. The dual gateway normally proxies it.")
    parser.add_argument("--stream-port", type=int, default=0, help="Detector-local HTTP port. 0 disables video serving.")
    parser.add_argument("--jpeg-stream-width", type=int, default=640, help="Phone/debug JPEG width, independent from inference width.")
    parser.add_argument("--jpeg-stream-height", type=int, default=360, help="Phone/debug JPEG height, independent from inference height.")
    parser.add_argument("--jpeg-quality", type=int, default=70, help="JPEG stream quality from 20 to 95.")
    parser.add_argument("--stream-fps-limit", type=float, default=8.0, help="Maximum per-client MJPEG FPS.")
    parser.add_argument("--stream-access-token", default="", help="Optional detector-local HTTP access token.")
    parser.add_argument("--profile", action="store_true", help="Print sliding-average stage timings once per second.")
    parser.add_argument("--max-frames", type=int, default=0, help="Stop after N processed frames. 0 means no limit.")
    parser.add_argument("--no-display", action="store_true", help="Process without opening an OpenCV window.")
    parser.add_argument("--video-every-frame", action="store_true", help="For video files, process every frame instead of skipping stale frames during preview.")
    args = parser.parse_args()
    return apply_runtime_profile_defaults(args)


def apply_runtime_profile_defaults(args: argparse.Namespace) -> argparse.Namespace:
    profile = RUNTIME_PROFILES[args.runtime_profile]
    for name, value in profile.items():
        if getattr(args, name) is None:
            setattr(args, name, value)
    if not 0.0 <= args.roi_top_ratio < 1.0:
        raise SystemExit("--roi-top-ratio must be >= 0.0 and < 1.0.")
    if not 0.0 < args.self_mask_bottom_ratio < 1.0:
        raise SystemExit("--self-mask-bottom-ratio must be > 0.0 and < 1.0.")
    if args.display_every_n < 1:
        raise SystemExit("--display-every-n must be >= 1.")
    if args.pitch_adjust_step < 0.0:
        raise SystemExit("--pitch-adjust-step must be >= 0.")
    if not 0.0 <= args.pitch_smoothing <= 1.0:
        raise SystemExit("--pitch-smoothing must be between 0 and 1.")
    if args.ego_motion_every_n < 1:
        raise SystemExit("--ego-motion-every-n must be >= 1.")
    if args.side_dead_zone < 0.0:
        raise SystemExit("--side-dead-zone must be >= 0.")
    if not 0 <= args.alert_min_level <= 4:
        raise SystemExit("--alert-min-level must be 0..4.")
    if args.alert_rate_limit < 0.0:
        raise SystemExit("--alert-rate-limit must be >= 0.")
    if args.process_every_n < 1:
        raise SystemExit("--process-every-n must be >= 1.")
    if args.inference_fps_limit < 0.0:
        raise SystemExit("--inference-fps-limit must be >= 0.")
    if args.camera_reconnect_attempts < 0:
        raise SystemExit("--camera-reconnect-attempts must be >= 0.")
    if args.camera_reconnect_backoff <= 0.0:
        raise SystemExit("--camera-reconnect-backoff must be > 0.")
    if not 20 <= args.jpeg_quality <= 95:
        raise SystemExit("--jpeg-quality must be 20..95.")
    if args.stream_port < 0 or args.stream_port > 65535:
        raise SystemExit("--stream-port must be 0..65535.")
    if args.stream_port and args.side not in ("left", "right"):
        raise SystemExit("--stream-port requires a fixed --side left or --side right.")
    return args


def openvino_export_dir_for_model(model_path: str | os.PathLike[str]) -> Path | None:
    path = Path(model_path)
    if path.suffix.lower() != ".pt":
        return None
    return path.with_name(f"{path.stem}_openvino_model")


def model_backend_label(model_path: str | os.PathLike[str]) -> str:
    path = Path(model_path)
    if path.suffix.lower() == ".pt":
        return "PyTorch"
    if path.name.endswith("_openvino_model"):
        return "OpenVINO"
    return path.suffix[1:].upper() if path.suffix else "YOLO"


def select_model_path_for_loading(args: argparse.Namespace) -> tuple[str, str]:
    if args.export_openvino:
        return str(args.model), "PyTorch"

    if args.prefer_openvino:
        openvino_dir = openvino_export_dir_for_model(args.model)
        if openvino_dir is not None and openvino_dir.exists():
            return str(openvino_dir), "OpenVINO"

    return str(args.model), model_backend_label(args.model)


def _model_name_items(model_names) -> list[tuple[int, str]]:
    if model_names is None:
        return []

    raw_items = model_names.items() if isinstance(model_names, dict) else enumerate(model_names)
    items: list[tuple[int, str]] = []
    for class_id, class_name in raw_items:
        try:
            normalized_class_id = int(class_id)
        except (TypeError, ValueError):
            continue
        items.append((normalized_class_id, str(class_name).strip()))
    return sorted(items)


def target_class_ids_from_model_names(model_names, target_classes: set[str] | None) -> list[int] | None:
    if target_classes is None:
        return None
    items = _model_name_items(model_names)
    if not items:
        return None
    return [
        class_id
        for class_id, class_name in items
        if class_name in target_classes
    ]


def crop_frame_for_inference(frame, roi_top_ratio: float) -> InferenceFrame:
    if not 0.0 <= roi_top_ratio < 1.0:
        raise ValueError("roi_top_ratio must be >= 0.0 and < 1.0")
    if roi_top_ratio <= 0.0:
        return InferenceFrame(image=frame, y_offset_px=0)

    height = int(frame.shape[0])
    y_offset = min(max(int(height * roi_top_ratio), 0), max(height - 1, 0))
    if y_offset <= 0:
        return InferenceFrame(image=frame, y_offset_px=0)
    return InferenceFrame(image=frame[y_offset:, :], y_offset_px=y_offset)


def restore_result_boxes_to_full_frame(result, y_offset_px: int):
    if y_offset_px <= 0:
        return result

    translate_y = getattr(result, "translated_y", None)
    if callable(translate_y):
        return translate_y(float(y_offset_px))

    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return result
    try:
        if len(boxes) == 0:
            return result
    except TypeError:
        pass

    data = getattr(boxes, "data", None)
    if data is not None:
        if hasattr(data, "clone"):
            adjusted_data = data.clone()
        elif hasattr(data, "copy"):
            adjusted_data = data.copy()
        else:
            adjusted_data = data
        adjusted_data[:, 1] = adjusted_data[:, 1] + float(y_offset_px)
        adjusted_data[:, 3] = adjusted_data[:, 3] + float(y_offset_px)
        result.boxes = boxes.__class__(adjusted_data, boxes.orig_shape)
        return result

    xyxy = getattr(boxes, "xyxy", None)
    if xyxy is not None:
        xyxy[:, [1, 3]] += float(y_offset_px)
    return result


class _StageTimer:
    def __init__(self, profiler: "StageProfiler", stage_name: str) -> None:
        self.profiler = profiler
        self.stage_name = stage_name
        self.started_at_s: float | None = None

    def __enter__(self):
        if self.profiler.enabled:
            self.started_at_s = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if self.started_at_s is not None:
            self.profiler.record(self.stage_name, time.perf_counter() - self.started_at_s)
        return False


class StageProfiler:
    STAGE_ORDER = (
        "capture",
        "roi/crop",
        "enhance",
        "ego-motion",
        "infer+track",
        "postprocess",
        "risk",
        "draw",
        "display/write",
    )

    def __init__(self, enabled: bool = False, report_interval_s: float = 1.0, max_samples: int = 120) -> None:
        self.enabled = enabled
        self.report_interval_s = max(report_interval_s, 0.1)
        self.max_samples = max(max_samples, 1)
        self._samples_by_stage: dict[str, deque[float]] = {}
        self._last_report_s = time.perf_counter()
        self.last_report_text = ""

    def stage(self, stage_name: str) -> _StageTimer:
        return _StageTimer(self, stage_name)

    def record(self, stage_name: str, elapsed_s: float) -> None:
        if not self.enabled:
            return
        samples = self._samples_by_stage.setdefault(stage_name, deque(maxlen=self.max_samples))
        samples.append(max(0.0, elapsed_s))

    def average_ms(self, stage_name: str) -> float | None:
        samples = self._samples_by_stage.get(stage_name)
        if not samples:
            return None
        return sum(samples) / len(samples) * 1000.0

    def summary_text(self) -> str:
        parts: list[str] = []
        total_ms = 0.0
        for stage_name in self.STAGE_ORDER:
            average_ms = self.average_ms(stage_name)
            if average_ms is None:
                continue
            total_ms += average_ms
            parts.append(f"{stage_name}={average_ms:.1f}ms")
        if not parts:
            return ""
        parts.append(f"total~={total_ms:.1f}ms")
        return "profile avg: " + " | ".join(parts)

    def maybe_report(self, now_s: float | None = None) -> str | None:
        if not self.enabled:
            return None
        now_s = time.perf_counter() if now_s is None else now_s
        if now_s - self._last_report_s < self.report_interval_s:
            return None
        self._last_report_s = now_s
        text = self.summary_text()
        if text:
            self.last_report_text = text
            eprint(text)
        return text

    def maybe_report_with_stream(self, stream_status: dict[str, object] | None = None) -> str | None:
        text = self.maybe_report()
        if text is None or not stream_status:
            return text
        eprint(
            "stream profile: "
            f"jpeg_encode={float(stream_status.get('jpeg_encode_ms', 0.0)):.1f}ms | "
            f"clients={int(stream_status.get('video_client_count', 0))} | "
            f"stream_fps={float(stream_status.get('stream_fps', 0.0)):.1f} | "
            f"dropped={int(stream_status.get('dropped_frames', 0))}"
        )
        return text

    def overlay_text(self) -> str:
        return self.last_report_text if self.enabled else ""


def open_capture(args: argparse.Namespace):
    import cv2

    if args.source == "video":
        if not args.video:
            raise SystemExit("Specify --video PATH when using --source video.")
        if video_should_skip_frames(args):
            capture = RealtimeVideoFileCapture(Path(args.video))
        else:
            capture = cv2.VideoCapture(str(Path(args.video)))
        if not capture.isOpened():
            raise SystemExit(f"Could not open video: {args.video}")
        return capture

    if args.camera_device:
        capture = LatestOpenCvCameraCapture(
            str(args.camera_device),
            args.width,
            args.height,
            args.fps,
            process_every_n=args.process_every_n,
            inference_fps_limit=args.inference_fps_limit,
            max_reconnect_attempts=args.camera_reconnect_attempts,
            reconnect_backoff_s=args.camera_reconnect_backoff,
        )
        if not capture.isOpened():
            raise SystemExit(f"Could not open camera device {args.camera_device}.")
    elif args.camera_backend == "ffmpeg":
        capture = FfmpegMjpegCameraCapture(
            FfmpegCameraConfig(
                device_name=args.camera_name,
                width=args.width,
                height=args.height,
                fps=args.fps,
            )
        )
        if not capture.is_opened():
            raise SystemExit(f"Could not open camera {args.camera_name} with FFmpeg.")
        return capture
    else:
        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
        capture = cv2.VideoCapture(args.camera_index, backend)
        if not capture.isOpened():
            raise SystemExit(f"Could not open camera index {args.camera_index}. Try --camera-index 0 or 1.")

    capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    capture.set(cv2.CAP_PROP_FPS, args.fps)
    return capture


def read_initial_frame(capture, timeout_s: float = 5.0, sleep_s: float = 0.05):
    deadline_s = time.monotonic() + max(timeout_s, 0.0)
    while True:
        ok, frame = capture.read()
        if ok and frame is not None:
            return True, frame
        if time.monotonic() >= deadline_s:
            return False, None
        if sleep_s > 0.0:
            time.sleep(sleep_s)


def create_writer(args: argparse.Namespace, frame_shape: tuple[int, int, int], fps: float):
    import cv2

    if not args.save_output:
        return None
    output_path = Path(args.save_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    height, width = frame_shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, max(1.0, fps), (width, height))
    if not writer.isOpened():
        raise SystemExit(f"Could not open output writer: {output_path}")
    return writer


def create_camera_calibration(args: argparse.Namespace, frame_width: int, frame_height: int) -> CameraCalibration:
    fallback = CameraCalibration(
        image_width=frame_width,
        image_height=frame_height,
        fov_deg=args.fov,
        fov_type=args.fov_type,
        horizontal_fov_deg=args.horizontal_fov,
        camera_height_m=args.camera_height,
        camera_pitch_deg=args.camera_pitch,
        distance_scale=args.distance_scale,
    )
    if not args.calibration_file:
        return fallback

    mapping = load_calibration_file(args.calibration_file)
    calibration = calibration_from_mapping(mapping, fallback)
    calibration = calibration.scaled_to_image_size(frame_width, frame_height)
    eprint(
        "Loaded camera calibration: "
        f"{'intrinsics' if calibration.has_intrinsics else 'FOV fallback'} "
        f"{calibration.image_width}x{calibration.image_height} pitch={calibration.camera_pitch_deg:.2f}"
    )
    return calibration


def create_yolo_model(args: argparse.Namespace, yolo_cls=None):
    if yolo_cls is None:
        from ultralytics import YOLO

        yolo_cls = YOLO

    model_path, backend_label = select_model_path_for_loading(args)
    if args.prefer_openvino and backend_label == "PyTorch":
        openvino_dir = openvino_export_dir_for_model(args.model)
        if openvino_dir is not None and not openvino_dir.exists():
            eprint(
                f"OpenVINO export not found at {openvino_dir}. "
                "Run once with --export-openvino, then rerun with --prefer-openvino."
            )
    if backend_label == "PyTorch" and (args.device is None or str(args.device).lower() == "cpu"):
        eprint(
            "PyTorch CPU inference may be slow. For demos, try "
            "--runtime-profile cpu_demo --imgsz 640 --prefer-openvino."
        )
    eprint(f"Loading {backend_label} model: {model_path}")
    model = yolo_cls(model_path)
    if args.export_openvino:
        exported_model_path = model.export(format="openvino")
        eprint(f"Loading OpenVINO model: {exported_model_path}")
        model = yolo_cls(str(exported_model_path))
    return model


def create_detector_backend(args: argparse.Namespace) -> DetectorBackend:
    if args.detector_backend == "ss928_om":
        return Ss928OmBackend(
            args.model,
            library_path=getattr(args, "ss928_runtime_library", None),
            acl_config_path=getattr(args, "ss928_acl_config", None),
        )
    return UltralyticsBackend(create_yolo_model(args))


def frame_timestamp(args: argparse.Namespace, start_time: float, frame_index: int, fps: float) -> float:
    if args.source == "video":
        return frame_index / max(fps, 1.0)
    return time.monotonic() - start_time


class RiskCsvLogger:
    FIELDNAMES = [
        "frame_index",
        "timestamp_s",
        "track_id",
        "class_name",
        "confidence",
        "observation_quality",
        "distance_m",
        "distance_confidence",
        "ground_distance_m",
        "size_distance_m",
        "ground_confidence",
        "size_confidence",
        "distance_source",
        "quality_flags",
        "ignored_reason",
        "self_object_score",
        "bbox_bottom_ratio",
        "bbox_truncated_edges",
        "x_m",
        "z_m",
        "camera_x_m",
        "camera_z_m",
        "backpack_x_m",
        "backpack_z_m",
        "vx_mps",
        "vz_mps",
        "speed_mps",
        "velocity_confidence",
        "velocity_stability",
        "position_jitter_m",
        "distance_trend_mps",
        "approach_consistency",
        "path_conflict_consistency",
        "ego_motion_magnitude",
        "radial_closing_speed_mps",
        "trajectory_distance_m",
        "cpa_time_s",
        "cpa_distance_m",
        "cpa_valid",
        "moving_away",
        "approaching",
        "path_conflict",
        "will_enter_personal_space",
        "will_enter_warning_corridor",
        "personal_entry_time_s",
        "corridor_entry_time_s",
        "min_future_distance_m",
        "conflict_reason",
        "ttc_s",
        "drac_mps2",
        "motion_pattern",
        "corridor_zone",
        "risk_cap_reason",
        "severity_class",
        "warning_action",
        "warning_time_horizon_s",
        "warning_radius_m",
        "risk_action_reason",
        "trajectory_risk",
        "ttc_risk",
        "drac_risk",
        "closing_risk",
        "static_obstacle_risk",
        "raw_risk_score",
        "raw_risk_level",
        "display_risk_score",
        "display_risk_level",
        "visual_risk_level",
        "haptic_risk_level",
        "stabilizer_pending_level",
        "stabilizer_pending_count",
        "stabilizer_required_frames",
        "stabilizer_reason",
        "observation_interval_s",
        "risk_candidate_duration_s",
        "path_conflict_duration_s",
        "time_since_last_observation_s",
        "effective_side_fps",
        "slice_id",
        "pending_slice_count",
        "required_slices",
        "last_pending_slice_id",
        "confirmed_across_slices",
        "minimum_confirmation_interval_s",
        "fast_path_reason",
    ]

    def __init__(self, path: str | None) -> None:
        self._file = None
        self._writer = None
        if path:
            output_path = Path(path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self._file = output_path.open("w", newline="", encoding="utf-8")
            self._writer = csv.DictWriter(self._file, fieldnames=self.FIELDNAMES)
            self._writer.writeheader()

    def write_frame(
        self,
        frame_index: int,
        targets,
        raw_risk_by_track_id: dict[int, RiskAssessment],
        display_risk_by_track_id: dict[int, RiskAssessment],
        stabilizer_debug_by_track_id: dict[int, "StabilizerDebugInfo"] | None = None,
    ) -> None:
        if self._writer is None:
            return
        stabilizer_debug_by_track_id = stabilizer_debug_by_track_id or {}
        for target in targets:
            raw = raw_risk_by_track_id.get(target.track_id)
            display = display_risk_by_track_id.get(target.track_id)
            debug = stabilizer_debug_by_track_id.get(target.track_id)
            point = target.ground_point
            camera_point = getattr(target, "camera_ground_point", None)
            self._writer.writerow(
                {
                    "frame_index": frame_index,
                    "timestamp_s": f"{target.timestamp_s:.3f}",
                    "track_id": target.track_id,
                    "class_name": target.class_name,
                    "confidence": f"{target.confidence:.3f}",
                    "observation_quality": f"{target.observation_quality:.3f}",
                    "distance_m": _format_optional_float(target.distance_m),
                    "distance_confidence": f"{target.distance_confidence:.3f}",
                    "ground_distance_m": _format_optional_float(target.ground_distance_m),
                    "size_distance_m": _format_optional_float(target.size_distance_m),
                    "ground_confidence": f"{target.ground_confidence:.3f}",
                    "size_confidence": f"{target.size_confidence:.3f}",
                    "distance_source": target.distance_source,
                    "quality_flags": "|".join(target.quality_flags),
                    "ignored_reason": getattr(target, "ignored_reason", ""),
                    "self_object_score": f"{getattr(target, 'self_object_score', 0.0):.3f}",
                    "bbox_bottom_ratio": f"{getattr(target, 'bbox_bottom_ratio', 0.0):.3f}",
                    "bbox_truncated_edges": getattr(target, "bbox_truncated_edges", ""),
                    "x_m": _format_optional_float(point.x_m if point is not None else None),
                    "z_m": _format_optional_float(point.z_m if point is not None else None),
                    "camera_x_m": _format_optional_float(
                        camera_point.x_m if camera_point is not None else None
                    ),
                    "camera_z_m": _format_optional_float(
                        camera_point.z_m if camera_point is not None else None
                    ),
                    "backpack_x_m": _format_optional_float(point.x_m if point is not None else None),
                    "backpack_z_m": _format_optional_float(point.z_m if point is not None else None),
                    "vx_mps": f"{target.vx_mps:.3f}",
                    "vz_mps": f"{target.vz_mps:.3f}",
                    "speed_mps": f"{target.speed_mps:.3f}",
                    "velocity_confidence": f"{target.velocity_confidence:.3f}",
                    "velocity_stability": f"{target.velocity_stability:.3f}",
                    "position_jitter_m": f"{target.position_jitter_m:.3f}",
                    "distance_trend_mps": f"{getattr(target, 'distance_trend_mps', 0.0):.3f}",
                    "approach_consistency": f"{getattr(target, 'approach_consistency', 0.0):.3f}",
                    "path_conflict_consistency": f"{getattr(target, 'path_conflict_consistency', 0.0):.3f}",
                    "ego_motion_magnitude": f"{target.ego_motion_magnitude:.3f}",
                    "radial_closing_speed_mps": _format_optional_float(raw.closing_speed_mps if raw else None),
                    "trajectory_distance_m": _format_optional_float(raw.trajectory_distance_m if raw else None),
                    "cpa_time_s": _format_optional_float(raw.cpa_time_s if raw else None),
                    "cpa_distance_m": _format_optional_float(raw.cpa_distance_m if raw else None),
                    "cpa_valid": "1" if raw and raw.cpa_valid else "0" if raw else "",
                    "moving_away": "1" if raw and raw.moving_away else "0" if raw else "",
                    "approaching": "1" if raw and raw.approaching else "0" if raw else "",
                    "path_conflict": "1" if raw and raw.path_conflict else "0" if raw else "",
                    "will_enter_personal_space": "1" if raw and raw.will_enter_personal_space else "0" if raw else "",
                    "will_enter_warning_corridor": "1" if raw and raw.will_enter_warning_corridor else "0" if raw else "",
                    "personal_entry_time_s": _format_optional_float(raw.personal_entry_time_s if raw else None),
                    "corridor_entry_time_s": _format_optional_float(raw.corridor_entry_time_s if raw else None),
                    "min_future_distance_m": _format_optional_float(raw.min_future_distance_m if raw else None),
                    "conflict_reason": raw.conflict_reason if raw else "",
                    "ttc_s": _format_optional_float(raw.ttc_s if raw else None),
                    "drac_mps2": _format_optional_float(raw.drac_mps2 if raw else None),
                    "motion_pattern": motion_pattern_name(raw.motion_pattern) if raw else "",
                    "corridor_zone": corridor_zone_name(raw.corridor_zone) if raw else "",
                    "risk_cap_reason": raw.risk_cap_reason if raw else "",
                    "severity_class": raw.severity_class if raw else "",
                    "warning_action": raw.warning_action if raw else "",
                    "warning_time_horizon_s": _format_optional_float(raw.warning_time_horizon_s if raw else None),
                    "warning_radius_m": _format_optional_float(raw.warning_radius_m if raw else None),
                    "risk_action_reason": raw.risk_action_reason if raw else "",
                    "trajectory_risk": f"{raw.trajectory_risk:.3f}" if raw else "",
                    "ttc_risk": f"{raw.ttc_risk:.3f}" if raw else "",
                    "drac_risk": f"{raw.drac_risk:.3f}" if raw else "",
                    "closing_risk": f"{raw.closing_risk:.3f}" if raw else "",
                    "static_obstacle_risk": f"{raw.static_obstacle_risk:.3f}" if raw else "",
                    "raw_risk_score": f"{raw.score:.3f}" if raw else "",
                    "raw_risk_level": risk_level_name(raw.level) if raw else "",
                    "display_risk_score": f"{display.score:.3f}" if display else "",
                    "display_risk_level": risk_level_name(display.level) if display else "",
                    "visual_risk_level": risk_level_name(display.visual_level) if display else "",
                    "haptic_risk_level": risk_level_name(display.haptic_level) if display else "",
                    "stabilizer_pending_level": risk_level_name(debug.pending_level) if debug else "",
                    "stabilizer_pending_count": str(debug.pending_count) if debug else "",
                    "stabilizer_required_frames": str(debug.required_frames) if debug else "",
                    "stabilizer_reason": debug.reason if debug else "",
                    "observation_interval_s": _format_optional_float(debug.observation_interval_s if debug else None),
                    "risk_candidate_duration_s": _format_optional_float(debug.risk_candidate_duration_s if debug else None),
                    "path_conflict_duration_s": _format_optional_float(debug.path_conflict_duration_s if debug else None),
                    "time_since_last_observation_s": _format_optional_float(
                        debug.time_since_last_observation_s if debug else None
                    ),
                    "effective_side_fps": _format_optional_float(debug.effective_side_fps if debug else None),
                    "slice_id": str(debug.slice_id) if debug and debug.slice_id is not None else "",
                    "pending_slice_count": str(debug.pending_slice_count) if debug else "",
                    "required_slices": str(debug.required_slices) if debug else "",
                    "last_pending_slice_id": (
                        str(debug.last_pending_slice_id)
                        if debug and debug.last_pending_slice_id is not None
                        else ""
                    ),
                    "confirmed_across_slices": (
                        "1" if debug and debug.confirmed_across_slices else "0" if debug else ""
                    ),
                    "minimum_confirmation_interval_s": _format_optional_float(
                        debug.minimum_confirmation_interval_s if debug else None
                    ),
                    "fast_path_reason": debug.fast_path_reason if debug else "",
                }
            )

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
            self._writer = None


def _format_optional_float(value: float | None) -> str:
    return "" if value is None else f"{value:.3f}"


def ignored_target_assessment(target: TrackedObject) -> RiskAssessment:
    reason = getattr(target, "ignored_reason", "") or "ignored"
    return RiskAssessment(
        track_id=target.track_id,
        score=0.0,
        level=RiskLevel.SAFE,
        ttc_s=None,
        trajectory_distance_m=None,
        drac_mps2=0.0,
        closing_speed_mps=0.0,
        visual_level=RiskLevel.SAFE,
        haptic_level=RiskLevel.SAFE,
        motion_pattern=MotionPattern.STATIC_OR_UNCERTAIN,
        risk_cap_reason=reason,
        warning_action=warning_action_for_level(RiskLevel.SAFE),
        risk_action_reason=reason,
        ignored_reason=reason,
    )


def result_to_observations(
    result,
    timestamp_s: float,
    calibration: CameraCalibration,
    target_classes: set[str] | None,
    distance_mode: str,
    size_weight: float,
    extrinsics: CameraExtrinsics | None = None,
) -> list[DetectionObservation]:
    portable_detections = getattr(result, "detections", None)
    if portable_detections is not None:
        names = result.names
        observations: list[DetectionObservation] = []
        for detection in portable_detections:
            if detection.track_id is None:
                continue
            class_id = int(detection.class_id)
            class_name = names[class_id] if isinstance(names, dict) else names[class_id]
            if not should_keep_class(class_name, target_classes):
                continue
            x1, y1, x2, y2 = [float(value) for value in detection.bbox_xyxy]
            confidence = float(detection.confidence)
            distance_estimate = estimate_ground_point_from_bbox(
                (x1, y1, x2, y2),
                class_name,
                calibration,
                mode=distance_mode,
                size_weight=size_weight,
            )
            camera_ground_point = distance_estimate.point if distance_estimate is not None else None
            ground_point = (
                extrinsics.camera_to_backpack(camera_ground_point)
                if extrinsics is not None and camera_ground_point is not None
                else camera_ground_point
            )
            distance_source = distance_estimate.source if distance_estimate is not None else "unknown"
            distance_confidence = (
                distance_estimate.distance_confidence if distance_estimate is not None else 0.0
            )
            quality_flags = (
                distance_estimate.quality_flags if distance_estimate is not None else ("no_distance",)
            )
            observations.append(
                DetectionObservation(
                    track_id=int(detection.track_id),
                    class_name=class_name,
                    confidence=confidence,
                    bbox_xyxy=(x1, y1, x2, y2),
                    ground_point=ground_point,
                    timestamp_s=timestamp_s,
                    distance_source=distance_source,
                    ground_distance_m=(
                        distance_estimate.ground_distance_m if distance_estimate is not None else None
                    ),
                    size_distance_m=(
                        distance_estimate.size_distance_m if distance_estimate is not None else None
                    ),
                    distance_confidence=distance_confidence,
                    ground_confidence=(
                        distance_estimate.ground_confidence if distance_estimate is not None else 0.0
                    ),
                    size_confidence=(
                        distance_estimate.size_confidence if distance_estimate is not None else 0.0
                    ),
                    quality_flags=quality_flags,
                    observation_quality=compute_observation_quality(
                        detection_confidence=confidence,
                        distance_confidence=distance_confidence,
                        velocity_confidence=0.5,
                        track_age_frames=1,
                        quality_flags=quality_flags,
                    ),
                    camera_ground_point=camera_ground_point,
                )
            )
        return observations

    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return []

    names = result.names
    observations: list[DetectionObservation] = []
    for box in boxes:
        if box.id is None:
            continue

        class_id = int(box.cls[0].item())
        class_name = names[class_id]
        if not should_keep_class(class_name, target_classes):
            continue

        confidence = float(box.conf[0].item())
        x1, y1, x2, y2 = [float(value) for value in box.xyxy[0].tolist()]
        distance_estimate = estimate_ground_point_from_bbox(
            (x1, y1, x2, y2),
            class_name,
            calibration,
            mode=distance_mode,
            size_weight=size_weight,
        )
        camera_ground_point = distance_estimate.point if distance_estimate is not None else None
        ground_point = (
            extrinsics.camera_to_backpack(camera_ground_point)
            if extrinsics is not None and camera_ground_point is not None
            else camera_ground_point
        )
        distance_source = distance_estimate.source if distance_estimate is not None else "unknown"
        distance_confidence = distance_estimate.distance_confidence if distance_estimate is not None else 0.0
        quality_flags = distance_estimate.quality_flags if distance_estimate is not None else ("no_distance",)
        observation_quality = compute_observation_quality(
            detection_confidence=confidence,
            distance_confidence=distance_confidence,
            velocity_confidence=0.5,
            track_age_frames=1,
            quality_flags=quality_flags,
        )
        observations.append(
            DetectionObservation(
                track_id=int(box.id[0].item()),
                class_name=class_name,
                confidence=confidence,
                bbox_xyxy=(x1, y1, x2, y2),
                ground_point=ground_point,
                timestamp_s=timestamp_s,
                distance_source=distance_source,
                ground_distance_m=distance_estimate.ground_distance_m if distance_estimate is not None else None,
                size_distance_m=distance_estimate.size_distance_m if distance_estimate is not None else None,
                distance_confidence=distance_confidence,
                ground_confidence=distance_estimate.ground_confidence if distance_estimate is not None else 0.0,
                size_confidence=distance_estimate.size_confidence if distance_estimate is not None else 0.0,
                quality_flags=quality_flags,
                observation_quality=observation_quality,
                camera_ground_point=camera_ground_point,
            )
        )

    return observations


def risk_color_bgr(level: RiskLevel) -> tuple[int, int, int]:
    return {
        RiskLevel.SAFE: (40, 220, 40),
        RiskLevel.ATTENTION: (0, 255, 255),
        RiskLevel.CAUTION: (0, 191, 255),
        RiskLevel.DANGER: (0, 80, 255),
        RiskLevel.EMERGENCY: (0, 0, 255),
    }[level]


def risk_level_name(level: RiskLevel) -> str:
    return {
        RiskLevel.SAFE: "SAFE",
        RiskLevel.ATTENTION: "ATTENTION",
        RiskLevel.CAUTION: "CAUTION",
        RiskLevel.DANGER: "DANGER",
        RiskLevel.EMERGENCY: "EMERGENCY",
    }[level]


def format_risk_suffix(assessment: RiskAssessment | None, verbosity: str = "normal") -> str:
    if assessment is None:
        return "RiskScore=0.00 SAFE"
    zone = corridor_zone_name(assessment.corridor_zone)
    if verbosity == "minimal":
        return risk_level_name(assessment.level)
    cpa = (
        f" CPA={assessment.cpa_time_s:.1f}s/{assessment.cpa_distance_m:.1f}m"
        if assessment.cpa_time_s is not None and assessment.cpa_distance_m is not None
        else ""
    )
    ttc = f" TTC={assessment.ttc_s:.1f}s" if assessment.ttc_s is not None else ""
    if verbosity == "normal":
        time_metric = cpa if cpa else ttc
        return f"{risk_level_name(assessment.level)} {zone}{time_metric} R={assessment.score:.2f}"
    trajectory = (
        f" TRAJ={assessment.trajectory_distance_m:.1f}m"
        if assessment.trajectory_distance_m is not None
        else ""
    )
    pattern = motion_pattern_name(assessment.motion_pattern)
    cap = f" cap={assessment.risk_cap_reason}" if assessment.risk_cap_reason != "none" else ""
    action = f" action={assessment.risk_action_reason}" if assessment.risk_action_reason != "none" else ""
    severity = f" sev={assessment.severity_class}" if assessment.severity_class else ""
    conflict = f" fc={assessment.conflict_reason}" if assessment.conflict_reason != "none" else ""
    haptic = f" h={risk_level_name(assessment.haptic_level)}"
    ignored = f" ignored={assessment.ignored_reason}" if assessment.ignored_reason else ""
    terms = (
        f" tr={assessment.trajectory_risk:.2f}"
        f" ttcR={assessment.ttc_risk:.2f}"
        f" closeR={assessment.closing_risk:.2f}"
    )
    return f"RiskScore={assessment.score:.2f} {risk_level_name(assessment.level)} {zone} {pattern}{severity}{haptic}{cpa}{ttc}{trajectory}{terms}{action}{conflict}{cap}{ignored}"


@dataclass(frozen=True)
class RiskWarningStabilizerConfig:
    min_confirm_frames_attention: int = 1
    min_confirm_frames_caution: int = 2
    min_confirm_frames_danger: int = 3
    min_confirm_frames_emergency: int = 2
    low_quality_extra_frames: int = 1
    low_quality_threshold: float = 0.55
    high_quality_fast_path_threshold: float = 0.80
    emergency_fast_path_ttc_s: float = 0.80
    emergency_fast_path_distance_m: float = 0.80
    downgrade_hold_frames: int = 2
    low_conflict_consistency_threshold: float = 0.50
    low_approach_consistency_threshold: float = 0.50
    low_conflict_extra_frames: int = 2
    min_confirm_duration_attention_s: float = 0.0
    min_confirm_duration_caution_s: float = 0.0
    min_confirm_duration_danger_s: float = 0.0
    min_confirm_duration_emergency_s: float = 0.0
    low_quality_extra_duration_s: float = 0.0
    min_confirm_slices_caution: int = 1
    min_confirm_slices_danger: int = 1
    min_confirm_slices_emergency: int = 1
    minimum_confirmation_interval_s: float = 0.0
    allow_emergency_single_slice_fast_path: bool = True


@dataclass(frozen=True)
class StabilizerDebugInfo:
    pending_level: RiskLevel = RiskLevel.SAFE
    pending_count: int = 0
    required_frames: int = 0
    reason: str = "none"
    observation_interval_s: float = 0.0
    risk_candidate_duration_s: float = 0.0
    path_conflict_duration_s: float = 0.0
    time_since_last_observation_s: float = 0.0
    effective_side_fps: float = 0.0
    slice_id: int | None = None
    pending_slice_count: int = 0
    required_slices: int = 1
    last_pending_slice_id: int | None = None
    confirmed_across_slices: bool = False
    minimum_confirmation_interval_s: float = 0.0
    fast_path_reason: str = ""


@dataclass
class _RiskDisplayState:
    displayed_level: RiskLevel = RiskLevel.SAFE
    displayed_score: float = 0.0
    pending_level: RiskLevel = RiskLevel.SAFE
    pending_count: int = 0
    downgrade_count: int = 0
    pending_started_s: float | None = None
    path_conflict_started_s: float | None = None
    last_observation_s: float | None = None
    pending_slice_count: int = 0
    last_pending_slice_id: int | None = None


class RiskWarningStabilizer:
    def __init__(self, config: RiskWarningStabilizerConfig | None = None, min_warning_frames: int | None = None) -> None:
        if config is None and min_warning_frames is not None:
            config = RiskWarningStabilizerConfig(
                min_confirm_frames_attention=max(1, min_warning_frames),
                min_confirm_frames_caution=max(1, min_warning_frames),
                min_confirm_frames_danger=max(1, min_warning_frames),
                min_confirm_frames_emergency=max(1, min_warning_frames),
            )
        self.config = config or RiskWarningStabilizerConfig()
        self._state_by_track_id: dict[int, _RiskDisplayState] = {}
        self._debug_by_track_id: dict[int, StabilizerDebugInfo] = {}
        self._single_frame_jump_suppressed_pending = 0

    def stabilize(
        self,
        risk_by_track_id: dict[int, RiskAssessment],
        tracked_objects_by_id: dict[int, object] | None = None,
        observation_s_by_track_id: dict[int, float] | None = None,
        effective_side_fps: float = 0.0,
        slice_id: int | None = None,
    ) -> dict[int, RiskAssessment]:
        tracked_objects_by_id = tracked_objects_by_id or {}
        observation_s_by_track_id = observation_s_by_track_id or {}
        stabilized: dict[int, RiskAssessment] = {}
        active_track_ids = set(risk_by_track_id)

        for track_id, assessment in risk_by_track_id.items():
            state = self._state_by_track_id.setdefault(track_id, _RiskDisplayState())
            target = tracked_objects_by_id.get(track_id)
            observation_quality = float(getattr(target, "observation_quality", 1.0))
            observation_s = float(
                observation_s_by_track_id.get(
                    track_id,
                    getattr(target, "timestamp_s", time.monotonic()),
                )
            )
            observation_interval_s = (
                max(0.0, observation_s - state.last_observation_s)
                if state.last_observation_s is not None
                else 0.0
            )
            if assessment.path_conflict:
                if state.path_conflict_started_s is None:
                    state.path_conflict_started_s = observation_s
            else:
                state.path_conflict_started_s = None
            path_conflict_duration_s = (
                max(0.0, observation_s - state.path_conflict_started_s)
                if state.path_conflict_started_s is not None
                else 0.0
            )
            state.last_observation_s = observation_s

            if (
                state.pending_count == 1
                and state.pending_level >= RiskLevel.CAUTION
                and state.pending_level > state.displayed_level
                and assessment.level <= state.displayed_level
            ):
                self._single_frame_jump_suppressed_pending += 1

            fast_path_reason = self._fast_path_reason(assessment, target)
            if fast_path_reason and self.config.allow_emergency_single_slice_fast_path:
                state.displayed_level = assessment.level
                state.displayed_score = assessment.score
                state.pending_level = assessment.level
                state.pending_count = 0
                state.pending_slice_count = 0
                state.last_pending_slice_id = slice_id
                state.downgrade_count = 0
                self._debug_by_track_id[track_id] = StabilizerDebugInfo(
                    pending_level=assessment.level,
                    pending_count=0,
                    required_frames=1,
                    reason="fast_path",
                    observation_interval_s=observation_interval_s,
                    path_conflict_duration_s=path_conflict_duration_s,
                    time_since_last_observation_s=observation_interval_s,
                    effective_side_fps=effective_side_fps,
                    slice_id=slice_id,
                    pending_slice_count=0,
                    required_slices=1,
                    last_pending_slice_id=slice_id,
                    confirmed_across_slices=True,
                    minimum_confirmation_interval_s=self.config.minimum_confirmation_interval_s,
                    fast_path_reason=fast_path_reason,
                )
                stabilized[track_id] = self._assessment_with_display_level(
                    assessment,
                    state.displayed_level,
                    state.displayed_score,
                )
                continue

            if assessment.level > state.displayed_level:
                display, debug = self._handle_upgrade(
                    state,
                    assessment,
                    observation_quality,
                    target,
                    observation_s,
                    observation_interval_s,
                    path_conflict_duration_s,
                    effective_side_fps,
                    slice_id,
                )
            elif assessment.level < state.displayed_level:
                display, debug = self._handle_downgrade(
                    state,
                    assessment,
                    observation_interval_s,
                    path_conflict_duration_s,
                    effective_side_fps,
                )
            else:
                state.displayed_level = assessment.level
                state.displayed_score = assessment.score
                state.pending_level = assessment.level
                state.pending_count = 0
                state.pending_slice_count = 0
                state.last_pending_slice_id = slice_id
                state.pending_started_s = None
                state.downgrade_count = 0
                display = self._assessment_with_display_level(assessment, assessment.level, assessment.score)
                debug = StabilizerDebugInfo(
                    pending_level=assessment.level,
                    pending_count=0,
                    required_frames=0,
                    reason="same_level",
                    observation_interval_s=observation_interval_s,
                    path_conflict_duration_s=path_conflict_duration_s,
                    time_since_last_observation_s=observation_interval_s,
                    effective_side_fps=effective_side_fps,
                    slice_id=slice_id,
                    last_pending_slice_id=slice_id,
                    confirmed_across_slices=True,
                    minimum_confirmation_interval_s=self.config.minimum_confirmation_interval_s,
                )

            self._debug_by_track_id[track_id] = debug
            stabilized[track_id] = display

        for track_id in list(self._state_by_track_id):
            if track_id not in active_track_ids:
                state = self._state_by_track_id[track_id]
                if (
                    state.pending_count == 1
                    and state.pending_level >= RiskLevel.CAUTION
                    and state.pending_level > state.displayed_level
                ):
                    self._single_frame_jump_suppressed_pending += 1
                del self._state_by_track_id[track_id]
                self._debug_by_track_id.pop(track_id, None)

        return stabilized

    def debug_info_by_track_id(self) -> dict[int, StabilizerDebugInfo]:
        return dict(self._debug_by_track_id)

    def consume_single_frame_jump_suppressed_count(self) -> int:
        count = self._single_frame_jump_suppressed_pending
        self._single_frame_jump_suppressed_pending = 0
        return count

    def _handle_upgrade(
        self,
        state: _RiskDisplayState,
        assessment: RiskAssessment,
        observation_quality: float,
        target,
        observation_s: float,
        observation_interval_s: float,
        path_conflict_duration_s: float,
        effective_side_fps: float,
        slice_id: int | None,
    ) -> tuple[RiskAssessment, StabilizerDebugInfo]:
        if state.pending_level != assessment.level:
            state.pending_level = assessment.level
            state.pending_count = 1
            state.pending_started_s = observation_s
            state.pending_slice_count = 1
            state.last_pending_slice_id = slice_id
        else:
            state.pending_count += 1
            if slice_id is None:
                state.pending_slice_count = state.pending_count
            elif state.last_pending_slice_id != slice_id:
                state.pending_slice_count += 1
                state.last_pending_slice_id = slice_id
        state.downgrade_count = 0

        required_frames = self._required_confirm_frames(assessment, observation_quality, target)
        required_slices = self._required_confirm_slices(assessment)
        pending_started_s = observation_s if state.pending_started_s is None else state.pending_started_s
        candidate_duration_s = max(0.0, observation_s - pending_started_s)
        required_duration_s = max(
            self._required_confirm_duration_s(assessment, observation_quality),
            self.config.minimum_confirmation_interval_s if required_slices > 1 else 0.0,
        )
        confirmed_across_slices = state.pending_slice_count >= required_slices
        if (
            state.pending_count >= required_frames
            and confirmed_across_slices
            and candidate_duration_s >= required_duration_s
        ):
            state.displayed_level = assessment.level
            state.displayed_score = assessment.score
            return self._assessment_with_display_level(assessment, assessment.level, assessment.score), StabilizerDebugInfo(
                pending_level=assessment.level,
                pending_count=state.pending_count,
                required_frames=required_frames,
                reason="upgraded",
                observation_interval_s=observation_interval_s,
                risk_candidate_duration_s=candidate_duration_s,
                path_conflict_duration_s=path_conflict_duration_s,
                time_since_last_observation_s=observation_interval_s,
                effective_side_fps=effective_side_fps,
                slice_id=slice_id,
                pending_slice_count=state.pending_slice_count,
                required_slices=required_slices,
                last_pending_slice_id=state.last_pending_slice_id,
                confirmed_across_slices=confirmed_across_slices,
                minimum_confirmation_interval_s=self.config.minimum_confirmation_interval_s,
            )

        return self._display_assessment_from_state(assessment, state), StabilizerDebugInfo(
            pending_level=assessment.level,
            pending_count=state.pending_count,
            required_frames=required_frames,
            reason="waiting_confirmation",
            observation_interval_s=observation_interval_s,
            risk_candidate_duration_s=candidate_duration_s,
            path_conflict_duration_s=path_conflict_duration_s,
            time_since_last_observation_s=observation_interval_s,
            effective_side_fps=effective_side_fps,
            slice_id=slice_id,
            pending_slice_count=state.pending_slice_count,
            required_slices=required_slices,
            last_pending_slice_id=state.last_pending_slice_id,
            confirmed_across_slices=confirmed_across_slices,
            minimum_confirmation_interval_s=self.config.minimum_confirmation_interval_s,
        )

    def _handle_downgrade(
        self,
        state: _RiskDisplayState,
        assessment: RiskAssessment,
        observation_interval_s: float,
        path_conflict_duration_s: float,
        effective_side_fps: float,
    ) -> tuple[RiskAssessment, StabilizerDebugInfo]:
        state.pending_level = assessment.level
        state.pending_count = 0
        state.pending_slice_count = 0
        state.last_pending_slice_id = None
        state.pending_started_s = None
        state.downgrade_count += 1
        if state.downgrade_count >= self.config.downgrade_hold_frames:
            state.downgrade_count = 0
            state.displayed_level = RiskLevel(max(int(state.displayed_level) - 1, int(assessment.level)))
            state.displayed_score = max(assessment.score, risk_score_for_display_level(state.displayed_level))
            reason = "downgraded"
        else:
            reason = "holding_downgrade"
        return self._display_assessment_from_state(assessment, state), StabilizerDebugInfo(
            pending_level=assessment.level,
            pending_count=state.downgrade_count,
            required_frames=self.config.downgrade_hold_frames,
            reason=reason,
            observation_interval_s=observation_interval_s,
            path_conflict_duration_s=path_conflict_duration_s,
            time_since_last_observation_s=observation_interval_s,
            effective_side_fps=effective_side_fps,
        )

    def _required_confirm_frames(self, assessment: RiskAssessment, observation_quality: float, target=None) -> int:
        level = assessment.level
        if level <= RiskLevel.ATTENTION:
            frames = self.config.min_confirm_frames_attention
        elif level == RiskLevel.CAUTION:
            frames = self.config.min_confirm_frames_caution
        elif level == RiskLevel.DANGER:
            frames = self.config.min_confirm_frames_danger
        else:
            frames = self.config.min_confirm_frames_emergency
        if level > RiskLevel.ATTENTION and observation_quality < self.config.low_quality_threshold:
            frames += self.config.low_quality_extra_frames
        if level > RiskLevel.ATTENTION:
            approach_consistency = float(getattr(target, "approach_consistency", 1.0))
            path_conflict_consistency = float(getattr(target, "path_conflict_consistency", 1.0))
            if (
                not assessment.path_conflict
                or (
                    approach_consistency < self.config.low_approach_consistency_threshold
                    and path_conflict_consistency < self.config.low_conflict_consistency_threshold
                )
            ):
                frames += self.config.low_conflict_extra_frames
        return max(1, frames)

    def _required_confirm_duration_s(self, assessment: RiskAssessment, observation_quality: float) -> float:
        durations = {
            RiskLevel.SAFE: 0.0,
            RiskLevel.ATTENTION: self.config.min_confirm_duration_attention_s,
            RiskLevel.CAUTION: self.config.min_confirm_duration_caution_s,
            RiskLevel.DANGER: self.config.min_confirm_duration_danger_s,
            RiskLevel.EMERGENCY: self.config.min_confirm_duration_emergency_s,
        }
        duration_s = max(0.0, float(durations[assessment.level]))
        if assessment.level > RiskLevel.ATTENTION and observation_quality < self.config.low_quality_threshold:
            duration_s += max(0.0, self.config.low_quality_extra_duration_s)
        return duration_s

    def _required_confirm_slices(self, assessment: RiskAssessment) -> int:
        if assessment.level == RiskLevel.CAUTION:
            return max(1, self.config.min_confirm_slices_caution)
        if assessment.level == RiskLevel.DANGER:
            return max(1, self.config.min_confirm_slices_danger)
        if assessment.level >= RiskLevel.EMERGENCY:
            return max(1, self.config.min_confirm_slices_emergency)
        return 1

    def _is_fast_path(self, assessment: RiskAssessment, target) -> bool:
        return bool(self._fast_path_reason(assessment, target))

    def _fast_path_reason(self, assessment: RiskAssessment, target) -> str:
        distance_m = getattr(target, "distance_m", None)
        observation_quality = float(getattr(target, "observation_quality", 0.0))
        inside_personal_space = distance_m is not None and distance_m <= self.config.emergency_fast_path_distance_m
        high_quality_emergency = observation_quality >= self.config.high_quality_fast_path_threshold
        stable_conflict = (
            bool(getattr(assessment, "path_conflict", False))
            and float(getattr(target, "approach_consistency", 0.0)) >= self.config.low_approach_consistency_threshold
            and float(getattr(target, "path_conflict_consistency", 0.0)) >= self.config.low_conflict_consistency_threshold
        )
        if assessment.level < RiskLevel.EMERGENCY:
            return ""
        if inside_personal_space:
            return "inside_personal_space"
        if (
            stable_conflict
            and high_quality_emergency
            and assessment.ttc_s is not None
            and assessment.ttc_s <= self.config.emergency_fast_path_ttc_s
        ):
            return "high_quality_extreme_ttc"
        if (
            stable_conflict
            and high_quality_emergency
            and assessment.cpa_time_s is not None
            and assessment.cpa_distance_m is not None
            and assessment.cpa_time_s <= self.config.emergency_fast_path_ttc_s
            and assessment.cpa_distance_m <= self.config.emergency_fast_path_distance_m
        ):
            return "high_quality_extreme_cpa"
        return ""

    @staticmethod
    def _assessment_with_display_level(
        assessment: RiskAssessment,
        display_level: RiskLevel,
        display_score: float,
    ) -> RiskAssessment:
        if display_level <= RiskLevel.SAFE:
            haptic_level = RiskLevel.SAFE
        else:
            haptic_level = RiskLevel(min(int(assessment.haptic_level), int(display_level)))
        return replace(
            assessment,
            score=display_score,
            level=display_level,
            visual_level=display_level,
            haptic_level=haptic_level,
            warning_action=warning_action_for_level(haptic_level),
        )

    @classmethod
    def _display_assessment_from_state(cls, assessment: RiskAssessment, state: _RiskDisplayState) -> RiskAssessment:
        if state.displayed_level <= RiskLevel.SAFE:
            return cls._assessment_with_display_level(assessment, RiskLevel.SAFE, 0.0)
        display_score = max(state.displayed_score, risk_score_for_display_level(state.displayed_level))
        return cls._assessment_with_display_level(assessment, state.displayed_level, display_score)


def risk_score_for_display_level(level: RiskLevel) -> float:
    return {
        RiskLevel.SAFE: 0.0,
        RiskLevel.ATTENTION: 0.40,
        RiskLevel.CAUTION: 0.60,
        RiskLevel.DANGER: 0.70,
        RiskLevel.EMERGENCY: 0.80,
    }[level]


def draw_overlay(
    frame,
    tracked_objects,
    fps_text: str,
    source_text: str,
    risk_by_track_id: dict[int, RiskAssessment] | None = None,
    profile_text: str = "",
    overlay_verbosity: str = "normal",
) -> None:
    import cv2

    risk_by_track_id = risk_by_track_id or {}
    for target in tracked_objects:
        x1, y1, x2, y2 = [int(round(value)) for value in target.bbox_xyxy]
        assessment = risk_by_track_id.get(target.track_id)
        color = risk_color_bgr(assessment.level) if assessment is not None else (80, 180, 255)
        thickness = 3 if assessment is not None and assessment.level >= RiskLevel.DANGER else 2
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)

        if target.ground_point is not None:
            foot_x = int(round((x1 + x2) / 2.0))
            foot_y = int(round(y2))
            cv2.circle(frame, (foot_x, foot_y), 5, color, -1)

        label = f"{format_overlay_label(target, overlay_verbosity)} {format_risk_suffix(assessment, overlay_verbosity)}"
        y_label = max(24, y1 - 8)
        cv2.putText(frame, label, (x1, y_label), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)

    cv2.putText(frame, source_text, (24, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(frame, fps_text, (24, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(frame, "q/Esc: exit  Space: pause", (24, 108), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (220, 220, 220), 2, cv2.LINE_AA)
    if profile_text:
        cv2.putText(frame, profile_text[:130], (24, 144), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 2, cv2.LINE_AA)


def maybe_resize_for_display(frame, scale: float):
    import cv2

    if scale <= 0 or abs(scale - 1.0) < 1e-6:
        return frame
    return cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def display_wait_ms(args: argparse.Namespace, capture_fps: float) -> int:
    return 1


def visualization_plan_for_frame(
    processed_frame_index: int,
    display_every_n: int,
    no_display: bool,
    has_writer: bool,
    draw_for_stream: bool = False,
) -> FrameVisualizationPlan:
    if display_every_n < 1:
        raise ValueError("display_every_n must be >= 1")
    should_show_window = not no_display and processed_frame_index % display_every_n == 0
    should_draw_for_output = has_writer
    return FrameVisualizationPlan(
        should_draw_for_output=should_draw_for_output,
        should_show_window=should_show_window,
        should_draw_for_stream=draw_for_stream,
    )


def video_should_skip_frames(args: argparse.Namespace) -> bool:
    return args.source == "video" and not args.video_every_frame and not args.no_display


class RealtimeVideoFileCapture:
    def __init__(self, path: Path) -> None:
        import cv2

        self.path = path
        self._capture = cv2.VideoCapture(str(path))
        self._fps = float(self._capture.get(cv2.CAP_PROP_FPS) or 30.0)
        self._width = float(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0.0)
        self._height = float(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0.0)
        self._frame_count = float(self._capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        self._condition = threading.Condition()
        self._latest_frame = None
        self._latest_sequence = 0
        self._last_delivered_sequence = 0
        self._latest_frame_index = -1
        self.last_frame_index = -1
        self._closed = False
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def isOpened(self) -> bool:
        return self._capture.isOpened()

    def get(self, prop_id: int) -> float:
        import cv2

        if prop_id == cv2.CAP_PROP_FPS:
            return self._fps
        if prop_id == cv2.CAP_PROP_FRAME_WIDTH:
            return self._width
        if prop_id == cv2.CAP_PROP_FRAME_HEIGHT:
            return self._height
        if prop_id == cv2.CAP_PROP_FRAME_COUNT:
            return self._frame_count
        if prop_id == cv2.CAP_PROP_POS_FRAMES:
            return float(max(self.last_frame_index, 0))
        return 0.0

    def read(self):
        with self._condition:
            while self._latest_sequence == self._last_delivered_sequence and not self._closed:
                self._condition.wait(timeout=1.0)

            if self._latest_frame is None or self._latest_sequence == self._last_delivered_sequence:
                return False, None

            self._last_delivered_sequence = self._latest_sequence
            self.last_frame_index = self._latest_frame_index
            return True, self._latest_frame

    def release(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._reader_thread.join(timeout=3.0)
        self._capture.release()

    def _reader_loop(self) -> None:
        frame_interval_s = 1.0 / max(self._fps, 1.0)
        next_frame_time = time.monotonic()
        frame_index = 0

        while True:
            with self._condition:
                if self._closed:
                    break

            ok, frame = self._capture.read()
            if not ok:
                break

            with self._condition:
                self._latest_frame = frame
                self._latest_frame_index = frame_index
                self._latest_sequence += 1
                self._condition.notify_all()

            frame_index += 1
            next_frame_time += frame_interval_s
            sleep_s = next_frame_time - time.monotonic()
            if sleep_s > 0:
                time.sleep(sleep_s)

        with self._condition:
            self._closed = True
            self._condition.notify_all()


def enhance_frame_for_detection(frame, mode: str):
    import cv2

    if mode == "off":
        return frame

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if mode == "auto" and gray.mean() >= 75.0:
        return frame

    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced_l = clahe.apply(l_channel)
    enhanced_lab = cv2.merge((enhanced_l, a_channel, b_channel))
    return cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)


def main() -> None:
    args = parse_args()
    alert_stdout = sys.stdout
    if args.emit_alert_jsonl:
        sys.stdout = sys.stderr
    import cv2

    global _LOG_PREFIX
    _LOG_PREFIX = args.side if args.side in ("left", "right") else ""
    profiler = StageProfiler(enabled=args.profile)
    capture = open_capture(args)
    capture_fps = float(capture.get(cv2.CAP_PROP_FPS) or args.fps or 30.0) if hasattr(capture, "get") else float(args.fps or 30.0)

    with profiler.stage("capture"):
        ok, first_frame = read_initial_frame(capture)
    if not ok:
        raise SystemExit("Input opened but no frame could be read.")

    frame_height, frame_width = first_frame.shape[:2]
    calibration = create_camera_calibration(args, frame_width, frame_height)
    pitch_controller = PitchController(
        initial_pitch_deg=calibration.camera_pitch_deg,
        step_deg=args.pitch_adjust_step,
        smoothing=args.pitch_smoothing,
    )

    writer = create_writer(args, first_frame.shape, capture_fps)
    video_server = None
    if args.stream_port:
        stream_device = (
            str(args.video)
            if args.source == "video"
            else (args.camera_device or str(args.camera_index))
        )
        video_server = DetectorVideoServer(
            side=args.side,
            device=stream_device,
            bind=args.stream_bind,
            port=args.stream_port,
            stream_width=args.jpeg_stream_width,
            stream_height=args.jpeg_stream_height,
            jpeg_quality=args.jpeg_quality,
            stream_fps_limit=args.stream_fps_limit,
            access_token=args.stream_access_token,
            status_provider=capture.status if hasattr(capture, "status") else None,
        )
        video_server.start()
    target_classes = parse_target_classes(args.target_classes)
    detector = create_detector_backend(args)
    target_class_ids = target_class_ids_from_model_names(detector.names, target_classes)
    if target_classes is None:
        eprint("YOLO class prefilter: all classes")
    elif target_class_ids is None:
        eprint("YOLO class prefilter unavailable; using post-processing class filter only.")
    elif target_class_ids:
        eprint(f"YOLO class prefilter IDs: {target_class_ids}")
    else:
        eprint("YOLO class prefilter IDs: none matched; YOLO tracking will receive an empty class filter.")

    track_state = TrackState(
        history_seconds=args.speed_window,
        smoothing_alpha=args.distance_smoothing,
        max_speed_mps=args.max_speed,
        speed_scale=args.speed_scale,
    )
    stable_track_ids = StableTrackIdManager()
    risk_model = RiskModel()
    risk_stabilizer = RiskWarningStabilizer()
    self_object_filter = SelfObjectFilter(
        bottom_ratio=args.self_mask_bottom_ratio,
        enabled=not args.disable_self_object_filter,
    )
    ego_motion_estimator = EgoMotionEstimator(mode=args.ego_motion_mode)
    risk_logger = RiskCsvLogger(args.risk_log_csv)
    alert_emitter = (
        AlertJsonlEmitter(
            alert_stdout,
            fixed_side=args.side,
            min_level=args.alert_min_level,
            rate_limit_s=args.alert_rate_limit,
            dead_zone_m=args.side_dead_zone,
            center_mode=args.center_side,
        )
        if args.emit_alert_jsonl
        else None
    )

    start_time = time.monotonic()
    processed_frames = 0
    source_frame_index = 0
    paused = False
    last_loop = time.monotonic()
    inference_times: deque[float] = deque(maxlen=120)
    current_frame = first_frame

    if not args.no_display:
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)

    while True:
        if args.max_frames and processed_frames >= args.max_frames:
            break

        if not paused:
            if processed_frames == 0:
                frame = current_frame
            else:
                with profiler.stage("capture"):
                    ok, frame = capture.read()
                if not ok:
                    break
            current_frame = frame
            if args.source == "video" and hasattr(capture, "last_frame_index"):
                source_frame_index = max(0, int(capture.last_frame_index))
            elif processed_frames > 0:
                source_frame_index += 1

            timestamp_s = frame_timestamp(args, start_time, source_frame_index, capture_fps)
            calibration = calibration.with_pitch(pitch_controller.update())
            with profiler.stage("roi/crop"):
                inference_view = crop_frame_for_inference(frame, args.roi_top_ratio)
            with profiler.stage("enhance"):
                inference_frame = enhance_frame_for_detection(inference_view.image, args.enhance)
            with profiler.stage("ego-motion"):
                if args.ego_motion_mode == "off":
                    ego_motion = EgoMotionEstimate(quality_flags=("disabled",))
                elif processed_frames % args.ego_motion_every_n == 0:
                    ego_motion = ego_motion_estimator.update(frame)
                else:
                    ego_motion = EgoMotionEstimate(quality_flags=("skipped",))

            track_kwargs = {
                "persist": True,
                "tracker": args.tracker,
                "conf": args.conf,
                "imgsz": args.imgsz,
                "verbose": False,
                "device": args.device,
                "max_det": args.max_det,
            }
            if target_class_ids is not None:
                track_kwargs["classes"] = target_class_ids

            with profiler.stage("infer+track"):
                results = detector.track(inference_frame, **track_kwargs)
            inference_times.append(time.monotonic())
            with profiler.stage("postprocess"):
                result = restore_result_boxes_to_full_frame(results[0], inference_view.y_offset_px)
                observations = result_to_observations(
                    result,
                    timestamp_s,
                    calibration,
                    target_classes,
                    args.distance_mode,
                    args.size_weight,
                )
                observations = stable_track_ids.assign(observations)
                tracked_objects = [
                    track_state.update(observation, ego_motion_magnitude=ego_motion.magnitude_px)
                    for observation in observations
                ]
                tracked_objects = self_object_filter.apply(tracked_objects, frame.shape)
            with profiler.stage("risk"):
                raw_risk_by_track_id = {
                    target.track_id: (
                        ignored_target_assessment(target)
                        if getattr(target, "ignored_reason", "")
                        else risk_model.assess(target)
                    )
                    for target in tracked_objects
                }
                tracked_objects_by_id = {target.track_id: target for target in tracked_objects}
                risk_by_track_id = risk_stabilizer.stabilize(raw_risk_by_track_id, tracked_objects_by_id)
                if alert_emitter is not None:
                    alert_emitter.update(tracked_objects, risk_by_track_id)
                risk_logger.write_frame(
                    source_frame_index,
                    tracked_objects,
                    raw_risk_by_track_id,
                    risk_by_track_id,
                    risk_stabilizer.debug_info_by_track_id(),
                )

            now = time.monotonic()
            loop_dt = max(now - last_loop, 1e-6)
            last_loop = now
            fps_text = f"processing FPS: {1.0 / loop_dt:.1f}"
            source_text = f"source: {args.source}"
            if args.source == "video" and args.video:
                source_text += f" {Path(args.video).name}"
            source_text += f" pitch={calibration.camera_pitch_deg:.2f}"

            visualization_plan = visualization_plan_for_frame(
                processed_frame_index=processed_frames,
                display_every_n=args.display_every_n,
                no_display=args.no_display,
                has_writer=writer is not None,
                draw_for_stream=bool(video_server is not None and video_server.wants_overlay()),
            )
            display_frame = None
            if visualization_plan.should_draw_overlay:
                with profiler.stage("draw"):
                    display_frame = frame.copy()
                    draw_overlay(
                        display_frame,
                        tracked_objects,
                        fps_text,
                        source_text,
                        risk_by_track_id,
                        profiler.overlay_text(),
                        args.overlay_verbosity,
                    )
            else:
                profiler.record("draw", 0.0)

            with profiler.stage("display/write"):
                if visualization_plan.should_draw_for_output and writer is not None and display_frame is not None:
                    writer.write(display_frame)

                if visualization_plan.should_show_window and display_frame is not None:
                    cv2.imshow(WINDOW_NAME, maybe_resize_for_display(display_frame, args.display_scale))
                    key = cv2.waitKey(display_wait_ms(args, capture_fps)) & 0xFF
                else:
                    key = -1

            if video_server is not None:
                inference_fps = 0.0
                if len(inference_times) >= 2:
                    inference_fps = (len(inference_times) - 1) / max(inference_times[-1] - inference_times[0], 1e-6)
                capture_status = capture.status() if hasattr(capture, "status") else {
                    "online": True,
                    "device": args.camera_device or str(args.camera_index),
                    "capture_width": frame_width,
                    "capture_height": frame_height,
                    "capture_fps": capture_fps,
                    "last_frame_age_ms": 0.0,
                    "dropped_frames": 0,
                    "camera_reconnect_count": 0,
                }
                highest_level = max(
                    (
                        int(getattr(assessment.haptic_level, "value", assessment.haptic_level))
                        for assessment in risk_by_track_id.values()
                    ),
                    default=0,
                )
                capture_status.update(
                    {
                        "inference_fps": round(inference_fps, 2),
                        "risk_level": highest_level,
                        "risk_name": RiskLevel(highest_level).name,
                        "processed_frames": processed_frames + 1,
                    }
                )
                video_server.publish(frame, display_frame, capture_status)

            processed_frames += 1
        else:
            display_frame = current_frame.copy()
            cv2.putText(display_frame, "PAUSED", (24, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 220, 255), 2, cv2.LINE_AA)
            if args.no_display:
                key = -1
            else:
                with profiler.stage("display/write"):
                    cv2.imshow(WINDOW_NAME, maybe_resize_for_display(display_frame, args.display_scale))
                    key = cv2.waitKey(display_wait_ms(args, capture_fps)) & 0xFF

        if key in (27, ord("q")):
            break
        if key == ord(" "):
            paused = not paused
        if not args.no_display and key in (ord("["), ord("]")):
            delta = -1 if key == ord("[") else 1
            pitch = pitch_controller.adjust(delta)
            eprint(f"camera pitch: {pitch:.2f} deg")
        profiler.maybe_report_with_stream(video_server.status() if video_server is not None else None)

    if alert_emitter is not None:
        alert_emitter.clear_all()
    capture.release()
    if video_server is not None:
        video_server.stop()
    detector.close()
    if writer is not None:
        writer.release()
    risk_logger.close()
    if args.emit_alert_jsonl:
        sys.stdout = alert_stdout
    if not args.no_display:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
