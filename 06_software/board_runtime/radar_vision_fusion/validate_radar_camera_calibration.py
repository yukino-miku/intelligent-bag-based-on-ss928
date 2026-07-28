from __future__ import annotations

import argparse
import json

from radar_camera_calibration import load_fusion_calibration


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate one radar-camera fusion calibration JSON file.")
    parser.add_argument("calibration")
    args = parser.parse_args()
    calibration = load_fusion_calibration(args.calibration)
    print(json.dumps({"valid": True, "side": calibration.side}, separators=(",", ":")))


if __name__ == "__main__":
    main()
