from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
import json
import signal
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from alert_output import AlertJsonlEmitter
from alternating_camera.scheduler import (
    AlternatingCaptureConfig,
    AlternatingRiskScheduleConfig,
    AlternatingV4l2Capture,
    RiskPrioritySlicePolicy,
)
from alternating_camera.pipeline import (
    FrameStageTimeline,
    ObservationGapTracker,
    select_latest_inference_frames,
)
from alternating_camera.gateway import AlternatingCameraGateway
from alternating_camera.session import AlternatingSessionRecorder
from alternating_camera.vision_runtime import (
    IndependentUltralyticsTracker,
    SharedModelAlternatingEngine,
    TrackerRuntimeConfig,
)
from calibration import CameraExtrinsics, extrinsics_from_mapping, load_calibration_file
from detector_backend import IndependentIouTracker
from risk_model import RiskModel
from vision_core import StableTrackIdManager, TrackState, parse_target_classes
from vision_obstacle_tracker import (
    RiskCsvLogger,
    RiskWarningStabilizer,
    RiskWarningStabilizerConfig,
    SelfObjectFilter,
    create_camera_calibration,
    create_detector_backend,
    crop_frame_for_inference,
    enhance_frame_for_detection,
    ignored_target_assessment,
    restore_result_boxes_to_full_frame,
    result_to_observations,
    target_class_ids_from_model_names,
    draw_overlay,
    risk_level_name,
)


STOP_REQUESTED = False


