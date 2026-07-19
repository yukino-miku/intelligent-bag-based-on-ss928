from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import traceback
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from alternating_camera.gateway import AlternatingCameraGateway
from alternating_camera.scheduler import AlternatingCaptureConfig, AlternatingV4l2Capture
from alternating_camera.session import AlternatingSessionRecorder


STOP_REQUESTED = False


def eprint(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Experimental single-owner left/right UVC STREAMON/OFF alternation without YOLO or PWM."
    )
    parser.add_argument("--left-device", default="/dev/video0")
    parser.add_argument("--right-device", default="/dev/video2")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=5.0)
    parser.add_argument("--slice-ms", type=int, default=500)
    parser.add_argument("--frames-per-slice", type=int, default=4)
    parser.add_argument("--warmup-frames", type=int, default=2)
    parser.add_argument("--switch-count", type=int, default=20, help="Maximum activations; 0 means duration only.")
    parser.add_argument("--duration-s", type=float, default=0.0, help="Maximum run time; 0 means switch-count only.")
    parser.add_argument(
        "--backend",
        choices=("v4l2_stream_toggle", "opencv_reopen_fallback"),
        default="v4l2_stream_toggle",
    )
    parser.add_argument("--output-dir", default="08_media/alternating_camera_runs")
    parser.add_argument("--save-snapshots", action="store_true")
    parser.add_argument("--snapshot-every-n-switches", type=int, default=10)
    parser.add_argument("--frame-timeout-ms", type=int, default=1000)
    parser.add_argument("--switch-failure-limit", type=int, default=3)
    parser.add_argument("--switch-backoff-ms", type=int, default=200)
    parser.add_argument("--max-blind-interval-ms", type=int, default=1200)
    parser.add_argument("--runtime-mode", choices=("diagnostic", "stream_only"), default="diagnostic")
    parser.add_argument("--serve-bind", default="0.0.0.0")
    parser.add_argument("--serve-port", type=int, default=0)
    parser.add_argument("--stream-fps-limit", type=float, default=5.0)
    parser.add_argument("--access-token", default="")
    parser.add_argument("--latest-summary-path", default="")
    parser.add_argument("--acceptance-min-duration-s", type=float, default=1800.0)
    parser.add_argument("--debug", action="store_true", help="Print a full traceback after a fatal experiment error.")
    args = parser.parse_args(argv)
    if args.switch_count <= 0 and args.duration_s <= 0:
        parser.error("at least one of --switch-count or --duration-s must be positive")
    if args.snapshot_every_n_switches <= 0:
        parser.error("--snapshot-every-n-switches must be positive")
    if args.backend != "v4l2_stream_toggle":
        parser.error(
            "opencv_reopen_fallback is deliberately not presented as native STREAMON/OFF; "
            "this build currently validates only v4l2_stream_toggle"
        )
    if args.runtime_mode == "stream_only" and args.serve_port <= 0:
        args.serve_port = 8081
    return args


def build_session_id(args: argparse.Namespace) -> str:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    fps_text = f"{args.fps:g}".replace(".", "p")
    return f"{timestamp}_ss928_v4l2_{args.width}x{args.height}_{fps_text}fps"


def _request_stop(_signum: int, _frame: object) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


