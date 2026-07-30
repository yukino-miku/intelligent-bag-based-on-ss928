#!/usr/bin/env python3
"""Compare reference and board-runner detection JSON without requiring YOLO."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def iou(left: list[float], right: list[float]) -> float:
    x1, y1 = max(left[0], right[0]), max(left[1], right[1])
    x2, y2 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    left_area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    right_area = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    return intersection / max(left_area + right_area - intersection, 1e-9)


def detections(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("detection payload must be an object or list")
    values = payload.get("detections", payload.get("pt"))
    if not isinstance(values, list):
        raise ValueError("payload does not contain a detections list")
    return values


def compare(reference: list[dict[str, Any]], candidate: list[dict[str, Any]], minimum_iou: float) -> dict[str, Any]:
    unused = set(range(len(candidate)))
    matches: list[dict[str, Any]] = []
    for ref_index, ref in enumerate(reference):
        options = [
            (iou([float(x) for x in ref["bbox"]], [float(x) for x in candidate[index]["bbox"]]), index)
            for index in unused
            if int(candidate[index]["class_id"]) == int(ref["class_id"])
        ]
        if not options:
            continue
        overlap, candidate_index = max(options)
        if overlap < minimum_iou:
            continue
        unused.remove(candidate_index)
        matches.append(
            {
                "reference_index": ref_index,
                "candidate_index": candidate_index,
                "class_id": int(ref["class_id"]),
                "iou": overlap,
                "confidence_delta": float(candidate[candidate_index]["confidence"]) - float(ref["confidence"]),
            }
        )
    return {
        "reference_count": len(reference),
        "candidate_count": len(candidate),
        "matched_count": len(matches),
        "unmatched_reference": len(reference) - len(matches),
        "unmatched_candidate": len(candidate) - len(matches),
        "mean_iou": sum(item["iou"] for item in matches) / len(matches) if matches else 0.0,
        "matches": matches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--minimum-iou", type=float, default=0.5)
    parser.add_argument("--require-match", action="store_true")
    args = parser.parse_args()
    reference = detections(json.loads(args.reference.read_text(encoding="utf-8")))
    candidate_line = next(line for line in args.candidate.read_text(encoding="utf-8").splitlines() if line.strip())
    candidate = detections(json.loads(candidate_line))
    result = compare(reference, candidate, args.minimum_iou)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.require_match and result["matched_count"] == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
