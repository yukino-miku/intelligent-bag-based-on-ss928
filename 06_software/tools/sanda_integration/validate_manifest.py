#!/usr/bin/env python3
"""Validate that the sanda audit manifest exactly covers a Git tree."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path, PurePosixPath
import sys

from generate_manifest import ACTIONS, BlobReader, lfs_metadata, source_entries


REQUIRED_FIELDS = [
    "source_path",
    "file_type",
    "size",
    "sha256",
    "purpose",
    "related_module",
    "destination_path",
    "action",
    "reason",
    "test_status",
]


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != REQUIRED_FIELDS:
            raise ValueError(f"unexpected manifest columns: {reader.fieldnames!r}")
        return list(reader)


def validate(source_repo: Path, source_ref: str, target_repo: Path, manifest: Path) -> dict[str, int]:
    entries = source_entries(source_repo, source_ref)
    rows = load_rows(manifest)
    errors: list[str] = []

    source_paths = [entry[0] for entry in entries]
    manifest_paths = [row["source_path"] for row in rows]
    if len(manifest_paths) != len(set(manifest_paths)):
        errors.append("manifest contains duplicate source_path values")
    missing = sorted(set(source_paths) - set(manifest_paths))
    extra = sorted(set(manifest_paths) - set(source_paths))
    if missing:
        errors.append(f"manifest misses {len(missing)} source paths; first={missing[0]}")
    if extra:
        errors.append(f"manifest has {len(extra)} extra paths; first={extra[0]}")

    entry_by_path = {path: (object_id, size) for path, object_id, size in entries}
    reader = BlobReader(source_repo)
    blob_cache: dict[str, tuple[str, int]] = {}
    try:
        for row in rows:
            source_path = row["source_path"]
            if source_path not in entry_by_path:
                continue
            action = row["action"]
            if action not in ACTIONS:
                errors.append(f"{source_path}: invalid action {action!r}")
            for field in ("file_type", "sha256", "purpose", "related_module", "reason", "test_status"):
                if not row[field].strip():
                    errors.append(f"{source_path}: empty {field}")
            destination = row["destination_path"].strip()
            if destination:
                destination_path = PurePosixPath(destination)
                if destination_path.is_absolute() or ".." in destination_path.parts:
                    errors.append(f"{source_path}: unsafe destination {destination}")
                if destination_path.parts and destination_path.parts[0] in {"work", "skills"}:
                    errors.append(f"{source_path}: source layout leaked into destination {destination}")
            if action in {"KEEP_EXISTING", "PORT", "MERGE", "MOVE"} and not destination:
                errors.append(f"{source_path}: {action} requires destination_path")
            if action in {"KEEP_EXISTING", "PORT", "MERGE", "MOVE"} and destination:
                if not (target_repo / Path(destination)).is_file():
                    errors.append(f"{source_path}: target landing is missing: {destination}")

            object_id, git_size = entry_by_path[source_path]
            expected = blob_cache.get(object_id)
            if expected is None:
                content = reader.read(object_id)
                lfs = lfs_metadata(content)
                expected = lfs if lfs else (hashlib.sha256(content).hexdigest(), git_size)
                blob_cache[object_id] = expected
            expected_hash, expected_size = expected
            if row["sha256"].lower() != expected_hash:
                errors.append(f"{source_path}: sha256 mismatch")
            try:
                manifest_size = int(row["size"])
            except ValueError:
                errors.append(f"{source_path}: invalid size {row['size']!r}")
            else:
                if manifest_size != expected_size:
                    errors.append(f"{source_path}: size mismatch {manifest_size} != {expected_size}")
    finally:
        reader.close()

    if errors:
        preview = "\n".join(f"- {item}" for item in errors[:50])
        raise ValueError(f"manifest validation failed with {len(errors)} error(s):\n{preview}")

    counts = {action: 0 for action in sorted(ACTIONS)}
    for row in rows:
        counts[row["action"]] += 1
    return {"source_files": len(entries), "manifest_rows": len(rows), **counts}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--target-repo", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = validate(
            args.source_repo.resolve(),
            args.source_ref,
            args.target_repo.resolve(),
            args.manifest.resolve(),
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for key, value in result.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
