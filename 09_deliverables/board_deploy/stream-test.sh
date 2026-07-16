#!/bin/sh
set -eu

HOST=${1:-127.0.0.1}
PORT=${2:-8080}
BASE="http://$HOST:$PORT"
OUT=${TMPDIR:-/tmp}/smartbag-stream-test
mkdir -p "$OUT"

curl --fail --silent --show-error "$BASE/api/v1/status"
printf '\n'
curl --fail --silent --show-error "$BASE/api/v1/cameras"
printf '\n'
curl --fail --silent --show-error "$BASE/api/v1/camera/left/snapshot.jpg?view=overlay" -o "$OUT/left.jpg"
curl --fail --silent --show-error "$BASE/api/v1/camera/right/snapshot.jpg?view=overlay" -o "$OUT/right.jpg"
echo "Snapshots saved to $OUT for local inspection."
