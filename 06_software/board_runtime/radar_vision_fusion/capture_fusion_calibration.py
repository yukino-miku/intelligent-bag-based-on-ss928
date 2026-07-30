from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Record synchronized manual radar/camera calibration observations.")
    parser.add_argument("--side", choices=("left", "right"), required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--radar-x", type=float, required=True)
    parser.add_argument("--radar-z", type=float, required=True)
    parser.add_argument("--pixel-u", type=float, required=True)
    parser.add_argument("--pixel-v", type=float, required=True)
    parser.add_argument("--image-width", type=int, required=True)
    parser.add_argument("--image-height", type=int, required=True)
    parser.add_argument("--target-id", default="manual")
    args = parser.parse_args()
    record = {
        "type": "fusion_calibration_observation",
        "side": args.side,
        "captured_mono_s": time.monotonic(),
        "radar_x_m": args.radar_x,
        "radar_z_m": args.radar_z,
        "pixel_u": args.pixel_u,
        "pixel_v": args.pixel_v,
        "image_width": args.image_width,
        "image_height": args.image_height,
        "target_id": args.target_id,
    }
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