def run(args: argparse.Namespace) -> tuple[Path, dict[str, object]]:
    config = AlternatingCaptureConfig(
        width=args.width,
        height=args.height,
        fps=args.fps,
        slice_ms=args.slice_ms,
        frames_per_slice=args.frames_per_slice,
        warmup_frames=args.warmup_frames,
        frame_timeout_ms=args.frame_timeout_ms,
        switch_failure_limit=args.switch_failure_limit,
        switch_backoff_ms=args.switch_backoff_ms,
        max_blind_interval_ms=args.max_blind_interval_ms,
    )
    session_id = build_session_id(args)
    recorder = AlternatingSessionRecorder(
        args.output_dir,
        session_id,
        latest_summary_path=args.latest_summary_path or None,
    )
    capture = AlternatingV4l2Capture(args.left_device, args.right_device, config)
    gateway: AlternatingCameraGateway | None = None
    last_performance_s = time.monotonic()
    started_s = last_performance_s
    summary: dict[str, object] = {}
    try:
        negotiated = capture.open()
        device_metadata: dict[str, object] = {}
        for side in ("left", "right"):
            device = capture.devices[side]
            identity = device.identity()
            try:
                format_table = device.enumerate_formats()
            except Exception as exc:
                format_table = [{"error": str(exc)}]
                recorder.error(f"{side} format enumeration failed: {exc}")
            device_metadata[side] = {
                "identity": identity,
                "format_table": format_table,
                "requested": {
                    "width": args.width,
                    "height": args.height,
                    "fps": args.fps,
                    "pixel_format": "MJPG",
                },
                "negotiated": asdict(negotiated[side]),
            }
        recorder.update_metadata(
            {
                "left_by_path": args.left_device,
                "right_by_path": args.right_device,
                "cameras": device_metadata,
                "alternating_backend": capture.backend,
                "configuration": asdict(config),
                "runtime_mode": args.runtime_mode,
                "model_path": "",
                "model_sha256": "",
                "calibration_sha256": "",
                "yolo_enabled": False,
                "pwm_enabled": False,
                "ble_enabled": False,
                "video_gateway_enabled": bool(args.serve_port),
            }
        )
        if args.serve_port:
            gateway = AlternatingCameraGateway(
                capture,
                bind=args.serve_bind,
                port=args.serve_port,
                access_token=args.access_token,
                stream_fps_limit=args.stream_fps_limit,
            )
            gateway.start()
            eprint(f"alternating gateway listening on {args.serve_bind}:{gateway.port}")

        side = "left"
        while not STOP_REQUESTED:
            if args.switch_count > 0 and capture.switch_count >= args.switch_count:
                break
            if args.duration_s > 0 and time.monotonic() - started_s >= args.duration_s:
                break
            result = capture.capture_slice(side)
            recorder.record_switch(result.event)
            for frame in result.frames:
                recorder.record_frame(frame, active_side=capture.active_side)
            if (
                args.save_snapshots
                and result.frames
                and result.event.switch_index % args.snapshot_every_n_switches == 0
            ):
                recorder.save_snapshot(result.frames[-1], result.event.switch_index)
            if not result.event.success:
                eprint(
                    f"switch={result.event.switch_index} side={side} failed "
                    f"{result.event.error_type}: {result.event.error_message}"
                )
            elif capture.switch_count % 10 == 0:
                status = capture.status()
                eprint(
                    f"switches={capture.switch_count} active={status['active_camera']} "
                    f"fps(L/R)={status['left_effective_fps']}/{status['right_effective_fps']} "
                    f"age_ms(L/R)={status['left_last_frame_age_ms']}/{status['right_last_frame_age_ms']}"
                )
            now_s = time.monotonic()
            if now_s - last_performance_s >= 1.0:
                status = capture.status(now_s)
                recorder.record_performance(
                    status,
                    gateway_clients=gateway.gateway_clients if gateway else 0,
                    camera_errors=capture.streamon_failures + capture.streamoff_failures,
                )
                last_performance_s = now_s
            side = "right" if side == "left" else "left"
    except Exception as exc:
        recorder.error(f"fatal: {type(exc).__name__}: {exc}")
        raise
    finally:
        if gateway is not None:
            gateway.stop()
        capture.close()
        if not recorder.performance_rows:
            recorder.record_performance(capture.status(), camera_errors=capture.streamon_failures + capture.streamoff_failures)
        summary = recorder.finish(
            acceptance_min_duration_s=args.acceptance_min_duration_s,
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
        eprint(f"alternating camera experiment failed: {type(exc).__name__}: {exc}")
        if args.debug:
            traceback.print_exc(file=sys.stderr)
        return 1
    print(json.dumps({"session_dir": str(session_dir), "summary": summary}, ensure_ascii=False))
    return 0 if summary.get("switch_success_rate_percent", 0.0) >= 99.0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
