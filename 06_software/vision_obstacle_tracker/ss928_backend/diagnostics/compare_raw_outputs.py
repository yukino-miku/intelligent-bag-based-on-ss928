#!/usr/bin/env python3
import argparse
import array
import hashlib
import json
import math
import sys


def load_f32(path):
    values = array.array("f")
    with open(path, "rb") as handle:
        values.fromfile(handle, __import__("os").path.getsize(path) // values.itemsize)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stats(path, values):
    finite = [value for value in values if math.isfinite(value)]
    return {
        "path": path,
        "bytes": len(values) * 4,
        "elements": len(values),
        "sha256": sha256(path),
        "min": min(finite) if finite else None,
        "max": max(finite) if finite else None,
        "mean": math.fsum(finite) / len(finite) if finite else None,
        "nonzero_elements": sum(value != 0.0 for value in values),
        "nonfinite_elements": len(values) - len(finite),
        "first_16": list(values[:16]),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("reference")
    parser.add_argument("current")
    parser.add_argument("--shape", default="1,84,8400")
    parser.add_argument("--json")
    args = parser.parse_args()

    reference = load_f32(args.reference)
    current = load_f32(args.current)
    result = {
        "shape": [int(part) for part in args.shape.split(",")],
        "reference": stats(args.reference, reference),
        "current": stats(args.current, current),
        "same_element_count": len(reference) == len(current),
    }
    if len(reference) == len(current):
        differences = [abs(left - right) for left, right in zip(reference, current)]
        result["comparison"] = {
            "bitwise_equal": result["reference"]["sha256"] == result["current"]["sha256"],
            "different_elements": sum(left != right for left, right in zip(reference, current)),
            "max_absolute_error": max(differences) if differences else 0.0,
            "mean_absolute_error": math.fsum(differences) / len(differences) if differences else 0.0,
        }
    else:
        result["comparison"] = None

    rendered = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)
    print(rendered)
    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered + "\n")
    return 0 if result.get("comparison") is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
