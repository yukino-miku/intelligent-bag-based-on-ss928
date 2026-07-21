from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from alternating_camera.image_transform import CameraImageTransform
from alternating_camera.scheduler import AlternatingCaptureConfig, AlternatingV4l2Capture
from alternating_camera.v4l2_capture import V4l2MjpegDevice
from tools.calibration_workflow import checkerboard_signature, find_checkerboard


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Headless checkerboard image capture for SmartBag cameras.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--device")
    source.add_argument("--left-device")
    parser.add_argument("--right-device")
    parser.add_argument("--side", choices=("left", "right"), default="left")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--board-cols", type=int, default=9)
    parser.add_argument("--board-rows", type=int, default=6)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--max-images-per-side", type=int, default=24)
    parser.add_argument("--duration-s", type=float, default=300.0)
    parser.add_argument("--warmup-frames", type=int, default=2)
    for side in ("left", "right"):
        parser.add_argument(f"--{side}-rotation-deg", type=int, choices=(0, 90, 180, 270), default=0)
        parser.add_argument(f"--{side}-flip-horizontal", action="store_true")
        parser.add_argument(f"--{side}-flip-vertical", action="store_true")
    args = parser.parse_args(argv)
    if bool(args.left_device) != bool(args.right_device):
        parser.error("alternating capture requires both --left-device and --right-device")
    return args


def _transform(args: argparse.Namespace, side: str) -> CameraImageTransform:
    return CameraImageTransform(
        rotation_deg=getattr(args, f"{side}_rotation_deg"),
        flip_horizontal=getattr(args, f"{side}_flip_horizontal"),
        flip_vertical=getattr(args, f"{side}_flip_vertical"),
    )


def main(argv: list[str] | None = None) -> int:
    import cv2
    import numpy as np

    args = parse_args(argv)
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    sides = ("left", "right") if args.left_device else (args.side,)
    accepted = {side: 0 for side in sides}
    signatures = {side: set() for side in sides}
    attempts = {side: 0 for side in sides}
    started_s = time.monotonic()

    def process_jpeg(side: str, data: bytes, sequence: int) -> None:
        attempts[side] += 1
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return
        image = _transform(args, side).apply(image)
        corners = find_checkerboard(image, (args.board_cols, args.board_rows))
        if corners is None:
            return
        signature = checkerboard_signature(corners, (image.shape[1], image.shape[0]))
        if signature in signatures[side]:
            return
        signatures[side].add(signature)
        side_dir = output_root / side
        side_dir.mkdir(exist_ok=True)
        destination = side_dir / f"{accepted[side]:03d}-seq{sequence:06d}.jpg"
        ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        if not ok:
            return
        destination.write_bytes(encoded.tobytes())
        accepted[side] += 1
        print(f"accepted side={side} image={destination.name} coverage={len(signatures[side])}", flush=True)

    capture = None
    device = None
    try:
        if args.left_device:
            capture = AlternatingV4l2Capture(
                args.left_device,
                args.right_device,
                AlternatingCaptureConfig(
                    width=args.width,
                    height=args.height,
                    fps=args.fps,
                    slice_ms=500,
                    frames_per_slice=1,
                    inference_frames_per_slice=1,
                    warmup_frames=args.warmup_frames,
                    require_stable_camera_paths=True,
                ),
            )
            capture.open()
            side = "left"
            while time.monotonic() - started_s < args.duration_s and any(
                accepted[name] < args.max_images_per_side for name in sides
            ):
                result = capture.capture_slice(side, streamoff_after_slice=True)
                if result.frames and accepted[side] < args.max_images_per_side:
                    frame = result.frames[-1]
                    process_jpeg(side, frame.data, frame.sequence)
                side = "right" if side == "left" else "left"
        else:
            device = V4l2MjpegDevice(args.device, args.width, args.height, args.fps)
            device.open()
            device.start()
            for _index in range(args.warmup_frames):
                device.read_frame(2.0)
            while (
                time.monotonic() - started_s < args.duration_s
                and accepted[args.side] < args.max_images_per_side
            ):
                frame = device.read_frame(2.0)
                process_jpeg(args.side, frame.data, frame.sequence)
    finally:
        if capture is not None:
            capture.close()
        if device is not None:
            device.close()

    report = {
        "board_cols": args.board_cols,
        "board_rows": args.board_rows,
        "accepted": accepted,
        "attempts": attempts,
        "coverage_bins": {side: len(values) for side, values in signatures.items()},
        "transforms": {side: _transform(args, side).as_dict() for side in sides},
        "duration_s": round(time.monotonic() - started_s, 3),
    }
    (output_root / "capture-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if all(count >= 8 for count in accepted.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
