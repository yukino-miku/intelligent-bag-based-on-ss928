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
    parser.add_argument("--max-error-px", type=float, default=80.0)
    parser.add_argument("--hardware-discovery", type=Path)
    parser.add_argument("--radar-config", type=Path)
    parser.add_argument("--require-measured", action="store_true")
    args = parser.parse_args()
    calibration = load_fusion_calibration(args.calibration)
    data = json.loads(Path(args.calibration).read_text(encoding="utf-8"))
    status = str(data.get("calibration_status", "UNSPECIFIED"))
    if args.require_measured and not status.startswith("MEASURED"):
        raise SystemExit(f"calibration is not measured: {status}")
    evidence = data.get("fit_evidence", {})
    rmse = float(evidence.get("horizontal_rmse_px", math.inf)) if isinstance(evidence, dict) else math.inf
    max_error = float(evidence.get("max_error_px", math.inf)) if isinstance(evidence, dict) else math.inf
    if args.require_measured and (not math.isfinite(rmse) or rmse > args.max_horizontal_rmse_px):
        raise SystemExit(f"horizontal projection RMSE is not accepted: {rmse}")
    if args.require_measured and (not math.isfinite(max_error) or max_error > args.max_error_px):
        raise SystemExit(f"horizontal projection max error is not accepted: {max_error}")
    if args.hardware_discovery:
        discovery = json.loads(args.hardware_discovery.read_text(encoding="utf-8"))
        assigned = discovery.get(calibration.side, {})
        current_id = str(assigned.get("id_path", "")) if isinstance(assigned, dict) else ""
        expected_id = str(data.get("hardware_id", ""))
        if not expected_id or expected_id != current_id:
            raise SystemExit(
                f"calibration hardware identity mismatch: expected={expected_id or 'missing'} current={current_id or 'missing'}"
            )
    if args.radar_config:
        radar_config = json.loads(args.radar_config.read_text(encoding="utf-8"))
        radars = [
            item for item in radar_config.get("radars", [])
            if item.get("side") == calibration.side and item.get("enabled", True)
        ]
        if len(radars) != 1:
            raise SystemExit(f"expected exactly one enabled {calibration.side} radar, found {len(radars)}")
        expected_radar = str(data.get("radar_name", ""))
        current_radar = str(radars[0].get("name", ""))
        if not expected_radar or expected_radar != current_radar:
            raise SystemExit(
                f"calibration radar identity mismatch: expected={expected_radar or 'missing'} current={current_radar or 'missing'}"
            )
    print(json.dumps({
        "valid": True,
        "side": calibration.side,
        "status": status,
        "horizontal_rmse_px": rmse,
        "max_error_px": max_error,
        "hardware_id": data.get("hardware_id", ""),
        "radar_name": data.get("radar_name", ""),
    }, separators=(",", ":")))


if __name__ == "__main__":
    main()
