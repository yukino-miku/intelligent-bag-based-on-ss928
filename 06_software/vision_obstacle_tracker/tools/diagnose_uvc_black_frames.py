from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from alternating_camera.v4l2_capture import V4l2MjpegDevice


def frame_visibility_metrics(image) -> dict[str, float]:
    import cv2
    import numpy as np

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    histogram = cv2.calcHist([gray], [0], None, [256], [0, 256]).reshape(-1)
    probabilities = histogram / max(float(histogram.sum()), 1.0)
    nonzero = probabilities[probabilities > 0.0]
    entropy = float(-(nonzero * np.log2(nonzero)).sum())
    edges = cv2.Canny(gray, 40, 120)
    p01, p99 = np.percentile(gray, [1.0, 99.0])
    return {
        "mean": float(gray.mean()),
        "stddev": float(gray.std()),
        "entropy_bits": entropy,
        "edge_density": float((edges > 0).mean()),
        "minimum": float(gray.min()),
        "maximum": float(gray.max()),
        "visible_dynamic_range": float(p99 - p01),
    }


def frame_is_effectively_black(metrics: dict[str, float]) -> bool:
    low_signal = metrics["mean"] < 12.0 and metrics["stddev"] < 8.0
    no_structure = metrics["entropy_bits"] < 2.0 and metrics["edge_density"] < 0.003
    no_range = metrics["visible_dynamic_range"] < 18.0
    return bool((low_signal and no_structure) or (low_signal and no_range))


def _command(argv: list[str]) -> str:
    try:
        completed = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=10.0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unavailable: {exc}"
    return (completed.stdout or completed.stderr).strip()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture UVC evidence and classify persistent black frames.")
    parser.add_argument("--device", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--frames", type=int, default=50)
    parser.add_argument("--warmup-frames", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    import cv2
    import numpy as np

    args = parse_args(argv)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    evidence = {
        "device": args.device,
        "v4l2_all": _command(["v4l2-ctl", "--device", args.device, "--all"]),
        "v4l2_formats": _command(
            ["v4l2-ctl", "--device", args.device, "--list-formats-ext"]
        ),
        "v4l2_controls": _command(
            ["v4l2-ctl", "--device", args.device, "--list-ctrls-menus"]
        ),
        "frames": [],
    }
    device = V4l2MjpegDevice(args.device, args.width, args.height, args.fps)
    try:
        negotiated = device.open()
        evidence["identity"] = device.identity()
        evidence["negotiated"] = {
            "width": negotiated.width,
            "height": negotiated.height,
            "pixel_format": negotiated.pixel_format,
            "actual_fps": negotiated.actual_fps,
        }
        device.start()
        for _index in range(args.warmup_frames):
            device.read_frame(2.0)
        for index in range(args.frames):
            raw = device.read_frame(2.0)
            image = cv2.imdecode(np.frombuffer(raw.data, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                evidence["frames"].append({"index": index, "decode_failed": True})
                continue
            metrics = frame_visibility_metrics(image)
            record = {
                "index": index,
                "sequence": raw.sequence,
                "captured_at_s": raw.captured_at_s,
                "jpeg_bytes": len(raw.data),
                "jpeg_sha256": hashlib.sha256(raw.data).hexdigest(),
                "effectively_black": frame_is_effectively_black(metrics),
                **metrics,
            }
            evidence["frames"].append(record)
            if index == 0:
                (output / "frame-000.raw.mjpg").write_bytes(raw.data)
                cv2.imwrite(str(output / "frame-000.decoded.png"), image)
    finally:
        device.close()
    valid = [row for row in evidence["frames"] if not row.get("decode_failed")]
    black_count = sum(bool(row["effectively_black"]) for row in valid)
    persistent_black = not valid or black_count / len(valid) >= 0.9
    evidence["summary"] = {
        "requested_frames": args.frames,
        "decoded_frames": len(valid),
        "black_frames": black_count,
        "black_ratio": black_count / max(len(valid), 1),
        "persistent_black": persistent_black,
        "result": "CAMERA_PHYSICAL_INPUT_BLOCKED" if persistent_black else "VISIBLE_SCENE",
    }
    (output / "black-frame-report.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence["summary"], ensure_ascii=False))
    return 1 if persistent_black else 0


if __name__ == "__main__":
    raise SystemExit(main())
