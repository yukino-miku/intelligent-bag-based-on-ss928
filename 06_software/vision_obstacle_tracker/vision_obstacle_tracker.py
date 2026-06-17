from __future__ import annotations

import argparse
import os
import threading
import time
from dataclasses import replace
from pathlib import Path

from camera_source import FfmpegCameraConfig, FfmpegMjpegCameraCapture
from calibration import CameraCalibration, estimate_ground_point_from_bbox
from risk_model import RiskAssessment, RiskLevel, RiskModel, risk_level_from_score
from vision_core import DetectionObservation, StableTrackIdManager, TrackState, format_overlay_label, parse_target_classes, should_keep_class


WINDOW_NAME = "YOLO Tracking Distance Speed"


RUNTIME_PROFILES = {
    "realtime": {
        "width": 960,
        "height": 540,
        "imgsz": 512,
        "conf": 0.03,
        "max_det": 50,
    },
    "balanced": {
        "width": 1280,
        "height": 720,
        "imgsz": 1024,
        "conf": 0.02,
        "max_det": 50,
    },
    "quality": {
        "width": 1920,
        "height": 1080,
        "imgsz": 1024,
        "conf": 0.02,
        "max_det": 50,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PC-side YOLO tracking, distance, and speed visualization.")
    parser.add_argument("--source", choices=("camera", "video"), default="camera", help="Input source type.")
    parser.add_argument("--video", help="Video file path when --source video is used.")
    parser.add_argument("--camera-index", type=int, default=1, help="OpenCV camera index. USB Camera is usually 1 on this PC.")
    parser.add_argument("--camera-backend", choices=("ffmpeg", "opencv"), default="ffmpeg", help="Live camera backend.")
    parser.add_argument("--camera-name", default="USB Camera", help="DirectShow camera device name for --camera-backend ffmpeg.")
    parser.add_argument("--runtime-profile", choices=tuple(RUNTIME_PROFILES), default="balanced", help="Runtime preset: realtime prioritizes FPS, balanced is default, quality favors far-object recognition.")
    parser.add_argument("--width", type=int, default=None, help="Requested camera width. Defaults come from --runtime-profile.")
    parser.add_argument("--height", type=int, default=None, help="Requested camera height. Defaults come from --runtime-profile.")
    parser.add_argument("--fps", type=float, default=30.0, help="Requested camera FPS or fallback video FPS.")
    parser.add_argument("--model", default="yolo11n.pt", help="Ultralytics YOLO model path/name.")
    parser.add_argument("--tracker", default="vehicle_botsort.yaml", help="Ultralytics tracker config, for example vehicle_botsort.yaml.")
    parser.add_argument("--conf", type=float, default=None, help="YOLO confidence threshold. Lower values detect farther/smaller objects.")
    parser.add_argument("--imgsz", type=int, default=None, help="YOLO inference image size. Defaults come from --runtime-profile.")
    parser.add_argument("--max-det", type=int, default=None, help="Maximum detections per frame passed to YOLO.")
    parser.add_argument("--export-openvino", action="store_true", help="Export --model to OpenVINO format, then use the exported model for CPU inference.")
    parser.add_argument("--target-classes", default="car,bicycle,motorcycle,bus,truck", help="Comma-separated COCO class names to display, or all.")
    parser.add_argument("--device", default=None, help="Ultralytics device, for example cpu, 0, cuda:0. Default: auto.")
    parser.add_argument("--camera-height", type=float, default=1.2, help="Camera height above ground in meters. Default approximates chest mounting.")
    parser.add_argument("--camera-pitch", type=float, default=5.0, help="Camera downward pitch in degrees. Smaller values increase forward distance.")
    parser.add_argument("--fov", type=float, default=120.0, help="Camera field of view in degrees.")
    parser.add_argument("--fov-type", choices=("diagonal", "horizontal", "vertical"), default="diagonal", help="How --fov is specified.")
    parser.add_argument("--horizontal-fov", type=float, default=None, help="Legacy override for horizontal FOV in degrees.")
    parser.add_argument("--distance-mode", choices=("fused", "ground", "size"), default="fused", help="Distance estimate mode.")
    parser.add_argument("--size-weight", type=float, default=0.75, help="Weight of vehicle-size distance in fused mode.")
    parser.add_argument("--distance-scale", type=float, default=1.0, help="Multiplier for estimated distances after field calibration.")
    parser.add_argument("--speed-scale", type=float, default=1.0, help="Multiplier for estimated relative speed.")
    parser.add_argument("--speed-window", type=float, default=1.5, help="Seconds of track history used for speed estimation.")
    parser.add_argument("--distance-smoothing", type=float, default=0.35, help="EMA alpha for distance smoothing. 1 disables smoothing.")
    parser.add_argument("--max-speed", type=float, default=40.0, help="Reject velocity spikes above this m/s. 0 disables rejection.")
    parser.add_argument("--enhance", choices=("off", "auto", "clahe"), default="off", help="Optional lightweight contrast enhancement before YOLO.")
    parser.add_argument("--display-scale", type=float, default=1.0, help="Scale display window; inference uses original frame.")
    parser.add_argument("--save-output", help="Optional output MP4 path with overlays.")
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
    return args


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

    if args.camera_backend == "ffmpeg":
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

    backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
    capture = cv2.VideoCapture(args.camera_index, backend)
    if not capture.isOpened():
        raise SystemExit(f"Could not open camera index {args.camera_index}. Try --camera-index 0 or 1.")

    capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    capture.set(cv2.CAP_PROP_FPS, args.fps)
    return capture


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


def create_yolo_model(args: argparse.Namespace, yolo_cls=None):
    if yolo_cls is None:
        from ultralytics import YOLO

        yolo_cls = YOLO

    model = yolo_cls(args.model)
    if args.export_openvino:
        exported_model_path = model.export(format="openvino")
        model = yolo_cls(exported_model_path)
    return model


def frame_timestamp(args: argparse.Namespace, start_time: float, frame_index: int, fps: float) -> float:
    if args.source == "video":
        return frame_index / max(fps, 1.0)
    return time.monotonic() - start_time


def result_to_observations(
    result,
    timestamp_s: float,
    calibration: CameraCalibration,
    target_classes: set[str] | None,
    distance_mode: str,
    size_weight: float,
) -> list[DetectionObservation]:
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
        ground_point = distance_estimate.point if distance_estimate is not None else None
        distance_source = distance_estimate.source if distance_estimate is not None else "unknown"
        observations.append(
            DetectionObservation(
                track_id=int(box.id[0].item()),
                class_name=class_name,
                confidence=confidence,
                bbox_xyxy=(x1, y1, x2, y2),
                ground_point=ground_point,
                timestamp_s=timestamp_s,
                distance_source=distance_source,
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


def format_risk_suffix(assessment: RiskAssessment | None) -> str:
    if assessment is None:
        return "RiskScore=0.00 SAFE"
    ttc = f" TTC={assessment.ttc_s:.1f}s" if assessment.ttc_s is not None else ""
    trajectory = (
        f" TRAJ={assessment.trajectory_distance_m:.1f}m"
        if assessment.trajectory_distance_m is not None
        else ""
    )
    return f"RiskScore={assessment.score:.2f} {risk_level_name(assessment.level)}{ttc}{trajectory}"


class RiskWarningStabilizer:
    def __init__(self, min_warning_frames: int = 3) -> None:
        self.min_warning_frames = max(1, min_warning_frames)
        self.score_window_frames = self.min_warning_frames + 1
        self._recent_scores_by_track_id: dict[int, list[float]] = {}

    def stabilize(self, risk_by_track_id: dict[int, RiskAssessment]) -> dict[int, RiskAssessment]:
        stabilized: dict[int, RiskAssessment] = {}
        active_track_ids = set(risk_by_track_id)

        for track_id, assessment in risk_by_track_id.items():
            recent_scores = self._recent_scores_by_track_id.setdefault(track_id, [])
            recent_scores.append(assessment.score)
            while len(recent_scores) > self.score_window_frames:
                del recent_scores[0]

            if len(recent_scores) < self.score_window_frames:
                stabilized[track_id] = replace(assessment, score=0.0, level=RiskLevel.SAFE)
                continue

            display_score = self._display_score_from_recent_scores(recent_scores)
            display_level = risk_level_from_score(display_score)
            if display_level <= RiskLevel.SAFE:
                stabilized[track_id] = replace(assessment, score=0.0, level=RiskLevel.SAFE)
            else:
                stabilized[track_id] = replace(assessment, score=display_score, level=display_level)

        for track_id in list(self._recent_scores_by_track_id):
            if track_id not in active_track_ids:
                del self._recent_scores_by_track_id[track_id]

        return stabilized

    @staticmethod
    def _display_score_from_recent_scores(recent_scores: list[float]) -> float:
        selected_count = max(1, len(recent_scores) - 1)
        if len(recent_scores) <= selected_count:
            return min(recent_scores, default=0.0)

        sorted_scores = sorted(recent_scores)
        best_group = sorted_scores[:selected_count]
        best_span = best_group[-1] - best_group[0]

        for start in range(1, len(sorted_scores) - selected_count + 1):
            group = sorted_scores[start : start + selected_count]
            span = group[-1] - group[0]
            if span < best_span or (span == best_span and group[0] > best_group[0]):
                best_group = group
                best_span = span

        return best_group[0]


def draw_overlay(
    frame,
    tracked_objects,
    fps_text: str,
    source_text: str,
    risk_by_track_id: dict[int, RiskAssessment] | None = None,
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

        label = f"{format_overlay_label(target)} {format_risk_suffix(assessment)}"
        y_label = max(24, y1 - 8)
        cv2.putText(frame, label, (x1, y_label), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)

    cv2.putText(frame, source_text, (24, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(frame, fps_text, (24, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(frame, "q/Esc: exit  Space: pause", (24, 108), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (220, 220, 220), 2, cv2.LINE_AA)


def maybe_resize_for_display(frame, scale: float):
    import cv2

    if scale <= 0 or abs(scale - 1.0) < 1e-6:
        return frame
    return cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def display_wait_ms(args: argparse.Namespace, capture_fps: float) -> int:
    return 1


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
    import cv2

    args = parse_args()
    capture = open_capture(args)
    capture_fps = float(capture.get(cv2.CAP_PROP_FPS) or args.fps or 30.0) if hasattr(capture, "get") else float(args.fps or 30.0)

    ok, first_frame = capture.read()
    if not ok:
        raise SystemExit("Input opened but no frame could be read.")

    frame_height, frame_width = first_frame.shape[:2]
    calibration = CameraCalibration(
        image_width=frame_width,
        image_height=frame_height,
        fov_deg=args.fov,
        fov_type=args.fov_type,
        horizontal_fov_deg=args.horizontal_fov,
        camera_height_m=args.camera_height,
        camera_pitch_deg=args.camera_pitch,
        distance_scale=args.distance_scale,
    )

    writer = create_writer(args, first_frame.shape, capture_fps)
    model = create_yolo_model(args)
    track_state = TrackState(
        history_seconds=args.speed_window,
        smoothing_alpha=args.distance_smoothing,
        max_speed_mps=args.max_speed,
        speed_scale=args.speed_scale,
    )
    stable_track_ids = StableTrackIdManager()
    risk_model = RiskModel()
    risk_stabilizer = RiskWarningStabilizer()
    target_classes = parse_target_classes(args.target_classes)

    start_time = time.monotonic()
    processed_frames = 0
    source_frame_index = 0
    paused = False
    last_loop = time.monotonic()
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
                ok, frame = capture.read()
                if not ok:
                    break
            current_frame = frame
            if args.source == "video" and hasattr(capture, "last_frame_index"):
                source_frame_index = max(0, int(capture.last_frame_index))
            elif processed_frames > 0:
                source_frame_index += 1

            timestamp_s = frame_timestamp(args, start_time, source_frame_index, capture_fps)
            inference_frame = enhance_frame_for_detection(frame, args.enhance)
            results = model.track(
                inference_frame,
                persist=True,
                tracker=args.tracker,
                conf=args.conf,
                imgsz=args.imgsz,
                verbose=False,
                device=args.device,
                max_det=args.max_det,
            )
            observations = result_to_observations(
                results[0],
                timestamp_s,
                calibration,
                target_classes,
                args.distance_mode,
                args.size_weight,
            )
            observations = stable_track_ids.assign(observations)
            tracked_objects = [track_state.update(observation) for observation in observations]
            raw_risk_by_track_id = {target.track_id: risk_model.assess(target) for target in tracked_objects}
            risk_by_track_id = risk_stabilizer.stabilize(raw_risk_by_track_id)

            now = time.monotonic()
            loop_dt = max(now - last_loop, 1e-6)
            last_loop = now
            fps_text = f"processing FPS: {1.0 / loop_dt:.1f}"
            source_text = f"source: {args.source}"
            if args.source == "video" and args.video:
                source_text += f" {Path(args.video).name}"

            display_frame = frame.copy()
            draw_overlay(display_frame, tracked_objects, fps_text, source_text, risk_by_track_id)
            if writer is not None:
                writer.write(display_frame)

            processed_frames += 1
        else:
            display_frame = current_frame.copy()
            cv2.putText(display_frame, "PAUSED", (24, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 220, 255), 2, cv2.LINE_AA)

        if args.no_display:
            key = -1
        else:
            cv2.imshow(WINDOW_NAME, maybe_resize_for_display(display_frame, args.display_scale))
            key = cv2.waitKey(display_wait_ms(args, capture_fps)) & 0xFF
            if key in (27, ord("q")):
                break
            if key == ord(" "):
                paused = not paused

    capture.release()
    if writer is not None:
        writer.release()
    if not args.no_display:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
