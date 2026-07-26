#!/usr/bin/env python3
import argparse
import hashlib
import json
import math


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_ppm(path):
    with open(path, "rb") as handle:
        if handle.readline().strip() != b"P6":
            raise ValueError("expected P6 PPM")
        dimensions = handle.readline().split()
        while dimensions and dimensions[0].startswith(b"#"):
            dimensions = handle.readline().split()
        width, height = map(int, dimensions)
        if handle.readline().strip() != b"255":
            raise ValueError("expected max value 255")
        pixels = handle.read()
    if len(pixels) != width * height * 3:
        raise ValueError("PPM pixel size mismatch")
    return width, height, pixels


def clamp_u8(value):
    return max(0, min(255, value))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("nv12")
    parser.add_argument("letterbox_ppm")
    parser.add_argument("--json")
    args = parser.parse_args()
    width = 640
    height = 640
    y_bytes = width * height
    with open(args.nv12, "rb") as handle:
        raw = handle.read()
    if len(raw) != y_bytes * 3 // 2:
        raise ValueError(f"expected 614400 input bytes, got {len(raw)}")
    y_plane = raw[:y_bytes]
    uv_plane = raw[y_bytes:]
    ppm_width, ppm_height, expected_rgb = read_ppm(args.letterbox_ppm)
    if (ppm_width, ppm_height) != (width, height):
        raise ValueError("letterbox PPM dimensions mismatch")

    squared_error = 0
    absolute_error = 0
    max_absolute_error = 0
    channel_absolute = [0, 0, 0]
    for y in range(height):
        uv_row = (y // 2) * width
        for x in range(width):
            yy = y_plane[y * width + x]
            uv = uv_row + (x & ~1)
            uu = uv_plane[uv] - 128
            vv = uv_plane[uv + 1] - 128
            # Exact static-AIPP CSC coefficients queried from this OM.  Rows
            # are R, G, B for its YUV420SP_U8 -> RGB conversion.
            actual = (
                clamp_u8((256 * yy + 359 * vv) >> 8),
                clamp_u8((256 * yy - 88 * uu - 183 * vv) >> 8),
                clamp_u8((256 * yy + 454 * uu) >> 8),
            )
            base = (y * width + x) * 3
            for channel in range(3):
                difference = abs(actual[channel] - expected_rgb[base + channel])
                absolute_error += difference
                channel_absolute[channel] += difference
                squared_error += difference * difference
                max_absolute_error = max(max_absolute_error, difference)

    samples = width * height * 3
    mse = squared_error / samples
    top_y = y_plane[:78 * width]
    bottom_y = y_plane[(78 + 484) * width:]
    top_uv = uv_plane[:39 * width]
    bottom_uv = uv_plane[(39 + 242) * width:]
    result = {
        "input": args.nv12,
        "sha256": sha256(args.nv12),
        "bytes": len(raw),
        "format": "NV12 YUV420SP UV, BT.601 wide/full range",
        "width": width,
        "height": height,
        "stride_y": width,
        "stride_uv": width,
        "planes": {
            "y": {"offset": 0, "bytes": len(y_plane), "min": min(y_plane), "max": max(y_plane), "mean": sum(y_plane) / len(y_plane)},
            "uv": {"offset": len(y_plane), "bytes": len(uv_plane), "min": min(uv_plane), "max": max(uv_plane), "mean": sum(uv_plane) / len(uv_plane)},
        },
        "letterbox_border": {
            "top_y_all_114": all(value == 114 for value in top_y),
            "bottom_y_all_114": all(value == 114 for value in bottom_y),
            "top_uv_all_128": all(value == 128 for value in top_uv),
            "bottom_uv_all_128": all(value == 128 for value in bottom_uv),
        },
        "aipp_csc_reconstruction_vs_letterbox_rgb": {
            "reference": args.letterbox_ppm,
            "mean_absolute_error": absolute_error / samples,
            "channel_mean_absolute_error_rgb": [value / (width * height) for value in channel_absolute],
            "max_absolute_error": max_absolute_error,
            "mse": mse,
            "psnr_db": float("inf") if mse == 0 else 10.0 * math.log10(255.0 * 255.0 / mse),
        },
        "verdict": "locked bytes are a dense 640x640 full-range NV12 representation of the fixed letterboxed bus image",
    }
    rendered = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)
    print(rendered)
    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered + "\n")


if __name__ == "__main__":
    main()
