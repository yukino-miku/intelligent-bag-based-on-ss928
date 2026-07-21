#!/usr/bin/env python3
"""Create a deterministic absolute-path image list for ATC calibration."""

from __future__ import annotations

import argparse
from pathlib import Path


SUPPORTED_SUFFIXES = {".jpg", ".jpeg"}


def calibration_images(source: Path, count: int) -> list[Path]:
    images = sorted(
        path.resolve()
        for path in source.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )
    if len(images) < count:
        raise ValueError(f"need at least {count} JPEG images, found {len(images)} in {source}")
    return images[:count]


def write_image_list(source: Path, output: Path, count: int) -> list[Path]:
    images = calibration_images(source, count)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(f"{path}\n" for path in images), encoding="utf-8")
    return images


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="directory containing representative JPEGs")
    parser.add_argument("output", type=Path, help="image_ref_list.txt output path")
    parser.add_argument("--count", type=int, default=20, help="number of images (default: 20)")
    args = parser.parse_args()
    if not args.source.is_dir():
        parser.error(f"source directory does not exist: {args.source}")
    if args.count <= 0:
        parser.error("--count must be greater than zero")

    try:
        images = write_image_list(args.source, args.output, args.count)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"wrote {len(images)} calibration images to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