def eprint(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _request_stop(_signum: int, _frame: object) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


@dataclass(frozen=True)
class SideFrameResult:
    side: str
    targets: list[object]
    raw_risks: dict[int, object]
    display_risks: dict[int, object]
    alerts: list[dict[str, object]]
    haptic_level: int
    tracking_ms: float
    risk_ms: float
    single_frame_jump_suppressed_count: int


class RealSideVisionContext:
    def __init__(self, side: str, args: argparse.Namespace, frame_width: int, frame_height: int) -> None:
        self.side = side
        self.args = args
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.tracker = self._create_tracker()
        side_args = argparse.Namespace(**vars(args))
        side_calibration_file = (
            args.left_calibration_file if side == "left" else args.right_calibration_file
        )
        side_args.calibration_file = side_calibration_file or args.calibration_file
        self.calibration = create_camera_calibration(side_args, frame_width, frame_height)
        fallback_extrinsics = CameraExtrinsics(
            yaw_deg=float(getattr(args, f"{side}_yaw_deg")),
            roll_deg=float(getattr(args, f"{side}_roll_deg")),
            mount_x_m=float(getattr(args, f"{side}_mount_x_m")),
            mount_z_m=float(getattr(args, f"{side}_mount_z_m")),
            calibrated=bool(getattr(args, f"{side}_extrinsics_calibrated")),
        )
        calibration_mapping = (
            load_calibration_file(side_args.calibration_file)
            if side_args.calibration_file
            else {}
        )
        self.extrinsics = extrinsics_from_mapping(calibration_mapping, fallback_extrinsics)
        if args.calibration_mode == "production" and not self.extrinsics.calibrated:
            raise ValueError(f"{side} camera extrinsics are not calibrated")
        if not self.extrinsics.calibrated:
            eprint(f"WARNING: {side} camera uses uncalibrated placeholder extrinsics")
        self.stable_track_ids = StableTrackIdManager()
        self.track_state = TrackState(
            history_seconds=args.speed_window,
            smoothing_alpha=args.distance_smoothing,
            max_speed_mps=args.max_speed,
            speed_scale=args.speed_scale,
        )
        self.risk_model = RiskModel()
        self.risk_stabilizer = self._create_stabilizer()
        self.self_object_filter = SelfObjectFilter(
            bottom_ratio=args.self_mask_bottom_ratio,
            enabled=not args.disable_self_object_filter,
        )
        risk_path = Path(args.risk_log_dir) / f"risk-{side}.csv" if args.risk_log_dir else None
        self.risk_logger = RiskCsvLogger(str(risk_path) if risk_path else None)
        self.alert_emitter = AlertJsonlEmitter(
            sys.stdout,
            fixed_side=side,
            min_level=args.alert_min_level,
            rate_limit_s=args.alert_rate_limit,
        )
        self.target_classes = parse_target_classes(args.target_classes)
        self.frame_index = 0

    def _create_tracker(self) -> object:
        args = self.args
        if args.detector_backend == "ss928_om":
            return IndependentIouTracker()
        return IndependentUltralyticsTracker(
            TrackerRuntimeConfig(
                args.tracker,
                frame_rate=args.tracker_nominal_fps or args.fps,
                effective_fps_mode=args.tracker_effective_fps_mode,
                expected_side_fps=(
                    args.inference_frames_per_slice * 1000.0 / max(2.0 * args.normal_slice_ms, 1.0)
                ),
            )
        )

    def _create_stabilizer(self) -> RiskWarningStabilizer:
        args = self.args
        return RiskWarningStabilizer(
            RiskWarningStabilizerConfig(
                min_confirm_duration_caution_s=args.caution_confirm_duration_s,
                min_confirm_duration_danger_s=args.danger_confirm_duration_s,
                min_confirm_duration_emergency_s=args.emergency_confirm_duration_s,
                low_quality_extra_duration_s=args.low_quality_extra_duration_s,
                min_confirm_slices_caution=args.min_confirm_slices_caution,
                min_confirm_slices_danger=args.min_confirm_slices_danger,
                min_confirm_slices_emergency=args.min_confirm_slices_emergency,
                minimum_confirmation_interval_s=args.minimum_confirmation_interval_s,
                allow_emergency_single_slice_fast_path=(
                    not args.disable_emergency_single_slice_fast_path
                ),
            )
        )

    def reset_tracking_state(self) -> None:
        self.tracker = self._create_tracker()
        self.stable_track_ids = StableTrackIdManager()
        self.track_state = TrackState(
            history_seconds=self.args.speed_window,
            smoothing_alpha=self.args.distance_smoothing,
            max_speed_mps=self.args.max_speed,
            speed_scale=self.args.speed_scale,
        )
        self.risk_stabilizer = self._create_stabilizer()

    def clear_for_camera_disconnect(self) -> list[dict[str, object]]:
        alerts = self.alert_emitter.clear_all()
        for payload in alerts:
            payload["clear_reason"] = "camera_disconnect"
        return alerts

    def process_detection(
        self,
        result: object,
        image: object,
        timestamp_s: float,
        **context: object,
    ) -> SideFrameResult:
        full_frame = context["full_frame"]
        y_offset_px = int(context.get("y_offset_px", 0))
        effective_side_fps = float(context.get("effective_side_fps", 0.0))
        slice_id = int(context.get("slice_id", -1))
        timeline = context.get("timeline")
        self.tracker.update_effective_fps(effective_side_fps)
        tracking_started_s = time.perf_counter()
        if timeline is not None:
            timeline.tracking_start_s = time.monotonic()
        tracked_result = self.tracker.update(result, image)
        tracked_result = restore_result_boxes_to_full_frame(tracked_result, y_offset_px)
        observations = result_to_observations(
            tracked_result,
            timestamp_s,
            self.calibration,
            self.target_classes,
            self.args.distance_mode,
            self.args.size_weight,
            self.extrinsics,
        )
        observations = self.stable_track_ids.assign(observations)
        targets = [self.track_state.update(observation) for observation in observations]
        targets = self.self_object_filter.apply(targets, full_frame.shape)
        tracking_ms = (time.perf_counter() - tracking_started_s) * 1000.0
        if timeline is not None:
            timeline.tracking_end_s = time.monotonic()
        risk_started_s = time.perf_counter()
        if timeline is not None:
            timeline.risk_start_s = time.monotonic()
        raw_risks = {
            target.track_id: (
                ignored_target_assessment(target)
                if getattr(target, "ignored_reason", "")
                else self.risk_model.assess(target)
            )
            for target in targets
        }
        targets_by_id = {target.track_id: target for target in targets}
        display_risks = self.risk_stabilizer.stabilize(
            raw_risks,
            targets_by_id,
            {target.track_id: timestamp_s for target in targets},
            effective_side_fps=effective_side_fps,
            slice_id=slice_id,
        )
        stabilizer_debug = self.risk_stabilizer.debug_info_by_track_id()
        single_frame_jump_suppressed_count = (
            self.risk_stabilizer.consume_single_frame_jump_suppressed_count()
        )
        alerts = self.alert_emitter.update(
            targets,
            display_risks,
            observed_sides=(self.side,),
            observation_s=timestamp_s,
        )
        self.risk_logger.write_frame(
            self.frame_index,
            targets,
            raw_risks,
            display_risks,
            stabilizer_debug,
        )
        for payload in alerts:
            track_id = int(payload.get("track_id", -1))
            target = targets_by_id.get(track_id)
            raw = raw_risks.get(track_id)
            display = display_risks.get(track_id)
            debug = stabilizer_debug.get(track_id)
            if target is not None:
                payload.update(
                    {
                        "distance_m": getattr(target, "distance_m", None),
                        "approach_consistency": getattr(target, "approach_consistency", None),
                        "path_conflict_consistency": getattr(target, "path_conflict_consistency", None),
                    }
                )
            if raw is not None:
                payload.update(
                    {
                        "raw_level": int(raw.level),
                        "path_conflict": bool(raw.path_conflict),
                        "moving_away": bool(raw.moving_away),
                        "cpa_time_s": raw.cpa_time_s,
                        "cpa_distance_m": raw.cpa_distance_m,
                        "corridor_entry_time_s": raw.corridor_entry_time_s,
                    }
                )
            if display is not None:
                payload.update(
                    {
                        "visual_level": int(display.visual_level),
                        "haptic_level": int(display.haptic_level),
                    }
                )
            if debug is not None:
                payload.update(
                    {
                        "stabilizer_pending_level": int(debug.pending_level),
                        "stabilizer_pending_count": debug.pending_count,
                        "stabilizer_required_frames": debug.required_frames,
                        "slice_id": debug.slice_id,
                        "pending_slice_count": debug.pending_slice_count,
                        "required_slices": debug.required_slices,
                        "confirmed_across_slices": debug.confirmed_across_slices,
                        "fast_path_reason": debug.fast_path_reason,
                    }
                )
        self.frame_index += 1
        haptic_level = max(
            (int(getattr(risk.haptic_level, "value", risk.haptic_level)) for risk in display_risks.values()),
            default=0,
        )
        risk_ms = (time.perf_counter() - risk_started_s) * 1000.0
        if timeline is not None:
            timeline.risk_end_s = time.monotonic()
        return SideFrameResult(
            self.side,
            targets,
            raw_risks,
            display_risks,
            alerts,
            haptic_level,
            tracking_ms,
            risk_ms,
            single_frame_jump_suppressed_count,
        )

    def heartbeat(self, stale_timeout_s: float) -> list[dict[str, object]]:
        return self.alert_emitter.heartbeat(stale_timeout_s)

    def close(self) -> list[dict[str, object]]:
        alerts = self.alert_emitter.clear_all()
        self.risk_logger.close()
        return alerts


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Experimental one-model, alternating dual-UVC vision runtime.")
    parser.add_argument("--left-device", required=True)
    parser.add_argument("--right-device", required=True)
    parser.add_argument("--backend", choices=("v4l2_stream_toggle",), default="v4l2_stream_toggle")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--normal-slice-ms", type=int, default=500)
    parser.add_argument("--risk-slice-ms", type=int, default=700)
    parser.add_argument("--minimum-other-side-slice-ms", type=int, default=250)
    parser.add_argument("--warmup-frames", type=int, default=2)
    parser.add_argument("--frames-per-slice", type=int, default=4)
    parser.add_argument("--inference-frames-per-slice", type=int, default=1)
    parser.add_argument(
        "--continuous-slice-inference",
        action="store_true",
        help=(
            "Keep the active camera streaming for the full slice and process each captured "
            "frame immediately instead of batching frames after STREAMOFF."
        ),
    )
    parser.add_argument("--max-blind-interval-ms", type=int, default=1200)
    parser.add_argument("--stale-observation-timeout-ms", type=int, default=1800)
    parser.add_argument("--switch-failure-limit", type=int, default=3)
    parser.add_argument("--switch-backoff-ms", type=int, default=200)
    parser.add_argument("--disable-camera-reconnect", action="store_true")
    parser.add_argument("--camera-reconnect-attempts", type=int, default=5)
    parser.add_argument("--camera-reconnect-initial-backoff-s", type=float, default=0.5)
    parser.add_argument("--camera-reconnect-max-backoff-s", type=float, default=8.0)
    parser.add_argument("--tracker-reset-after-disconnect-s", type=float, default=3.0)
    parser.add_argument("--disable-risk-priority", action="store_true")
    parser.add_argument("--duration-s", type=float, default=0.0)
    parser.add_argument("--switch-count", type=int, default=0)
    parser.add_argument("--output-dir", default="08_media/alternating_camera_runs")
    parser.add_argument("--risk-log-dir", default="")
    parser.add_argument("--latest-summary-path", default="")
    parser.add_argument("--model", default="yolo11n.pt")
    parser.add_argument(
        "--detector-backend",
        choices=("ultralytics", "ss928_om"),
        default="ultralytics",
    )
    parser.add_argument("--ss928-runtime-library", default=None)
    parser.add_argument("--ss928-acl-config", default=None)
    parser.add_argument("--tracker", default="vehicle_botsort.yaml")
    parser.add_argument("--tracker-nominal-fps", type=float, default=0.0)
    parser.add_argument(
        "--tracker-effective-fps-mode",
        choices=("fixed", "negotiated", "effective_side"),
        default="effective_side",
    )
    parser.add_argument("--conf", type=float, default=0.08)
    parser.add_argument("--imgsz", type=int, default=416)
    parser.add_argument("--max-det", type=int, default=30)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--prefer-openvino", action="store_true")
    parser.add_argument("--export-openvino", action="store_true")
    parser.add_argument("--target-classes", default="car,bicycle,motorcycle,bus,truck")
    parser.add_argument("--roi-top-ratio", type=float, default=0.0)
    parser.add_argument("--enhance", choices=("off", "auto", "clahe"), default="off")
    parser.add_argument("--self-mask-bottom-ratio", type=float, default=0.92)
    parser.add_argument("--disable-self-object-filter", action="store_true")
    parser.add_argument("--camera-height", type=float, default=1.2)
    parser.add_argument("--camera-pitch", type=float, default=5.0)
    parser.add_argument("--calibration-file", default="")
    parser.add_argument("--left-calibration-file", default="")
    parser.add_argument("--right-calibration-file", default="")
    parser.add_argument("--calibration-mode", choices=("diagnostic", "production"), default="diagnostic")
    for side in ("left", "right"):
        parser.add_argument(f"--{side}-yaw-deg", type=float, default=0.0)
        parser.add_argument(f"--{side}-roll-deg", type=float, default=0.0)
        parser.add_argument(f"--{side}-mount-x-m", type=float, default=0.0)
        parser.add_argument(f"--{side}-mount-z-m", type=float, default=0.0)
        parser.add_argument(f"--{side}-extrinsics-calibrated", action="store_true")
    parser.add_argument("--fov", type=float, default=120.0)
    parser.add_argument("--fov-type", choices=("diagonal", "horizontal", "vertical"), default="diagonal")
    parser.add_argument("--horizontal-fov", type=float, default=None)
    parser.add_argument("--distance-scale", type=float, default=1.0)
    parser.add_argument("--distance-mode", choices=("fused", "ground", "size"), default="fused")
    parser.add_argument("--size-weight", type=float, default=0.75)
    parser.add_argument("--speed-window", type=float, default=1.5)
    parser.add_argument("--distance-smoothing", type=float, default=0.35)
    parser.add_argument("--max-speed", type=float, default=40.0)
    parser.add_argument("--speed-scale", type=float, default=1.0)
    parser.add_argument("--alert-min-level", type=int, default=1)
    parser.add_argument("--alert-rate-limit", type=float, default=0.25)
    parser.add_argument("--caution-confirm-duration-s", type=float, default=0.03)
    parser.add_argument("--danger-confirm-duration-s", type=float, default=0.06)
    parser.add_argument("--emergency-confirm-duration-s", type=float, default=0.03)
    parser.add_argument("--low-quality-extra-duration-s", type=float, default=0.10)
    parser.add_argument("--min-confirm-slices-caution", type=int, default=2)
    parser.add_argument("--min-confirm-slices-danger", type=int, default=2)
    parser.add_argument("--min-confirm-slices-emergency", type=int, default=2)
    parser.add_argument("--minimum-confirmation-interval-s", type=float, default=0.20)
    parser.add_argument("--disable-emergency-single-slice-fast-path", action="store_true")
    parser.add_argument("--serve-bind", default="0.0.0.0")
    parser.add_argument("--serve-port", type=int, default=8080)
    parser.add_argument("--access-token", default="")
    parser.add_argument("--jpeg-quality", type=int, default=80)
    parser.add_argument("--overlay-width", type=int, default=0)
    parser.add_argument("--overlay-height", type=int, default=0)
    parser.add_argument("--stream-fps-limit", type=float, default=5.0)
    parser.add_argument("--disable-video-gateway", action="store_true")
    args = parser.parse_args(argv)
    if args.duration_s <= 0.0 and args.switch_count <= 0:
        parser.error("one of --duration-s or --switch-count must be positive")
    if not 0.0 <= args.roi_top_ratio < 1.0:
        parser.error("--roi-top-ratio must be >= 0 and < 1")
    if not 1 <= args.inference_frames_per_slice <= args.frames_per_slice:
        parser.error("--inference-frames-per-slice must be between 1 and --frames-per-slice")
    for option in (
        "min_confirm_slices_caution",
        "min_confirm_slices_danger",
        "min_confirm_slices_emergency",
    ):
        if getattr(args, option) < 1:
            parser.error(f"--{option.replace('_', '-')} must be at least 1")
    if not 1 <= args.jpeg_quality <= 100:
        parser.error("--jpeg-quality must be between 1 and 100")
    if args.serve_port < 0 or args.serve_port > 65535:
        parser.error("--serve-port must be between 0 and 65535")
    return args


def _sha256(path: str) -> str:
    candidate = Path(path)
    if not candidate.is_file():
        return ""
    digest = hashlib.sha256()
    with candidate.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _session_id(args: argparse.Namespace) -> str:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}_ss928_single-model_{args.width}x{args.height}_{args.fps:g}fps"


