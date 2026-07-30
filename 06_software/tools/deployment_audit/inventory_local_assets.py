#!/usr/bin/env python3
"""Generate a reproducible local deployment-asset inventory without publishing file contents."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
from typing import Iterable


BINARY_EXTENSIONS = {
    ".pt", ".onnx", ".om", ".bin", ".so", ".a", ".o", ".elf", ".whl", ".deb", ".ko", ".img",
    ".tar", ".tgz", ".gz", ".zip",
}
CONFIG_EXTENSIONS = {".json", ".yaml", ".yml", ".service", ".sh"}
KEYWORDS = {
    "yolo", "vehicle", "detector", "runner", "acl", "ascend", "ss928", "aarch64", "mpp", "model",
    "camera", "calibration", "mr20", "bmi270", "tm6605", "ws73", "cloudbase", "smartbag", "deploy",
    "om_inspect",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def elf_info(path: Path) -> tuple[str, str]:
    try:
        header = path.read_bytes()[:64]
    except OSError:
        return "unknown", "unreadable"
    if len(header) < 20 or header[:4] != b"\x7fELF":
        return "not-applicable", path.suffix.lower().lstrip(".") or "data"
    endian = "<" if header[5] == 1 else ">"
    machine = struct.unpack_from(endian + "H", header, 18)[0]
    architecture = {62: "x86_64", 183: "AArch64", 40: "ARM"}.get(machine, f"ELF-machine-{machine}")
    bits = "64" if header[4] == 2 else "32"
    return architecture, f"ELF{bits}"


def candidate(path: Path) -> bool:
    extension = path.suffix.lower()
    if extension in BINARY_EXTENSIONS:
        return True
    lowered = path.as_posix().lower()
    has_keyword = any(keyword in lowered for keyword in KEYWORDS)
    return (extension in CONFIG_EXTENSIONS and has_keyword) or (not extension and has_keyword)


def iter_files(root: Path) -> Iterable[Path]:
    for directory, names, filenames in os.walk(root):
        names[:] = [name for name in names if name not in {".git", "node_modules", "__pycache__", ".venv"}]
        base = Path(directory)
        for filename in filenames:
            path = base / filename
            if candidate(path):
                yield path


def git_paths(repository: Path) -> tuple[set[str], set[str]]:
    tracked_output = subprocess.check_output(["git", "ls-files", "-z"], cwd=repository)
    tracked = {item.decode("utf-8", "surrogateescape") for item in tracked_output.split(b"\0") if item}
    status_output = subprocess.check_output(
        ["git", "status", "--short", "--ignored", "-z", "--untracked-files=all"], cwd=repository
    )
    ignored: set[str] = set()
    parts = [item for item in status_output.split(b"\0") if item]
    for item in parts:
        decoded = item.decode("utf-8", "surrogateescape")
        if decoded.startswith("!! "):
            ignored.add(decoded[3:])
    return tracked, ignored


def classify(root_id: str, relative: str, tracked: bool) -> tuple[str, str, str, str]:
    lowered = relative.lower()
    if root_id == "parent_tmp":
        return "temporary clone/build output", "inherits source terms; not selected", "LOCAL_ONLY", "local discovery only"
    if root_id in {"repo_archive", "parent_backup"}:
        return "vendor/archive/local backup", "redistribution not established", "DO_NOT_DISTRIBUTE", "local discovery only"
    if lowered == "09_deliverables/board_deploy/models/vehicle-detector.om":
        return (
            "Ultralytics YOLO11n SS928 release conversion",
            "AGPL-3.0-only; see MODEL_LICENSES.md",
            "GIT",
            "static model/runner contract PASS; board ACL PENDING",
        )
    if "09_deliverables/board_deploy/bin/aarch64" in lowered:
        return "project source build", "AGPL-3.0-only", "GIT", "host ELF/native PASS; board ACL PENDING"
    if lowered.endswith("yolo11n_ss928.om") or lowered.endswith("yolo11n_640.pt") or lowered.endswith("yolo11n_640.onnx"):
        decision = "GIT" if tracked else "LOCAL_ONLY"
        return "Ultralytics YOLO11n conversion set", "AGPL-3.0-only or separately licensed enterprise", decision, "PT/ONNX PASS; ATC PASS; board OM PENDING"
    if "sdk" in lowered or "toolchain" in lowered:
        return "vendor/archive/local backup", "redistribution not established", "DO_NOT_DISTRIBUTE", "local discovery only"
    if tracked:
        return "project repository", "AGPL-3.0-only or documented third-party terms", "GIT", "covered by repository tests where applicable"
    return "local generated or runtime asset", "unknown; manual review required", "LOCAL_ONLY", "no portable success claim"


def sdk_match(relative: str) -> str:
    lowered = relative.lower()
    if "v2.0.2.2" in lowered:
        return "SS928V100 SDK V2.0.2.2"
    if "v2.0.2.3" in lowered:
        return "SS928V100 SDK V2.0.2.3"
    if "mix210" in lowered:
        return "aarch64-mix210 toolchain; board ABI validation required"
    if "ss928" in lowered or "svp_nnn" in lowered:
        return "SS928 family; exact image match requires validation"
    return "not established"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--parent-tmp", type=Path)
    parser.add_argument("--parent-backup", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    repository = args.repository.resolve()
    tracked, ignored = git_paths(repository)
    roots: list[tuple[str, Path]] = []
    if (repository / "10_archive").is_dir():
        roots.append(("repo_archive", repository / "10_archive"))
    roots.append(("repository", repository))
    if args.parent_tmp and args.parent_tmp.is_dir():
        roots.append(("parent_tmp", args.parent_tmp.resolve()))
    if args.parent_backup and args.parent_backup.is_dir():
        roots.append(("parent_backup", args.parent_backup.resolve()))

    seen: set[Path] = set()
    records: list[dict[str, object]] = []
    for root_id, root in roots:
        for path in iter_files(root):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            relative = path.relative_to(root).as_posix()
            repository_relative = path.relative_to(repository).as_posix() if path.is_relative_to(repository) else ""
            is_tracked = repository_relative in tracked
            is_ignored = repository_relative in ignored or any(
                repository_relative.startswith(value.rstrip("/") + "/") for value in ignored if value.endswith("/")
            )
            architecture, file_format = elf_info(path)
            source, license_status, distribution, evidence = classify(root_id, relative, is_tracked)
            records.append(
                {
                    "root": root_id,
                    "path": relative,
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256(path),
                    "architecture": architecture,
                    "file_format": file_format,
                    "git_tracked": is_tracked,
                    "git_ignored": is_ignored,
                    "source": source,
                    "license_status": license_status,
                    "distribution_decision": distribution,
                    "sdk_or_image_match": sdk_match(relative),
                    "success_evidence": evidence,
                }
            )
    records.sort(key=lambda item: (str(item["root"]), str(item["path"])))
    summary = {
        "candidate_file_count": len(records),
        "total_bytes": sum(int(item["size_bytes"]) for item in records),
        "model_count": sum(Path(str(item["path"])).suffix.lower() in {".pt", ".onnx", ".om"} for item in records),
        "elf_count": sum(str(item["file_format"]).startswith("ELF") for item in records),
        "tracked_count": sum(bool(item["git_tracked"]) for item in records),
        "ignored_count": sum(bool(item["git_ignored"]) for item in records),
        "license_blocked_or_do_not_distribute": sum(
            item["distribution_decision"] in {"LICENSE_BLOCKED", "DO_NOT_DISTRIBUTE"} for item in records
        ),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "local-deployment-asset-inventory.json"
    csv_path = args.output_dir / "local-deployment-asset-inventory.csv"
    md_path = args.output_dir / "local-deployment-asset-inventory.md"
    json_path.write_text(
        json.dumps({"summary": summary, "assets": records}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with csv_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=list(records[0]) if records else ["path"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(records)
    md_path.write_text(
        "# 本地部署资产清单\n\n"
        "> 由 `inventory_local_assets.py` 生成。路径使用匿名 root 标识，不写入电脑用户名或绝对路径；清单不复制资产内容。\n\n"
        + "\n".join(f"- `{key}`: {value}" for key, value in summary.items())
        + "\n\n## 处置结论\n\n"
        "- `GIT`: 项目原创内容及按 AGPL-3.0-only 分发的正式 YOLO11n 转换资产。\n"
        "- `LOCAL_ONLY`: 未被选为正式交付物的模型副本、板端日志和运行生成物。\n"
        "- `DO_NOT_DISTRIBUTE`: 厂商 SDK、工具链、系统镜像和备份，仅登记哈希。\n"
        "- 厂商许可和第三方归属仍以 `THIRD_PARTY_NOTICES.md` 为准。\n\n"
        "完整逐文件字段见同目录 CSV/JSON。自动许可分类是保守初筛，不能替代法律审查。\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
