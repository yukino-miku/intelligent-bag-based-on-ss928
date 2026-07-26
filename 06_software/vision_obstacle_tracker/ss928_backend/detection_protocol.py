from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any


@dataclass(frozen=True)
class NativeDetection:
    class_id: int
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class NativeDetectionFrame:
    frame_index: int
    detections: tuple[NativeDetection, ...]


def parse_detection_jsonl(line: str) -> NativeDetectionFrame:
    payload = json.loads(line)
    if not isinstance(payload, dict) or payload.get("type") != "detections":
        raise ValueError("native detector record must have type=detections")
    frame_index = int(payload["frame_index"])
    if frame_index < 0:
        raise ValueError("frame_index must be non-negative")
    detections: list[NativeDetection] = []
    for item in payload.get("detections", []):
        if not isinstance(item, dict):
            raise ValueError("each detection must be an object")
        bbox_data = item.get("bbox")
        if not isinstance(bbox_data, list) or len(bbox_data) != 4:
            raise ValueError("detection bbox must contain x1,y1,x2,y2")
        bbox = tuple(float(value) for value in bbox_data)
        confidence = float(item["confidence"])
        if not all(math.isfinite(value) for value in (*bbox, confidence)):
            raise ValueError("detection values must be finite")
        if not 0.0 <= confidence <= 1.0 or bbox[2] < bbox[0] or bbox[3] < bbox[1]:
            raise ValueError("invalid confidence or bbox geometry")
        detections.append(
            NativeDetection(
                class_id=int(item["class_id"]),
                class_name=str(item["class_name"]),
                confidence=confidence,
                bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
            )
        )
    return NativeDetectionFrame(frame_index, tuple(detections))
