#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." 2>/dev/null && pwd || true)
SESSION_ID=${SESSION_ID:-$(date -u +%Y%m%dT%H%M%SZ)}
START_EPOCH_S=$(date +%s)
export START_EPOCH_S
if [ -n "$REPO_ROOT" ] && [ -d "$REPO_ROOT/08_media" ]; then
    SESSION="$REPO_ROOT/08_media/hardware_refresh_runs/$SESSION_ID"
else
    SESSION="/var/log/smartbag/hardware_refresh_runs/$SESSION_ID"
fi
mkdir -p "$SESSION"

for file in i2c-events.csv haptic-events.csv light-events.csv radar-frames.csv radar-targets.csv alert-events.csv actuator-events.csv controller-status.csv errors.log; do
    : >"$SESSION/$file"
done

python3 - "$SESSION/log-offsets.json" <<'PY'
import json, os, sys
paths = [
    "/var/log/smartbag/controller-events.jsonl",
    "/var/log/smartbag/actuator-events.jsonl",
    "/var/log/smartbag/mr20-right-rear.jsonl",
]
json.dump(
    {path: os.path.getsize(path) if os.path.exists(path) else 0 for path in paths},
    open(sys.argv[1], "w", encoding="utf-8"),
    indent=2,
    sort_keys=True,
)
PY

python3 - "$SESSION/hardware-inventory.json" <<'PY'
import glob, json, platform, subprocess, sys
def command(*args):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()
    except Exception as exc:
        return f"ERROR: {type(exc).__name__}: {exc}"
json.dump({
    "machine": platform.machine(),
    "platform": platform.platform(),
    "kernel": platform.release(),
    "python": platform.python_version(),
    "i2c_devices": glob.glob("/dev/i2c-*"),
    "ttyAMA4": glob.glob("/dev/ttyAMA4"),
    "interfaces": command("ip", "-brief", "address")
}, open(sys.argv[1], "w", encoding="utf-8"), indent=2, sort_keys=True)
PY
python3 - "$SESSION/pinmux.json" <<'PY'
import json, shutil, subprocess, sys
addresses = ["0x102F013c", "0x102F0140", "0x102F0110", "0x102F01EC"]
values = {}
if shutil.which("bspmm"):
    for address in addresses:
        try:
            values[address] = subprocess.check_output(["bspmm", address], text=True, stderr=subprocess.STDOUT).strip()
        except Exception as exc:
            values[address] = f"ERROR: {type(exc).__name__}: {exc}"
json.dump(values, open(sys.argv[1], "w", encoding="utf-8"), indent=2, sort_keys=True)
PY
ip address show >"$SESSION/network-status.txt" 2>&1

branch=$(git -C "$REPO_ROOT" branch --show-current 2>/dev/null || echo unknown)
sha=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)
python3 - "$SESSION/session.json" "$SESSION_ID" "$branch" "$sha" "$REPO_ROOT" <<'PY'
import hashlib, json, os, platform, subprocess, sys
path, session_id, branch, sha, repo_root = sys.argv[1:]
def load(path, fallback):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return fallback
def digest(path):
    try:
        return hashlib.sha256(open(path, "rb").read()).hexdigest()
    except Exception:
        return None
def command(*args):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()
    except Exception as exc:
        return f"ERROR: {type(exc).__name__}: {exc}"
hardware = load("/etc/smartbag/hardware.json", {})
mr20 = load("/etc/smartbag/mr20-radar.json", {})
mux = hardware.get("i2c_mux", {})
haptics = hardware.get("haptics", {})
lights = hardware.get("lights", {})
manifest_path = os.path.join(repo_root, "00_admin", "sanda-upstream-import-manifest.json")
data = {
    "session_id": session_id,
    "started_epoch_s": int(os.environ["START_EPOCH_S"]),
    "target_branch": branch,
    "target_sha": sha,
    "upstream_sha": "970351c84a12f3219e7910ee488ac5ff579d6f98",
    "import_manifest_sha256": digest(manifest_path),
    "board_model": platform.machine(),
    "os": platform.platform(),
    "kernel": platform.release(),
    "python": platform.python_version(),
    "config_sha256": digest("/etc/smartbag/config.json"),
    "hardware_profile": hardware.get("profile", "missing"),
    "i2c_mux_address": mux.get("address"),
    "i2c_mux_channels": mux.get("channels"),
    "tm6605_address": haptics.get("address"),
    "pwm_lights": {"left": lights.get("left"), "right": lights.get("right")},
    "mr20": mr20.get("radars", []),
    "eth0": command("ip", "-brief", "address", "show", "eth0"),
    "eth1": command("ip", "-brief", "address", "show", "eth1"),
    "physical_or_replay": "read_only_preflight",
    "vision": command("systemctl", "is-active", "smartbag-alert.service") == "active",
    "radar": bool(hardware.get("radar", {}).get("enabled", False)),
    "ble": not bool(hardware.get("ble", {}).get("disabled", False)),
    "cloud": load("/etc/smartbag/cloud-uploader.json", {}).get("enabled", False)
}
json.dump(data, open(path, "w", encoding="utf-8"), indent=2, sort_keys=True)
PY

