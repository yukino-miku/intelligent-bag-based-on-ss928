#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
VERSION=${1:-smartbag-v1.0.0-rc1}
REF=${2:-HEAD}
OUTPUT_DIR=${OUTPUT_DIR:-$SCRIPT_DIR}
PACKAGE_NAME="smartbag-ss928-${VERSION#smartbag-}"
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT INT TERM

mkdir -p "$OUTPUT_DIR" "$STAGING/$PACKAGE_NAME"
git -C "$REPO_ROOT" archive "$REF" | tar -xf - -C "$STAGING/$PACKAGE_NAME"

python3 "$STAGING/$PACKAGE_NAME/09_deliverables/board_deploy/verify_release_assets.py" \
    --runner "$STAGING/$PACKAGE_NAME/09_deliverables/board_deploy/bin/aarch64/ss928_detection_runner" \
    --runner-manifest "$STAGING/$PACKAGE_NAME/09_deliverables/board_deploy/bin/aarch64/runner-manifest.json"

COMMIT=$(git -C "$REPO_ROOT" rev-parse "$REF^{commit}")
python3 - "$STAGING/$PACKAGE_NAME" "$VERSION" "$COMMIT" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
files = []
for path in sorted(item for item in root.rglob("*") if item.is_file()):
    relative = path.relative_to(root).as_posix()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    files.append({"path": relative, "size_bytes": path.stat().st_size, "sha256": digest})
manifest = {
    "schema_version": 1,
    "version": sys.argv[2],
    "git_commit": sys.argv[3],
    "full_install_ready": False,
    "radar_only_static_ready": True,
    "model_included": False,
    "runner_included": True,
    "blocking_reason": "vehicle model license and SS928 board validation are unresolved",
    "files": files,
}
(root / "release-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

tar -czf "$OUTPUT_DIR/$PACKAGE_NAME.tar.gz" -C "$STAGING" "$PACKAGE_NAME"
python3 - "$OUTPUT_DIR/$PACKAGE_NAME.tar.gz" "$OUTPUT_DIR/SHA256SUMS" <<'PY'
import hashlib
from pathlib import Path
import sys
artifact = Path(sys.argv[1])
digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
Path(sys.argv[2]).write_text(f"{digest}  {artifact.name}\n", encoding="ascii")
print(f"{digest}  {artifact}")
PY
echo "Release bundle created. It supports honest radar-only installation; full visual mode remains blocked."
