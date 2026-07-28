from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Mapping

from mr20_radar.mr20_radar import MR20Target, RadarScan

try:
    from .fusion_runtime import RadarVisionFusionRuntime, build_fusion_runtime
    from .models import ClassificationFrame, VehicleDetection
except ImportError:
    from fusion_runtime import RadarVisionFusionRuntime, build_fusion_runtime
    from models import ClassificationFrame, VehicleDetection


class FusionReplay:
    def __init__(self, runtime: RadarVisionFusionRuntime) -> None:
        self.runtime = runtime

    def replay(self, records: Iterable[tuple[float, str, object]], realtime_scale: float = 0.0) -> None:
        previous_timestamp: float | None = None
        for timestamp, kind, payload in sorted(records, key=lambda item: item[0]):
            if realtime_scale > 0.0 and previous_timestamp is not None:
                time.sleep(max(0.0, timestamp - previous_timestamp) / realtime_scale)
            if kind == "scan":
                self.runtime.process_scan(payload)  # type: ignore[arg-type]
            elif kind == "classification":
                self.runtime.process_classification(payload)  # type: ignore[arg-type]
            previous_timestamp = timestamp


def load_replay_records(root: str | Path) -> tuple[tuple[float, str, object], ...]:
    root = Path(root)
    records: list[tuple[float, str, object]] = []
    for payload in _read_jsonl(root / "radar_scans.jsonl"):
        scan = RadarScan(
            radar_name=str(payload["radar_name"]),
            side=str(payload["side"]),
            measurement_count=int(payload["measurement_count"]),
            captured_mono_s=float(payload["captured_mono_s"]),
            targets=tuple(MR20Target(**item) for item in payload.get("targets", [])),
            expected_target_count=int(payload.get("expected_target_count", len(payload.get("targets", [])))),
            received_target_count=int(payload.get("received_target_count", len(payload.get("targets", [])))),
            unique_target_count=int(payload.get("unique_target_count", len(payload.get("targets", [])))),
            complete=bool(payload.get("complete", True)),
            completion_reason=str(payload.get("completion_reason", "replay")),
            missing_target_count=int(payload.get("missing_target_count", 0)),
            duplicate_target_count=int(payload.get("duplicate_target_count", 0)),
            measurement_sequence_gap=int(payload.get("measurement_sequence_gap", 0)),
            started_mono_s=float(payload.get("started_mono_s", payload["captured_mono_s"])),
        )
        records.append((scan.captured_mono_s, "scan", scan))
    for payload in _read_jsonl(root / "classification_frames.jsonl"):
        detections = tuple(
            VehicleDetection(
                detection_id=int(item["detection_id"]),
                class_id=int(item["class_id"]),
                class_name=str(item["class_name"]),
                confidence=float(item["confidence"]),
                bbox_xyxy=tuple(float(value) for value in item["bbox_xyxy"]),  # type: ignore[arg-type]
                bbox_center_x=float(item["bbox_center_x"]),
                bbox_center_y=float(item["bbox_center_y"]),
                bbox_bottom_x=float(item["bbox_bottom_x"]),
                bbox_bottom_y=float(item["bbox_bottom_y"]),
            )
            for item in payload.get("detections", [])
        )
        frame = ClassificationFrame(
            side=str(payload["side"]),
            frame_id=int(payload["frame_id"]),
            captured_mono_s=float(payload["captured_mono_s"]),
            image_width=int(payload["image_width"]),
            image_height=int(payload["image_height"]),
            detections=detections,
            camera_state=str(payload.get("camera_state", "REPLAY")),
            capture_latency_ms=float(payload.get("capture_latency_ms", 0.0)),
            inference_latency_ms=float(payload.get("inference_latency_ms", 0.0)),
            streamon_latency_ms=float(payload.get("streamon_latency_ms", 0.0)),
            first_frame_latency_ms=float(payload.get("first_frame_latency_ms", 0.0)),
            streamoff_latency_ms=float(payload.get("streamoff_latency_ms", 0.0)),
            association_latency_ms=float(payload.get("association_latency_ms", 0.0)),
        )
        records.append((frame.captured_mono_s, "classification", frame))
    return tuple(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay recorded radar scans and snapshot detections.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--record-dir", required=True)
    parser.add_argument("--realtime-scale", type=float, default=0.0)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    config = dict(config)
    config["snapshot_classifier"] = {**dict(config.get("snapshot_classifier", {})), "enabled": False}

    def emit(event) -> None:
        print(json.dumps({"type": "fused_alert", **event.__dict__}, ensure_ascii=False, separators=(",", ":")))

    runtime = build_fusion_runtime(config, emit)
    FusionReplay(runtime).replay(load_replay_records(args.record_dir), args.realtime_scale)


def _read_jsonl(path: Path) -> Iterable[Mapping[str, object]]:
    if not path.is_file():
        return ()
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        if isinstance(payload, dict):
            payload.pop("type", None)
            records.append(payload)
    return tuple(records)


if __name__ == "__main__":
    main()
