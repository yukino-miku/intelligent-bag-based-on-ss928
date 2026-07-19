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
from alternating_camera.session import AlternatingSessionRecorder
from alternating_camera.vision_runtime import (
    IndependentUltralyticsTracker,
    SharedModelAlternatingEngine,
    TrackerRuntimeConfig,
)
from risk_model import RiskModel
from vision_core import StableTrackIdManager, TrackState, parse_target_classes
from vision_obstacle_tracker import (
    RiskCsvLogger,
    RiskWarningStabilizer,
    RiskWarningStabilizerConfig,
    SelfObjectFilter,
    create_camera_calibration,
    create_yolo_model,
    crop_frame_for_inference,
    enhance_frame_for_detection,
    ignored_target_assessment,
    restore_result_boxes_to_full_frame,
    result_to_observations,
    target_class_ids_from_model_names,
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


class RealSideVisionContext:
    def __init__(self, side: str, args: argparse.Namespace, frame_width: int, frame_height: int) -> None:
        self.side = side
        self.args = args
        self.tracker = IndependentUltralyticsTracker(
            TrackerRuntimeConfig(args.tracker, frame_rate=args.fps)
        )
        side_args = argparse.Namespace(**vars(args))
        side_calibration_file = (
            args.left_calibration_file if side == "left" else args.right_calibration_file
        )
        side_args.calibration_file = side_calibration_file or args.calibration_file
        self.calibration = create_camera_calibration(side_args, frame_width, frame_height)
        self.stable_track_ids = StableTrackIdManager()
        self.track_state = TrackState(
            history_seconds=args.speed_window,
            smoothing_alpha=args.distance_smoothing,
            max_speed_mps=args.max_speed,
            speed_scale=args.speed_scale,
        )
        self.risk_model = RiskModel()
        self.risk_stabilizer = RiskWarningStabilizer(
            RiskWarningStabilizerConfig(
                min_confirm_duration_caution_s=args.caution_confirm_duration_s,
                min_confirm_duration_danger_s=args.danger_confirm_duration_s,
                min_confirm_duration_emergency_s=args.emergency_confirm_duration_s,
                low_quality_extra_duration_s=args.low_quality_extra_duration_s,
            )
        )
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
        tracking_started_s = time.perf_counter()
        tracked_result = self.tracker.update(result, image)
        tracked_result = restore_result_boxes_to_full_frame(tracked_result, y_offset_px)
        observations = result_to_observations(
            tracked_result,
            timestamp_s,
            self.calibration,
            self.target_classes,
            self.args.distance_mode,
            self.args.size_weight,
        )
        observations = self.stable_track_ids.assign(observations)
        targets = [self.track_state.update(observation) for observation in observations]
        targets = self.self_object_filter.apply(targets, full_frame.shape)
        tracking_ms = (time.perf_counter() - tracking_started_s) * 1000.0
        risk_started_s = time.perf_counter()
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
        )
        stabilizer_debug = self.risk_stabilizer.debug_info_by_track_id()
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
                    }
                )
        self.frame_index += 1
        haptic_level = max(
            (int(getattr(risk.haptic_level, "value", risk.haptic_level)) for risk in display_risks.values()),
            default=0,
        )
        risk_ms = (time.perf_counter() - risk_started_s) * 1000.0
        return SideFrameResult(
            self.side,
            targets,
            raw_risks,
            display_risks,
            alerts,
            haptic_level,
            tracking_ms,
            risk_ms,
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
    parser.add_argument("--max-blind-interval-ms", type=int, default=1200)
    parser.add_argument("--stale-observation-timeout-ms", type=int, default=1800)
    parser.add_argument("--switch-failure-limit", type=int, default=3)
    parser.add_argument("--switch-backoff-ms", type=int, default=200)
    parser.add_argument("--disable-risk-priority", action="store_true")
    parser.add_argument("--duration-s", type=float, default=0.0)
    parser.add_argument("--switch-count", type=int, default=0)
    parser.add_argument("--output-dir", default="08_media/alternating_camera_runs")
    parser.add_argument("--risk-log-dir", default="")
    parser.add_argument("--latest-summary-path", default="")
    parser.add_argument("--model", default="yolo11n.pt")
    parser.add_argument("--tracker", default="vehicle_botsort.yaml")
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
    args = parser.parse_args(argv)
    if args.duration_s <= 0.0 and args.switch_count <= 0:
        parser.error("one of --duration-s or --switch-count must be positive")
    if not 0.0 <= args.roi_top_ratio < 1.0:
        parser.error("--roi-top-ratio must be >= 0 and < 1")
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
        return create_yolo_model(args)


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
            "event_kind": payload.get("event_kind", "state_change"),
            "clear_reason": payload.get("clear_reason", ""),
            "observation_age_ms": payload.get("observation_age_ms", ""),
        }
    )


