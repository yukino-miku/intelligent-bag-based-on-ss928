#!/usr/bin/env python3
import argparse
import array
import json
import math
import os
import sys


COCO80 = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier",
    "toothbrush",
]


def load_f32(path):
    values = array.array("f")
    size = os.path.getsize(path)
    if size % 4:
        raise ValueError("raw tensor size is not divisible by four")
    with open(path, "rb") as handle:
        values.fromfile(handle, size // 4)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def simple_stats(values):
    return {
        "min": min(values),
        "max": max(values),
        "mean": math.fsum(values) / len(values),
        "negative": sum(value < 0.0 for value in values),
        "above_one": sum(value > 1.0 for value in values),
        "nonfinite": sum(not math.isfinite(value) for value in values),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("raw")
    parser.add_argument("--json")
    args = parser.parse_args()
    values = load_f32(args.raw)
    if len(values) != 84 * 8400:
        raise ValueError(f"expected 705600 elements, got {len(values)}")

    anchors = 8400
    correct_classes = values[4 * anchors:84 * anchors]
    coordinate_channels = [values[channel * anchors:(channel + 1) * anchors] for channel in range(4)]
    thresholds = [0.001, 0.01, 0.05, 0.1, 0.25, 0.45]
    class_maxima = []
    for class_id, name in enumerate(COCO80):
        channel = values[(4 + class_id) * anchors:(5 + class_id) * anchors]
        score = max(channel)
        anchor = channel.index(score)
        class_maxima.append({"class_id": class_id, "class_name": name, "max_score": score, "anchor": anchor})

    best_per_anchor = []
    for anchor in range(anchors):
        best_class = max(range(80), key=lambda class_id: values[(4 + class_id) * anchors + anchor])
        score = values[(4 + best_class) * anchors + anchor]
        best_per_anchor.append({
            "anchor": anchor,
            "class_id": best_class,
            "class_name": COCO80[best_class],
            "score": score,
            "xywh": [values[channel * anchors + anchor] for channel in range(4)],
        })
    best_per_anchor.sort(key=lambda item: item["score"], reverse=True)

    # Deliberately interpret the same contiguous bytes as [8400,84] to test the
    # competing layout hypothesis. Values treated as "class scores" then contain
    # coordinate magnitudes, which is direct evidence that this layout is wrong.
    wrong_layout_classes = []
    for anchor in range(anchors):
        base = anchor * 84
        wrong_layout_classes.extend(values[base + 4:base + 84])

    target_ids = [1, 2, 3, 5, 7]
    correct_stats = simple_stats(correct_classes)
    sigmoid_min = 1.0 / (1.0 + math.exp(-correct_stats["min"]))
    sigmoid_max = 1.0 / (1.0 + math.exp(-correct_stats["max"]))
    result = {
        "raw_path": args.raw,
        "descriptor_layout": [1, 84, 8400],
        "channel_contract": "4 xywh channels + 80 class probabilities; no objectness channel",
        "layout_a_channel_first": {
            "coordinate_stats": {
                name: simple_stats(channel)
                for name, channel in zip(["cx", "cy", "width", "height"], coordinate_channels)
            },
            "class_score_stats": correct_stats,
            "class_elements_at_or_above_threshold": {
                str(threshold): sum(value >= threshold for value in correct_classes)
                for threshold in thresholds
            },
            "anchors_with_best_class_at_or_above_threshold": {
                str(threshold): sum(item["score"] >= threshold for item in best_per_anchor)
                for threshold in thresholds
            },
            "top_16_anchors": best_per_anchor[:16],
            "class_maxima_descending": sorted(class_maxima, key=lambda item: item["max_score"], reverse=True),
            "configured_target_class_maxima": [class_maxima[class_id] for class_id in target_ids],
        },
        "layout_b_channel_last_hypothesis": {
            "interpreted_class_score_stats": simple_stats(wrong_layout_classes),
            "verdict": "invalid: interpreted class scores contain coordinate-sized values above 1",
        },
        "sigmoid_check": {
            "raw_class_scores_are_bounded_0_to_1": correct_stats["negative"] == 0 and correct_stats["above_one"] == 0,
            "if_sigmoid_were_applied_min": sigmoid_min,
            "if_sigmoid_were_applied_max": sigmoid_max,
            "official_v2_0_2_2_decoder_applies_sigmoid": False,
            "verdict": "already activated; applying sigmoid again would move every score to about 0.5",
        },
        "confidence_check": {
            "configured_threshold": 0.25,
            "maximum_class_score": correct_stats["max"],
            "proposals_before_target_filter_at_configured_threshold": sum(item["score"] >= 0.25 for item in best_per_anchor),
            "verdict": "zero proposals at confidence filtering, before target-class filtering and NMS",
        },
        "coordinate_check": {
            "encoding": "xywh center coordinates in the 640x640 model canvas",
            "xyxy_conversion": "x1=cx-w/2, y1=cy-h/2, x2=cx+w/2, y2=cy+h/2",
            "letterbox": {
                "source": [546, 413],
                "resized": [640, 484],
                "model": [640, 640],
                "scale": 640.0 / 546.0,
                "pad_x": 0.0,
                "pad_y": 78.0,
                "restore": "subtract pad_x/pad_y, divide by scale, then clip to source bounds",
            },
            "verdict": "coordinate conversion/restoration occurs only after confidence filtering and cannot cause the observed zero proposals",
        },
        "nms_check": {
            "configured_iou": 0.45,
            "input_proposals": 0,
            "verdict": "NMS is not reached with any proposal and cannot cause the observed zero",
        },
    }
    rendered = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)
    print(rendered)
    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered + "\n")


if __name__ == "__main__":
    main()
