#!/usr/bin/env python3
"""Compare YOLO PT and ONNX detections on the same still image."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


TARGET_CLASS_IDS = [1, 2, 3, 5, 7]


def serialize(result: object) -> list[dict[str, object]]:
    boxes = result.boxes  # type: ignore[attr-defined]
    names = result.names  # type: ignore[attr-defined]
    return [
        {
            "class_id": int(class_id),
            "class_name": str(names[int(class_id)]),
            "confidence": round(float(confidence), 6),
            "bbox": [round(float(value), 3) for value in bbox],
        }
        for class_id, confidence, bbox in zip(
            boxes.cls.cpu().tolist(), boxes.conf.cpu().tolist(), boxes.xyxy.cpu().tolist()
        )
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--pt", type=Path, required=True)
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confidence", type=float, default=0.25)
    args = parser.parse_args()

    from ultralytics import YOLO

    results: dict[str, list[dict[str, object]]] = {}
    for key, model_path in (("pt", args.pt), ("onnx", args.onnx)):
        model = YOLO(str(model_path), task="detect")
        prediction = model.predict(
            str(args.image), imgsz=640, conf=args.confidence, classes=TARGET_CLASS_IDS, verbose=False
        )[0]
        results[key] = serialize(prediction)
    payload = {
        "type": "model_parity_reference",
        "image_name": args.image.name,
        "confidence": args.confidence,
        "pt": results["pt"],
        "onnx": results["onnx"],
        "detections": results["pt"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pt_count": len(results["pt"]), "onnx_count": len(results["onnx"]), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