def run(args: argparse.Namespace) -> tuple[Path, dict[str, object]]:
    import cv2
    import numpy as np

    capture_config = AlternatingCaptureConfig(
        width=args.width,
        height=args.height,
        fps=args.fps,
        slice_ms=args.normal_slice_ms,
        frames_per_slice=args.frames_per_slice,
        warmup_frames=args.warmup_frames,
        switch_failure_limit=args.switch_failure_limit,
        switch_backoff_ms=args.switch_backoff_ms,
        max_blind_interval_ms=args.max_blind_interval_ms,
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
    tracking_durations_ms: deque[float] = deque(maxlen=120)
    risk_durations_ms: deque[float] = deque(maxlen=120)
    inference_times_s: deque[float] = deque(maxlen=120)
    started_s = time.monotonic()
    last_performance_s = started_s
    side = "left"
    engine: SharedModelAlternatingEngine | None = None
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
                "video_gateway_enabled": False,
                "shared_model_instances": 1,
            }
        )

        consecutive_failed_slices = 0
        while not STOP_REQUESTED:
            pending_slice = capture.capture_slice(
                side,
                slice_ms=schedule.slice_ms_for(side),
                streamoff_after_slice=True,
            )
            recorder.record_switch(pending_slice.event)
            if pending_slice.event.success:
                consecutive_failed_slices = 0
            else:
                consecutive_failed_slices += 1
            status = capture.status()
            effective_fps = float(status.get(f"{side}_effective_fps", 0.0) or 0.0)
            for frame in pending_slice.frames:
                decode_started_s = time.perf_counter()
                full_frame = cv2.imdecode(np.frombuffer(frame.data, dtype=np.uint8), cv2.IMREAD_COLOR)
                decode_ms = (time.perf_counter() - decode_started_s) * 1000.0
                recorder.record_frame(frame, active_side=side, decode_ms=decode_ms)
                if full_frame is None:
                    recorder.error(f"decode failed side={side} sequence={frame.sequence}")
                    continue
                inference_view = crop_frame_for_inference(full_frame, args.roi_top_ratio)
                inference_image = enhance_frame_for_detection(inference_view.image, args.enhance)
                result = engine.process(
                    side,
                    inference_image,
                    frame.captured_at_s,
                    full_frame=full_frame,
                    y_offset_px=inference_view.y_offset_px,
                    effective_side_fps=effective_fps,
                )
                inference_durations_ms.append(engine.last_inference_ms)
                tracking_durations_ms.append(result.tracking_ms)
                risk_durations_ms.append(result.risk_ms)
                inference_times_s.append(time.monotonic())
                schedule.update_haptic_level(side, result.haptic_level)
                for payload in result.alerts:
                    _record_alert(recorder, payload)
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
                recorder.record_performance(
                    capture.status(now_s),
                    camera_errors=capture.streamon_failures + capture.streamoff_failures,
                    stage_metrics={
                        "inference_fps": inference_fps,
                        "inference_ms": (
                            sum(inference_durations_ms) / len(inference_durations_ms)
                            if inference_durations_ms
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
                    },
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
        for context in contexts.values():
            for payload in context.close():
                _record_alert(recorder, payload)
        capture.close()
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
