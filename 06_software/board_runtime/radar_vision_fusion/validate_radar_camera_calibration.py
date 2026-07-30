from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from radar_camera_calibration import load_fusion_calibration


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate one radar-camera fusion calibration JSON file.")
    parser.add_argument("calibration")
    parser.add_argument("--max-horizontal-rmse-px", type=float, default=40.0)
    parser.add_argument("--require-measured", action="store_true")
    args = parser.parse_args()
    calibration = load_fusion_calibration(args.calibration)
    data = json.loads(Path(args.calibration).read_text(encoding="utf-8"))
    status = str(data.get("calibration_status", "UNSPECIFIED"))
    if args.require_measured and not status.startswith("MEASURED"):
        raise SystemExit(f"calibration is not measured: {status}")
    evidence = data.get("fit_evidence", {})
    rmse = float(evidence.get("horizontal_rmse_px", math.inf)) if isinstance(evidence, dict) else math.inf
    if args.require_measured and (not math.isfinite(rmse) or rmse > args.max_horizontal_rmse_px):
        raise SystemExit(f"horizontal projection RMSE is not accepted: {rmse}")
    print(json.dumps({"valid": True, "side": calibration.side, "status": status, "horizontal_rmse_px": rmse}, separators=(",", ":")))


if __name__ == "__main__":
    main()
