#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path


MODEL_COMPAT_NAME = "yolov8n.om"
ALERT_RE = re.compile(r"\bAL\s+([LR])([1-4])\b", re.IGNORECASE)
LEVEL_RE = re.compile(
    r"(?:\bside\s*[=:]\s*)?(left|right|l|r)?\b.*?\blevel\s*[=: ]\s*([1-4])\b",
    re.IGNORECASE,
)
SAMPLE_DETECTION_RE = re.compile(
    r"\b(?P<label>\d+)\s*=\s*(?P<score>\d+(?:\.\d+)?)\s+at\s+"
    r"(?P<x>-?\d+(?:\.\d+)?)\s+(?P<y>-?\d+(?:\.\d+)?)\s+"
    r"(?P<w>-?\d+(?:\.\d+)?)\s+(?:x\s+)?(?P<h>-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def eprint(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def normalize_side(value: str | None, default_side: str) -> str:
    if not value:
        return default_side
    lowered = value.lower()
    if lowered in ("l", "left"):
        return "left"
    if lowered in ("r", "right"):
        return "right"
    raise ValueError(f"invalid side: {value!r}")


def parse_alert_line(line: str, default_side: str) -> dict[str, object] | None:
    text = strip_ansi(line).strip()
    if not text:
        return None

    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and data.get("type") == "vision_alert":
            data.setdefault("side", default_side)
            return data

    match = ALERT_RE.search(text)
    if match:
        return build_event(normalize_side(match.group(1), default_side), int(match.group(2)))

    match = LEVEL_RE.search(text)
    if match:
        return build_event(normalize_side(match.group(1), default_side), int(match.group(2)))

    return None


def parse_sample_detection_line(line: str, side: str, width: float, height: float) -> dict[str, object] | None:
    match = SAMPLE_DETECTION_RE.search(strip_ansi(line))
    if not match:
        return None

    score = float(match.group("score"))
    box_h = max(0.0, float(match.group("h")))
    height_ratio = box_h / max(height, 1.0)
    if score < 0.45:
        return None
    if height_ratio >= 0.65:
        level = 4
    elif height_ratio >= 0.45:
        level = 3
    elif height_ratio >= 0.25:
        level = 2
    else:
        level = 1

    event = build_event(side, level, score=score, track_id=int(match.group("label")))
    event["bbox"] = [
        round(float(match.group("x")), 2),
        round(float(match.group("y")), 2),
        round(float(match.group("w")), 2),
        round(box_h, 2),
    ]
    return event


def build_event(side: str, level: int, score: float = 1.0, track_id: int = 0) -> dict[str, object]:
    return {
        "type": "vision_alert",
        "side": side,
        "level": int(level),
        "score": round(float(score), 4),
        "track_id": int(track_id),
        "ts": round(time.monotonic(), 3),
    }


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)


def emit_event(event: dict[str, object]) -> None:
    print(json.dumps(event, separators=(",", ":"), ensure_ascii=False), flush=True)


def prepare_runner_cwd(model_path: Path, runner_cwd: Path) -> None:
    runner_cwd.mkdir(parents=True, exist_ok=True)
    compat_path = runner_cwd / MODEL_COMPAT_NAME
    if compat_path.exists() or compat_path.is_symlink():
        if compat_path.is_symlink() and Path(os.readlink(compat_path)) == model_path:
            return
        compat_path.unlink()
    try:
        compat_path.symlink_to(model_path)
    except OSError:
        import shutil

        shutil.copy2(model_path, compat_path)


def run_bridge(args: argparse.Namespace) -> int:
    model_path = Path(args.model).resolve()
    if not model_path.exists():
        raise SystemExit(f"model not found: {model_path}")

    if args.self_test_level:
        emit_event(build_event(args.side, args.self_test_level))
        return 0

    if not args.runner:
        eprint(f"OM model ready: {model_path}; no runner configured for {args.side}")
        while True:
            time.sleep(30.0)

    runner_cwd = Path(args.runner_cwd).resolve()
    prepare_runner_cwd(model_path, runner_cwd)
    command = shlex.split(args.runner)
    env = os.environ.copy()
    env["SMARTBAG_OM_MODEL"] = str(model_path)
    env["LD_LIBRARY_PATH"] = "/opt/lib:/opt/lib/npu:" + env.get("LD_LIBRARY_PATH", "")

    eprint(f"starting {args.side} OM runner in {runner_cwd}: {' '.join(command)}")
    process = subprocess.Popen(
        command,
        cwd=str(runner_cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )

    def _stop(_signum: int, _frame: object) -> None:
        if process.poll() is None:
            process.terminate()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    assert process.stdout is not None
    for line in process.stdout:
        event = parse_alert_line(line, args.side)
        if event is None and args.sample_detection_alerts:
            event = parse_sample_detection_line(line, args.side, args.frame_width, args.frame_height)
        if event is not None:
            emit_event(event)
        else:
            eprint(f"[{args.side} om] {strip_ansi(line).rstrip()}")

    return process.wait()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bridge a board OM detector runner to smartbag vision_alert JSONL.")
    parser.add_argument("--side", choices=("left", "right"), required=True)
    parser.add_argument("--emit-alert-jsonl", action="store_true", help="Accepted for controller compatibility.")
    parser.add_argument("--model", default="/root/smartbag_alert/intelligent_bag/models/yolo11s.om")
    parser.add_argument("--runner", default="", help="Detector command to run. It should emit JSONL or level text.")
    parser.add_argument("--runner-cwd", default="/root/smartbag_alert/runtime/om_detector")
    parser.add_argument("--self-test-level", type=int, choices=(1, 2, 3, 4), default=0)
    parser.add_argument(
        "--sample-detection-alerts",
        action="store_true",
        help="Development fallback: convert raw sample bbox prints to approximate levels.",
    )
    parser.add_argument("--frame-width", type=float, default=640.0)
    parser.add_argument("--frame-height", type=float, default=640.0)
    return parser.parse_args()


def main() -> None:
    raise SystemExit(run_bridge(parse_args()))


if __name__ == "__main__":
    main()
