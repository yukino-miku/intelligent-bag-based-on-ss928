from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def tracked_files() -> list[Path]:
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [ROOT / item.decode() for item in output.split(b"\0") if item]


def validate_line_endings(files: list[Path]) -> None:
    suffixes = {".sh", ".service", ".timer", ".network"}
    failures = [str(path.relative_to(ROOT)) for path in files if path.suffix in suffixes and b"\r\n" in path.read_bytes()]
    if failures:
        raise SystemExit("CRLF is forbidden in Linux deployment files: " + ", ".join(failures))


def validate_manifest() -> None:
    path = ROOT / "00_admin/sanda-upstream-import-manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["source_commit"] != "970351c84a12f3219e7910ee488ac5ff579d6f98":
        raise SystemExit("unexpected upstream source commit")
    required = {"source_repo", "source_commit", "source_path", "source_blob_sha", "destination_path", "action", "reason", "license_status", "tests"}
    for index, item in enumerate(data["items"]):
        missing = required - set(item)
        if missing:
            raise SystemExit(f"manifest item {index} missing {sorted(missing)}")


def validate_cloud_examples() -> None:
    uploader = json.loads((ROOT / "06_software/board_runtime/cloud_uploader/config.example.json").read_text(encoding="utf-8"))
    if uploader["enabled"] or uploader["device_id"]:
        raise SystemExit("Cloud uploader example must be disabled and have no device id")
    cloud_js = (ROOT / "06_software/mobile/ssminiprogram/miniprogram/config/cloud.example.js").read_text(encoding="utf-8")
    for pattern in (r'envId:\s*"[^\"]+"', r'deviceId:\s*"[^\"]+"'):
        if re.search(pattern, cloud_js):
            raise SystemExit("Cloud mini program example contains a fixed environment or device id")


def validate_secrets(files: list[Path]) -> None:
    patterns = (
        re.compile(br"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(br"(?i)(?:hmac_secret|cloud_secret|private_key)\s*[:=]\s*['\"][^'\"]{12,}"),
    )
    failures = []
    for path in files:
        if path.stat().st_size > 2 * 1024 * 1024:
            continue
        data = path.read_bytes()
        if any(pattern.search(data) for pattern in patterns):
            failures.append(str(path.relative_to(ROOT)))
    if failures:
        raise SystemExit("possible committed secret: " + ", ".join(failures))


def main() -> None:
    files = tracked_files()
    validate_line_endings(files)
    validate_manifest()
    validate_cloud_examples()
    validate_secrets(files)
    print("hardware refresh repository policy passed")


if __name__ == "__main__":
    main()