set +e
"$SCRIPT_DIR/hardware-preflight.sh" >"$SESSION/preflight.log" 2>>"$SESSION/errors.log"
preflight_rc=$?
"$SCRIPT_DIR/mr20-network-preflight.sh" >"$SESSION/mr20-network.log" 2>>"$SESSION/errors.log"
mr20_rc=$?
set -e

DURATION_S=${DURATION_S:-0}
export DURATION_S
printf 'timestamp_s,cpu_load_1m,rss_kib,temperature_c,controller_state\n' >"$SESSION/controller-status.csv"
if [ "$DURATION_S" -gt 0 ] 2>/dev/null; then
    end=$(( $(date +%s) + DURATION_S ))
    while [ "$(date +%s)" -lt "$end" ]; do
        now=$(date +%s)
        load=$(cut -d' ' -f1 /proc/loadavg)
        pid=$(systemctl show -p MainPID --value smartbag-alert.service 2>/dev/null || echo 0)
        rss=0
        [ "$pid" -gt 0 ] 2>/dev/null && rss=$(awk '/VmRSS/{print $2}' "/proc/$pid/status" 2>/dev/null || echo 0)
        temp=""
        [ -r /sys/class/thermal/thermal_zone0/temp ] && temp=$(awk '{printf "%.1f", $1/1000}' /sys/class/thermal/thermal_zone0/temp)
        state=$(systemctl is-active smartbag-alert.service 2>/dev/null || true)
        printf '%s,%s,%s,%s,%s\n' "$now" "$load" "$rss" "$temp" "$state" >>"$SESSION/controller-status.csv"
        sleep 5
    done
fi

journalctl -u smartbag-alert.service -u smartbag-cloud-uploader.service \
    --since "@$START_EPOCH_S" --no-pager >>"$SESSION/errors.log" 2>&1 || true

python3 - "$SESSION/log-offsets.json" "$SESSION/alert-events.csv" "$SESSION/actuator-events.csv" "$SESSION/radar-targets.csv" <<'PY'
import csv, json, os, sys

offset_path, alert_csv, actuator_csv, radar_csv = sys.argv[1:]
offsets = json.load(open(offset_path, encoding="utf-8"))
sources = {
    "/var/log/smartbag/controller-events.jsonl": alert_csv,
    "/var/log/smartbag/actuator-events.jsonl": actuator_csv,
    "/var/log/smartbag/mr20-right-rear.jsonl": radar_csv,
}
for source, destination in sources.items():
    records = []
    try:
        with open(source, "r", encoding="utf-8", errors="replace") as handle:
            handle.seek(int(offsets.get(source, 0)))
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    records.append(value)
    except OSError:
        pass
    fields = sorted({key for record in records for key in record})
    with open(destination, "w", newline="", encoding="utf-8") as handle:
        if not fields:
            continue
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=True, separators=(",", ":"))
                if isinstance(value, (dict, list)) else value
                for key, value in record.items()
            })
PY

python3 - "$SESSION/summary.json" "$preflight_rc" "$mr20_rc" "$SESSION/errors.log" <<'PY'
import json, subprocess, sys
errors = open(sys.argv[4], encoding="utf-8", errors="replace").read()
error_lines = [
    line.lower() for line in errors.splitlines()
    if any(mark in line.lower() for mark in ("error", "warn", "fail", "eio"))
]
try:
    restarts = int(subprocess.check_output(
        ["systemctl", "show", "-p", "NRestarts", "--value", "smartbag-alert.service"],
        text=True,
    ).strip() or "0")
except Exception:
    restarts = None
result = {
    "hardware_preflight": "BOARD_TESTED" if int(sys.argv[2]) == 0 else "BLOCKED",
    "mr20_network": "BOARD_TESTED" if int(sys.argv[3]) == 0 else "BLOCKED",
    "i2c_mux": "NOT_RUN",
    "tm6605_physical": "NOT_RUN",
    "lights_physical": "NOT_RUN",
    "mr20_target_60b": "NOT_RUN",
    "cloudbase": "NOT_DEPLOYED",
    "monitor_duration_s": int(__import__("os").environ.get("DURATION_S", "0")),
    "i2c_eio_mentions": sum(line.count("eio") for line in error_lines),
    "radar_error_mentions": sum("radar" in line for line in error_lines),
    "controller_service_restarts": restarts,
}
json.dump(result, open(sys.argv[1], "w", encoding="utf-8"), indent=2, sort_keys=True)
PY
python3 - "$SESSION/summary.json" "$SESSION/summary.md" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    handle.write("# Hardware refresh session\n\n")
    for key, value in data.items():
        handle.write(f"- `{key}`: `{value}`\n")
PY
echo "session=$SESSION"
echo "Physical outputs were not actuated. Run tm6605-test.sh/light-test.sh only after wiring confirmation."