def _create_model_with_jsonl_safe_stdout(args: argparse.Namespace) -> object:
    with redirect_stdout(sys.stderr):
        return create_detector_backend(args)


def _record_alert(recorder: AlternatingSessionRecorder, payload: dict[str, object]) -> None:
    recorder.record_alert(
        {
            "timestamp": payload.get("ts", time.monotonic()),
            "side": payload.get("side", ""),
            "track_id": payload.get("track_id", ""),
            "class": payload.get("class", ""),
            "distance_m": payload.get("distance_m", ""),
            "raw_level": payload.get("raw_level", ""),
            "visual_level": payload.get("visual_level", ""),
            "haptic_level": payload.get("haptic_level", payload.get("level", 0)),
            "score": payload.get("score", 0.0),
            "path_conflict": payload.get("path_conflict", ""),
            "moving_away": payload.get("moving_away", ""),
            "cpa_time_s": payload.get("cpa_time_s", ""),
            "cpa_distance_m": payload.get("cpa_distance_m", ""),
            "corridor_entry_time_s": payload.get("corridor_entry_time_s", ""),
            "approach_consistency": payload.get("approach_consistency", ""),
            "path_conflict_consistency": payload.get("path_conflict_consistency", ""),
            "stabilizer_pending_level": payload.get("stabilizer_pending_level", ""),
            "stabilizer_pending_count": payload.get("stabilizer_pending_count", ""),
            "stabilizer_required_frames": payload.get("stabilizer_required_frames", ""),
            "slice_id": payload.get("slice_id", ""),
            "pending_slice_count": payload.get("pending_slice_count", ""),
            "required_slices": payload.get("required_slices", ""),
            "confirmed_across_slices": payload.get("confirmed_across_slices", ""),
            "fast_path_reason": payload.get("fast_path_reason", ""),
            "event_kind": payload.get("event_kind", "state_change"),
            "clear_reason": payload.get("clear_reason", ""),
            "observation_age_ms": payload.get("observation_age_ms", ""),
        }
    )


