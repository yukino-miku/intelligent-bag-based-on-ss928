#!/bin/sh
set -eu

SOURCE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT INT TERM

git clone --quiet --no-local "$SOURCE_ROOT" "$WORK/clone"
CLONE="$WORK/clone"
cd "$CLONE"

test -f 09_deliverables/board_deploy/models/vehicle-detector.om
RUNNER=09_deliverables/board_deploy/bin/aarch64/ss928_detection_runner
if ! test -x "$RUNNER"; then
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)
      git ls-files --stage -- "$RUNNER" | grep -Eq '^100755 '
      ;;
    *)
      echo "runner is not executable: $RUNNER" >&2
      exit 1
      ;;
  esac
fi
python3 09_deliverables/board_deploy/verify_release_assets.py \
  --model 09_deliverables/board_deploy/models/vehicle-detector.om \
  --model-manifest 09_deliverables/board_deploy/models/vehicle-detector.manifest.json \
  --runner 09_deliverables/board_deploy/bin/aarch64/ss928_detection_runner \
  --runner-manifest 09_deliverables/board_deploy/bin/aarch64/runner-manifest.json

SMARTBAG_ROOT_PREFIX="$WORK/full-root" ./install-on-ss928.sh \
  --full --offline --skip-optional --no-start --yes
SMARTBAG_ROOT_PREFIX="$WORK/radar-root" ./install-on-ss928.sh \
  --radar-only --offline --skip-optional --no-start --yes
SMARTBAG_ROOT_PREFIX="$WORK/radar-root" ./install-on-ss928.sh \
  --radar-only --offline --skip-optional --no-start --yes

printf '{"keep":true}\n' >"$WORK/radar-root/etc/smartbag/local-test.json"
mkdir -p "$WORK/radar-root/var/lib/smartbag/alarm-events"
printf '{}\n' >"$WORK/radar-root/var/lib/smartbag/alarm-events/keep.json"
SMARTBAG_ROOT_PREFIX="$WORK/radar-root" 09_deliverables/board_deploy/uninstall.sh
test -f "$WORK/radar-root/etc/smartbag/local-test.json"
test -f "$WORK/radar-root/var/lib/smartbag/alarm-events/keep.json"

OUTPUT_DIR="$WORK/release" 09_deliverables/releases/build-release.sh smartbag-v1.0.0-rc2 HEAD
(cd "$WORK/release" && sha256sum -c SHA256SUMS)
tar -tzf "$WORK/release/smartbag-ss928-v1.0.0-rc2.tar.gz" >"$WORK/archive.txt"
grep -q '/09_deliverables/board_deploy/models/vehicle-detector.om$' "$WORK/archive.txt"
grep -q '/09_deliverables/board_deploy/bin/aarch64/ss928_detection_runner$' "$WORK/archive.txt"
if grep -Eq '/(08_media|10_archive)/' "$WORK/archive.txt"; then
  echo "release archive contains excluded local media/archive data" >&2
  exit 1
fi

echo "Clean clone, model/runner, mock installs, uninstall retention, and release archive passed."