def _result_metadata(result: SideFrameResult, slice_id: int) -> dict[str, object]:
    if not result.display_risks:
        return {
            "slice_id": slice_id,
            "risk_level": 0,
            "risk_name": "SAFE",
            "track_id": None,
            "class": "",
            "distance_m": None,
        }
    track_id, display = max(
        result.display_risks.items(),
        key=lambda item: (int(item[1].haptic_level), int(item[1].visual_level), item[1].score),
    )
    target = next((target for target in result.targets if target.track_id == track_id), None)
    return {
        "slice_id": slice_id,
        "risk_level": int(display.haptic_level),
        "risk_name": risk_level_name(display.haptic_level),
        "track_id": track_id,
        "class": getattr(target, "class_name", ""),
        "distance_m": getattr(target, "distance_m", None),
    }


def _encode_overlay(
    frame,
    result: SideFrameResult,
    *,
    side: str,
    slice_id: int,
    frame_age_ms: float,
    args: argparse.Namespace,
    timeline: FrameStageTimeline,
) -> tuple[bytes, float, float]:
    import cv2

    timeline.overlay_start_s = time.monotonic()
    overlay_started_s = time.perf_counter()
    overlay = frame.copy()
    draw_overlay(
        overlay,
        result.targets,
        fps_text=f"side={side} slice={slice_id} age={frame_age_ms:.0f}ms cached-other-side",
        source_text="alternating_single_model",
        risk_by_track_id=result.display_risks,
        overlay_verbosity="normal",
    )
    for target in result.targets:
        raw = result.raw_risks.get(target.track_id)
        display = result.display_risks.get(target.track_id)
        if raw is None or display is None:
            continue
        x1, _y1, _x2, y2 = [int(round(value)) for value in target.bbox_xyxy]
        detail = (
            f"raw={risk_level_name(raw.level)} visual={risk_level_name(display.visual_level)} "
            f"haptic={risk_level_name(display.haptic_level)} path={int(raw.path_conflict)} "
            f"away={int(raw.moving_away)}"
        )
        cv2.putText(
            overlay,
            detail,
            (max(0, x1), min(overlay.shape[0] - 8, max(18, y2 + 18))),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    if args.overlay_width > 0 and args.overlay_height > 0:
        overlay = cv2.resize(
            overlay,
            (args.overlay_width, args.overlay_height),
            interpolation=cv2.INTER_AREA,
        )
    draw_ms = (time.perf_counter() - overlay_started_s) * 1000.0
    timeline.overlay_end_s = time.monotonic()

    timeline.jpeg_encode_start_s = time.monotonic()
    encode_started_s = time.perf_counter()
    ok, encoded = cv2.imencode(
        ".jpg",
        overlay,
        [int(cv2.IMWRITE_JPEG_QUALITY), args.jpeg_quality],
    )
    jpeg_ms = (time.perf_counter() - encode_started_s) * 1000.0
    timeline.jpeg_encode_end_s = time.monotonic()
    if not ok:
        raise RuntimeError("overlay JPEG encoding failed")
    return encoded.tobytes(), draw_ms, jpeg_ms


def run(args: argparse.Namespace) -> tuple[Path, dict[str, object]]:
    import cv2
    import numpy as np

    capture_config = AlternatingCaptureConfig(
        width=args.width,
        height=args.height,
        fps=args.fps,
        slice_ms=args.normal_slice_ms,
        frames_per_slice=args.frames_per_slice,
        inference_frames_per_slice=args.inference_frames_per_slice,
        warmup_frames=args.warmup_frames,
        switch_failure_limit=args.switch_failure_limit,
        switch_backoff_ms=args.switch_backoff_ms,
        max_blind_interval_ms=args.max_blind_interval_ms,
        camera_reconnect_enabled=not args.disable_camera_reconnect,
        camera_reconnect_attempts=args.camera_reconnect_attempts,
        camera_reconnect_initial_backoff_s=args.camera_reconnect_initial_backoff_s,
        camera_reconnect_max_backoff_s=args.camera_reconnect_max_backoff_s,
        tracker_reset_after_disconnect_s=args.tracker_reset_after_disconnect_s,
    )
    schedule = RiskPrioritySlicePolicy(
        AlternatingRiskScheduleConfig(
            normal_slice_ms=args.normal_slice_ms,
            risk_slice_ms=args.risk_slice_ms,
            minimum_other_side_slice_ms=args.minimum_other_side_slice_ms,
            max_blind_interval_ms=args.max_blind_interval_ms,
            risk_priority_enabled=not args.disable_risk_priority,
        )
    )
    capture = AlternatingV4l2Capture(args.left_device, args.right_device, capture_config)
    recorder = AlternatingSessionRecorder(
        args.output_dir,
        _session_id(args),
        latest_summary_path=args.latest_summary_path or None,
    )
    contexts: dict[str, RealSideVisionContext] = {}
    inference_durations_ms: deque[float] = deque(maxlen=120)
    detector_preprocess_durations_ms: deque[float] = deque(maxlen=120)
    npu_inference_durations_ms: deque[float] = deque(maxlen=120)
    detector_postprocess_durations_ms: deque[float] = deque(maxlen=120)
    tracking_durations_ms: deque[float] = deque(maxlen=120)
    risk_durations_ms: deque[float] = deque(maxlen=120)
    draw_durations_ms: deque[float] = deque(maxlen=120)
    jpeg_durations_ms: deque[float] = deque(maxlen=120)
    inference_times_s: deque[float] = deque(maxlen=120)
    inference_times_by_side = {
        "left": deque(maxlen=120),
        "right": deque(maxlen=120),
    }
    oldest_pending_ages_ms: deque[float] = deque(maxlen=120)
    observation_gaps = ObservationGapTracker()
    pending_frame_records: list[dict[str, object]] = []
    captured_valid_frames = 0
    selected_inference_frames = 0
    skipped_inference_frames = 0
    started_s = time.monotonic()
    last_performance_s = started_s
    side = "left"
    engine: SharedModelAlternatingEngine | None = None
    gateway: AlternatingCameraGateway | None = None
    runtime_status: dict[str, object] = {"sides": {"left": {}, "right": {}}}
    summary: dict[str, object] = {}
    try:
        negotiated = capture.open()
        engine = SharedModelAlternatingEngine(
            args.model,
            lambda camera_side: contexts.setdefault(
                camera_side,
                RealSideVisionContext(
                    camera_side,
                    args,
                    negotiated[camera_side].width,
                    negotiated[camera_side].height,
                ),
            ),
            model_factory=lambda _path: _create_model_with_jsonl_safe_stdout(args),
            predict_kwargs={
                "conf": args.conf,
                "imgsz": args.imgsz,
                "verbose": False,
                "device": args.device,
                "max_det": args.max_det,
            },
            predict_stdout=sys.stderr,
        )
        class_ids = target_class_ids_from_model_names(engine.names, parse_target_classes(args.target_classes))
        if class_ids is not None:
            engine.predict_kwargs["classes"] = class_ids
        for camera_side in ("left", "right"):
            fmt = negotiated[camera_side]
            runtime_status["sides"][camera_side] = {
                "device": args.left_device if camera_side == "left" else args.right_device,
                "requested_width": args.width,
                "requested_height": args.height,
                "actual_width": fmt.width,
                "actual_height": fmt.height,
                "requested_fps": args.fps,
                "actual_fps": fmt.actual_fps,
            }
        runtime_status.update(
            {
                "model": args.model,
                "model_backend": args.detector_backend,
                "jpeg_quality": args.jpeg_quality,
            }
        )
        if not args.disable_video_gateway:
            gateway = AlternatingCameraGateway(
                capture,
                bind=args.serve_bind,
                port=args.serve_port,
                access_token=args.access_token,
                stream_fps_limit=args.stream_fps_limit,
                status_provider=lambda: runtime_status,
            )
            gateway.start()
            eprint(f"Alternating video gateway: http://{args.serve_bind}:{gateway.port}/")
        started_s = time.monotonic()
        last_performance_s = started_s
        recorder.update_metadata(
            {
                "left_by_path": args.left_device,
                "right_by_path": args.right_device,
                "cameras": {side_name: asdict(fmt) for side_name, fmt in negotiated.items()},
                "camera_identity": {
                    side_name: capture.devices[side_name].identity()
                    for side_name in ("left", "right")
                },
                "camera_format_tables": {
                    side_name: capture.devices[side_name].enumerate_formats()
                    for side_name in ("left", "right")
                },
                "alternating_backend": capture.backend,
                "configuration": vars(args),
                "runtime_mode": "alternating_single_model",
                "model_path": args.model,
                "model_sha256": _sha256(args.model),
                "calibration_sha256": {
                    "left": _sha256(args.left_calibration_file or args.calibration_file),
                    "right": _sha256(args.right_calibration_file or args.calibration_file),
                },
                "yolo_enabled": True,
                "pwm_enabled": False,
                "ble_enabled": False,
                "video_gateway_enabled": gateway is not None,
                "video_gateway_port": gateway.port if gateway is not None else None,
                "shared_model_instances": 1,
            }
        )

        def process_frame(
            frame,
            event,
            *,
            effective_fps: float,
        ) -> None:
            nonlocal selected_inference_frames
            selected_inference_frames += 1
            timeline = FrameStageTimeline(
                slice_id=event.slice_id,
                side=frame.side,
                capture_slice_start_s=event.capture_slice_start_s,
                capture_slice_end_s=event.capture_slice_end_s,
                streamoff_complete_s=event.streamoff_complete_s,
            )
            timeline.decode_start_s = time.monotonic()
            decode_started_s = time.perf_counter()
            full_frame = cv2.imdecode(
                np.frombuffer(frame.data, dtype=np.uint8),
                cv2.IMREAD_COLOR,
            )
            decode_ms = (time.perf_counter() - decode_started_s) * 1000.0
            timeline.decode_end_s = time.monotonic()
            if full_frame is None:
                recorder.error(f"decode failed side={frame.side} sequence={frame.sequence}")
                timeline.processing_complete_s = time.monotonic()
                pending_frame_records.append(
                    {
                        "frame": frame,
                        "active_side": frame.side,
                        "decode_ms": decode_ms,
                        "selected_for_inference": True,
                        "timeline": timeline,
                        "reconnect_count": capture.side_state[frame.side].reconnect_count,
                        "last_error": "jpeg_decode_failed",
                    }
                )
                return

            gap_metrics = observation_gaps.observe(frame.side, frame.captured_at_s)
            oldest_pending_ages_ms.append(
                max(0.0, timeline.decode_start_s - frame.captured_at_s) * 1000.0
            )
            inference_view = crop_frame_for_inference(full_frame, args.roi_top_ratio)
            inference_image = enhance_frame_for_detection(inference_view.image, args.enhance)
            result = engine.process(
                frame.side,
                inference_image,
                frame.captured_at_s,
                full_frame=full_frame,
                y_offset_px=inference_view.y_offset_px,
                effective_side_fps=effective_fps,
                slice_id=event.slice_id,
                timeline=timeline,
            )
            inference_durations_ms.append(engine.last_inference_ms)
            detector_model = engine.model
            if hasattr(detector_model, "last_preprocess_ms"):
                detector_preprocess_durations_ms.append(
                    float(detector_model.last_preprocess_ms)
                )
            if hasattr(detector_model, "last_npu_ms"):
                npu_inference_durations_ms.append(float(detector_model.last_npu_ms))
            if hasattr(detector_model, "last_postprocess_ms"):
                detector_postprocess_durations_ms.append(
                    float(detector_model.last_postprocess_ms)
                )
            tracking_durations_ms.append(result.tracking_ms)
            risk_durations_ms.append(result.risk_ms)
            recorder.record_single_frame_jump_suppressed(
                result.single_frame_jump_suppressed_count
            )
            inferred_at_s = time.monotonic()
            inference_times_s.append(inferred_at_s)
            inference_times_by_side[frame.side].append(inferred_at_s)
            schedule.update_haptic_level(frame.side, result.haptic_level)
            for payload in result.alerts:
                _record_alert(recorder, payload)
            metadata = _result_metadata(result, event.slice_id)
            draw_ms = 0.0
            jpeg_ms = 0.0
            if gateway is not None:
                overlay_bytes, draw_ms, jpeg_ms = _encode_overlay(
                    full_frame,
                    result,
                    side=frame.side,
                    slice_id=event.slice_id,
                    frame_age_ms=max(0.0, time.monotonic() - frame.captured_at_s) * 1000.0,
                    args=args,
                    timeline=timeline,
                )
                gateway.publish_overlay(
                    frame.side,
                    overlay_bytes,
                    sequence=frame.sequence,
                    captured_at_s=frame.captured_at_s,
                    metadata=metadata,
                )
                draw_durations_ms.append(draw_ms)
                jpeg_durations_ms.append(jpeg_ms)
            side_times = inference_times_by_side[frame.side]
            side_inference_fps = (
                (len(side_times) - 1) / max(side_times[-1] - side_times[0], 1e-6)
                if len(side_times) >= 2
                else 0.0
            )
            runtime_status["sides"][frame.side].update(
                {
                    "slice_id": event.slice_id,
                    "inference_fps": side_inference_fps,
                    "inference_ms": engine.last_inference_ms,
                    "detector_preprocess_ms": float(
                        getattr(engine.model, "last_preprocess_ms", 0.0)
                    ),
                    "npu_inference_ms": float(getattr(engine.model, "last_npu_ms", 0.0)),
                    "detector_postprocess_ms": float(
                        getattr(engine.model, "last_postprocess_ms", 0.0)
                    ),
                    "tracking_ms": result.tracking_ms,
                    "risk_ms": result.risk_ms,
                    "overlay_ms": draw_ms,
                    "jpeg_encode_ms": jpeg_ms,
                    "end_to_end_observation_gap_ms": gap_metrics[
                        "end_to_end_observation_gap_ms"
                    ],
                    **metadata,
                }
            )
            timeline.processing_complete_s = time.monotonic()
            pending_frame_records.append(
                {
                    "frame": frame,
                    "active_side": frame.side,
                    "decode_ms": decode_ms,
                    "selected_for_inference": True,
                    "timeline": timeline,
                    "end_to_end_observation_gap_ms": gap_metrics[
                        "end_to_end_observation_gap_ms"
                    ],
                    "side_to_side_latency_ms": gap_metrics["side_to_side_latency_ms"],
                    "reconnect_count": capture.side_state[frame.side].reconnect_count,
                    "last_error": capture.side_state[frame.side].last_error,
                }
            )

        consecutive_failed_slices = 0
        while not STOP_REQUESTED:
            prior_frame_records = pending_frame_records
            pending_frame_records = []

            def process_captured_frame(frame, event) -> None:
                if gateway is not None:
                    gateway.publish_raw(frame, {"slice_id": event.slice_id})
                live_status = capture.status()
                process_frame(
                    frame,
                    event,
                    effective_fps=float(
                        live_status.get(f"{frame.side}_effective_fps", 0.0) or 0.0
                    ),
                )

            pending_slice = capture.capture_slice(
                side,
                slice_ms=schedule.slice_ms_for(side),
                streamoff_after_slice=True,
                capture_until_deadline=args.continuous_slice_inference,
                frame_callback=(
                    process_captured_frame if args.continuous_slice_inference else None
                ),
            )
            for pending_record in prior_frame_records:
                timeline = pending_record["timeline"]
                timeline.next_camera_streamon_s = pending_slice.event.streamon_start_s
                timeline.next_camera_first_frame_s = pending_slice.event.first_frame_s
                recorder.record_frame(**pending_record)
            recorder.record_switch(pending_slice.event)
            if args.continuous_slice_inference:
                for pending_record in pending_frame_records:
                    timeline = pending_record["timeline"]
                    timeline.capture_slice_end_s = pending_slice.event.capture_slice_end_s
                    timeline.streamoff_complete_s = pending_slice.event.streamoff_complete_s
            if pending_slice.event.success:
                consecutive_failed_slices = 0
            else:
                consecutive_failed_slices += 1
                context = contexts.get(side)
                if context is not None:
                    disconnect_clears = context.clear_for_camera_disconnect()
                    for payload in disconnect_clears:
                        _record_alert(recorder, payload)
            status = capture.status()
            runtime_status["sides"][side].update(
                {
                    "connection_state": status.get(f"{side}_connection_state"),
                    "reconnect_count": status.get(f"{side}_reconnect_count", 0),
                }
            )
            if pending_slice.event.success and capture.consume_tracker_reset_required(side):
                contexts[side].reset_tracking_state()
                recorder.error(f"tracker reset after extended {side} camera disconnect")
            effective_fps = float(status.get(f"{side}_effective_fps", 0.0) or 0.0)
            captured_valid_frames += len(pending_slice.frames)
            if not args.continuous_slice_inference:
                if gateway is not None:
                    for captured_frame in pending_slice.frames:
                        gateway.publish_raw(
                            captured_frame,
                            {"slice_id": pending_slice.event.slice_id},
                        )
                selected_frames, skipped_count = select_latest_inference_frames(
                    pending_slice.frames,
                    args.inference_frames_per_slice,
                )
                selected_sequences = {frame.sequence for frame in selected_frames}
                skipped_inference_frames += skipped_count
                for frame in pending_slice.frames:
                    if frame.sequence in selected_sequences:
                        continue
                    recorder.record_frame(
                        frame,
                        active_side=side,
                        selected_for_inference=False,
                        reconnect_count=capture.side_state[side].reconnect_count,
                        last_error=capture.side_state[side].last_error,
                    )
                for frame in selected_frames:
                    process_frame(
                        frame,
                        pending_slice.event,
                        effective_fps=effective_fps,
                    )
            for context in contexts.values():
                for payload in context.heartbeat(args.stale_observation_timeout_ms / 1000.0):
                    _record_alert(recorder, payload)

            now_s = time.monotonic()
            if now_s - last_performance_s >= 1.0:
                inference_fps = (
                    (len(inference_times_s) - 1) / max(inference_times_s[-1] - inference_times_s[0], 1e-6)
                    if len(inference_times_s) >= 2
                    else 0.0
                )
                gap_summary = observation_gaps.summary()
                capture_only_max_blind = max(
                    float(status.get("left_blind_interval_ms") or 0.0),
                    float(status.get("right_blind_interval_ms") or 0.0),
                )
                recorder.record_performance(
                    capture.status(now_s),
                    gateway_clients=gateway.gateway_clients if gateway is not None else 0,
                    camera_errors=capture.streamon_failures + capture.streamoff_failures,
                    stage_metrics={
                        "inference_fps": inference_fps,
                        "inference_ms": (
                            sum(inference_durations_ms) / len(inference_durations_ms)
                            if inference_durations_ms
                            else 0.0
                        ),
                        "detector_preprocess_ms": (
                            sum(detector_preprocess_durations_ms)
                            / len(detector_preprocess_durations_ms)
                            if detector_preprocess_durations_ms
                            else 0.0
                        ),
                        "npu_inference_ms": (
                            sum(npu_inference_durations_ms) / len(npu_inference_durations_ms)
                            if npu_inference_durations_ms
                            else 0.0
                        ),
                        "detector_postprocess_ms": (
                            sum(detector_postprocess_durations_ms)
                            / len(detector_postprocess_durations_ms)
                            if detector_postprocess_durations_ms
                            else 0.0
                        ),
                        "tracking_ms": (
                            sum(tracking_durations_ms) / len(tracking_durations_ms)
                            if tracking_durations_ms
                            else 0.0
                        ),
                        "risk_ms": (
                            sum(risk_durations_ms) / len(risk_durations_ms)
                            if risk_durations_ms
                            else 0.0
                        ),
                        "draw_ms": (
                            sum(draw_durations_ms) / len(draw_durations_ms)
                            if draw_durations_ms
                            else 0.0
                        ),
                        "jpeg_encode_ms": (
                            sum(jpeg_durations_ms) / len(jpeg_durations_ms)
                            if jpeg_durations_ms
                            else 0.0
                        ),
                        "capture_only_max_blind_ms": capture_only_max_blind,
                        **gap_summary,
                        "captured_valid_frames": captured_valid_frames,
                        "selected_inference_frames": selected_inference_frames,
                        "skipped_inference_frames": skipped_inference_frames,
                        "inference_frames_per_slice": (
                            len(pending_slice.frames)
                            if args.continuous_slice_inference
                            else args.inference_frames_per_slice
                        ),
                        "inference_queue_depth": 0,
                        "oldest_pending_frame_age_ms": (
                            max(oldest_pending_ages_ms) if oldest_pending_ages_ms else 0.0
                        ),
                    },
                )
                runtime_status.update(
                    {
                        **gap_summary,
                        "capture_only_max_blind_ms": capture_only_max_blind,
                        "cpu_percent": recorder.performance_rows[-1]["cpu_percent"],
                        "process_rss_mb": recorder.performance_rows[-1]["process_rss_mb"],
                        "temperature_c": recorder.performance_rows[-1]["temperature_c"],
                    }
                )
                last_performance_s = now_s
            if consecutive_failed_slices >= args.switch_failure_limit:
                raise RuntimeError(
                    f"camera switching failed for {consecutive_failed_slices} consecutive slices"
                )
            if args.switch_count > 0 and capture.switch_count >= args.switch_count:
                break
            if args.duration_s > 0.0 and now_s - started_s >= args.duration_s:
                break
            side = "right" if side == "left" else "left"
    except Exception as exc:
        recorder.error(f"fatal: {type(exc).__name__}: {exc}")
        raise
    finally:
        for pending_record in pending_frame_records:
            recorder.record_frame(**pending_record)
        pending_frame_records.clear()
        for context in contexts.values():
            for payload in context.close():
                _record_alert(recorder, payload)
        if gateway is not None:
            gateway.stop()
        if engine is not None:
            engine.close()
        capture.close()
        recorder.camera_reconnects = sum(
            state.reconnect_count for state in capture.side_state.values()
        )
        if not recorder.performance_rows:
            recorder.record_performance(capture.status())
        summary = recorder.finish(
            acceptance_min_duration_s=max(1800.0, args.duration_s),
            acceptance_max_blind_interval_ms=args.max_blind_interval_ms,
        )
        recorder.close()
    return recorder.session_dir, summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    try:
        session_dir, summary = run(args)
    except Exception as exc:
        eprint(f"alternating single-model runtime failed: {type(exc).__name__}: {exc}")
        return 1
    eprint(json.dumps({"session_dir": str(session_dir), "summary": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
