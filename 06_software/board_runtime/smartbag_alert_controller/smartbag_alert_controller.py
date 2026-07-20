#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
import os
import queue
import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Mapping

BOARD_RUNTIME_DIR = Path(__file__).resolve().parents[1]
COMMON_DIR = BOARD_RUNTIME_DIR / "common"
if str(BOARD_RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(BOARD_RUNTIME_DIR))
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from ble_protocol import route_ble_command
from hardware_profile import validate_hardware_profile
from i2c_mux import I2cMuxTransaction
from runtime_metrics import ResourceSampler, atomic_write_json, status_timestamp
from mr20_radar import MR20RadarWorker, RadarAlert, load_mr20_config

from alert_core import (
    DEFAULT_LEVEL_DUTY_PERCENT,
    DEFAULT_PWM_PERIOD_NS,
    MOTOR_PWM_PINS,
    AlertEvent,
    AlertOutput,
    AlertState,
    MOTOR_BY_KEY,
    event_is_stale,
    normalize_level,
    parse_alert_command,
    parse_vision_alert_jsonl,
)
from ble_nus import BleNusServer
from haptics import DryRunHapticBackend, LegacyPwmHapticBackend, Tm6605HapticBackend
from lights import DisabledLightBackend, LinuxSysfsPwm, PwmChannelSpec, PwmLightBackend
from output_policy import OutputDecision, OutputPolicy


AUDIO_ROOT = Path("/root/smartbag/audio")
SAMPLE_AUDIO = "/opt/sample/audio/sample_audio"
BLE_NAME = "SS928-SmartBag"
RISK_NAMES = ("SAFE", "ATTENTION", "CAUTION", "DANGER", "EMERGENCY")
I2S_PINMUX = (
    ("0x102F010C", "0x1202", "Pin12 I2S_BCLK"),
    ("0x102F0108", "0x1102", "Pin38 I2S_WS"),
    ("0x102F0104", "0x1202", "Pin40 I2S_SD_TX"),
)


def eprint(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


class PwmController:
    def __init__(
        self,
        pwm_root: Path,
        period_ns: int = DEFAULT_PWM_PERIOD_NS,
        dry_run: bool = False,
        skip_pinmux: bool = False,
    ) -> None:
        self.pwm_root = pwm_root
        self.period_ns = period_ns
        self.dry_run = dry_run
        self.skip_pinmux = skip_pinmux

    def setup(self) -> None:
        if not self.skip_pinmux:
            for pin in MOTOR_PWM_PINS:
                self._run(["bspmm", pin.pinmux_addr, pin.pinmux_value], f"{pin.key} pinmux")
        for pin in MOTOR_PWM_PINS:
            self._ensure_channel(pin.key)

    def preflight(self) -> None:
        chip_path = self.pwm_root / "pwmchip0"
        npwm_path = chip_path / "npwm"
        if self.dry_run:
            eprint(f"DRY preflight read {npwm_path}")
            return
        if not npwm_path.exists():
            raise RuntimeError(f"{npwm_path} not found")
        npwm = int(npwm_path.read_text(encoding="ascii").strip())
        required = max(pin.pwm_channel for pin in MOTOR_PWM_PINS) + 1
        if npwm < required:
            raise RuntimeError(f"pwmchip0 npwm={npwm}, need at least {required}")
        eprint(f"pwmchip0 npwm={npwm}; channels 1/10/14/15 are in range")

    def apply(self, duties_ns: dict[str, int]) -> None:
        for key, duty_ns in duties_ns.items():
            self.set_duty(key, duty_ns)

    def stop_all(self) -> None:
        for pin in MOTOR_PWM_PINS:
            self.set_duty(pin.key, 0)

    def set_duty(self, key: str, duty_ns: int) -> None:
        pin = MOTOR_BY_KEY[key]
        duty_ns = max(0, min(int(duty_ns), self.period_ns))
        if self.dry_run:
            eprint(
                f"DRY pwm {key}: chip={pin.pwm_chip} channel={pin.pwm_channel} "
                f"period={self.period_ns} duty={duty_ns}"
            )
            return
        pwm_path = self._ensure_channel(key)
        if self._read(pwm_path / "enable") == "1":
            self._write(pwm_path / "enable", "0")
        self._write(pwm_path / "period", str(self.period_ns))
        self._write(pwm_path / "duty_cycle", str(duty_ns))
        self._write(pwm_path / "enable", "1" if duty_ns > 0 else "0")

    def _ensure_channel(self, key: str) -> Path:
        pin = MOTOR_BY_KEY[key]
        chip_path = self.pwm_root / f"pwmchip{pin.pwm_chip}"
        pwm_path = chip_path / f"pwm{pin.pwm_channel}"
        if self.dry_run:
            return pwm_path
        if not chip_path.exists():
            raise RuntimeError(f"{chip_path} not found")
        if not pwm_path.exists():
            self._write(chip_path / "export", str(pin.pwm_channel))
            for _ in range(20):
                if pwm_path.exists():
                    break
                time.sleep(0.05)
        if not pwm_path.exists():
            raise RuntimeError(f"{pwm_path} did not appear after export")
        return pwm_path

    def _write(self, path: Path, value: str) -> None:
        path.write_text(value + "\n", encoding="ascii")

    def _read(self, path: Path) -> str:
        return path.read_text(encoding="ascii", errors="ignore").strip()

    def _run(self, command: list[str], label: str) -> None:
        if self.dry_run:
            eprint("DRY " + " ".join(command) + f"  # {label}")
            return
        subprocess.run(command, check=True)


class AudioPlayer:
    def __init__(
        self,
        audio_root: Path,
        sample_audio: str = SAMPLE_AUDIO,
        dry_run: bool = False,
        enabled: bool = True,
        default_sleep_s: float = 5.0,
        default_timeout_s: float = 13.0,
        skip_pinmux: bool = False,
    ) -> None:
        self.audio_root = audio_root
        self.sample_audio = sample_audio
        self.dry_run = dry_run
        self.enabled = enabled
        self.default_sleep_s = default_sleep_s
        self.default_timeout_s = default_timeout_s
        self.skip_pinmux = skip_pinmux
        self._queue: "queue.PriorityQueue[tuple[int, int, str]]" = queue.PriorityQueue()
        self._sequence = itertools.count()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._process_lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None

    def setup(self) -> None:
        if self.skip_pinmux or not self.enabled:
            return
        for addr, value, label in I2S_PINMUX:
            if self.dry_run:
                eprint(f"DRY bspmm {addr} {value}  # {label}")
            else:
                subprocess.run(["bspmm", addr, value], check=True)

    def start(self) -> None:
        if not self.enabled:
            return
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def request(self, clip: str | None) -> None:
        if not self.enabled or not clip:
            return
        try:
            level = int(clip[1:])
        except ValueError:
            level = 0
        self._queue.put((-level, next(self._sequence), clip))

    def clear(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        with self._process_lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()

    def stop(self) -> None:
        self._stop.set()
        self.clear()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                _priority, _sequence, clip = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            self._play(clip)

    def _play(self, clip: str) -> None:
        clip_dir = self.audio_root / clip
        audio_file = clip_dir / "audio_chn0.aac"
        if self.dry_run:
            eprint(f"DRY play {clip}: cd {clip_dir} && {self.sample_audio} 2")
            return
        if not audio_file.exists():
            eprint(f"WARN missing audio clip {audio_file}")
            return
        sleep_s, timeout_s = self._timing_for(clip_dir)
        with self._process_lock:
            self._process = subprocess.Popen(
                [self.sample_audio, "2"],
                cwd=str(clip_dir),
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
            process = self._process
        try:
            deadline = time.monotonic() + max(timeout_s, sleep_s + 1.0)
            while time.monotonic() < deadline and process.poll() is None:
                if time.monotonic() >= deadline - max(timeout_s - sleep_s, 1.0):
                    break
                time.sleep(0.1)
            process.communicate(input=b"\n\n", timeout=max(timeout_s - sleep_s, 1.0))
        except subprocess.TimeoutExpired:
            process.kill()
        finally:
            with self._process_lock:
                if self._process is process:
                    self._process = None

    def _timing_for(self, clip_dir: Path) -> tuple[float, float]:
        hint = clip_dir / "play_hint.txt"
        sleep_s = self.default_sleep_s
        timeout_s = self.default_timeout_s
        if not hint.exists():
            return sleep_s, timeout_s
        try:
            for line in hint.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("sleep_seconds="):
                    sleep_s = float(line.split("=", 1)[1])
                elif line.startswith("timeout_seconds="):
                    timeout_s = float(line.split("=", 1)[1])
        except ValueError:
            return self.default_sleep_s, self.default_timeout_s
        return sleep_s, timeout_s


class DetectorProcess:
    def __init__(
        self,
        side: str | None,
        command: str,
        event_queue: "queue.Queue[AlertEvent]",
        cwd: Path | None = None,
        restart_limit: int = 5,
        restart_backoff_s: float = 1.0,
        append_alert_args: bool = True,
    ) -> None:
        self.side = side
        self.command = command
        self.event_queue = event_queue
        self.cwd = cwd
        self.process: subprocess.Popen[str] | None = None
        self.thread: threading.Thread | None = None
        self.restart_limit = max(0, int(restart_limit))
        self.restart_backoff_s = max(0.1, float(restart_backoff_s))
        self.restart_count = 0
        self.next_restart_s = 0.0
        self.last_exit_code: int | None = None
        self._stopping = False
        self.append_alert_args = append_alert_args

    def start(self, *, restarted: bool = False) -> None:
        argv = (
            build_detector_command(self.command, self.side)
            if self.append_alert_args
            else shlex.split(self.command)
        )
        process = subprocess.Popen(
            argv,
            cwd=str(self.cwd) if self.cwd else None,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self.process = process
        if restarted:
            self.restart_count += 1
        self.thread = threading.Thread(target=self._reader, args=(process,), daemon=True)
        self.thread.start()
        eprint(f"started {self.side or 'single-camera'} detector pid={process.pid}: {' '.join(argv)}")

    def stop(self) -> None:
        self._stopping = True
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def maybe_restart(self, now_s: float | None = None) -> bool:
        now_s = time.monotonic() if now_s is None else now_s
        if self._stopping or self.process is None or self.process.poll() is None:
            return False
        if self.thread is not None and self.thread.is_alive():
            return False
        if self.restart_count >= self.restart_limit or now_s < self.next_restart_s:
            return False
        self.start(restarted=True)
        return True

    def status(self) -> dict[str, object]:
        process = self.process
        return {
            "side": self.side or "auto",
            "running": bool(process is not None and process.poll() is None),
            "pid": process.pid if process is not None and process.poll() is None else None,
            "restart_count": self.restart_count,
            "restart_limit": self.restart_limit,
            "last_exit_code": self.last_exit_code,
        }

    def _reader(self, process: subprocess.Popen[str] | None = None) -> None:
        process = process or self.process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                text = line.strip()
                if not text:
                    continue
                try:
                    event = parse_vision_alert_jsonl(text)
                except Exception as exc:
                    eprint(f"[{self.side or 'single-camera'}] ignored malformed alert: {text[:160]} ({exc})")
                    continue
                if event is not None:
                    if self.side in ("left", "right") and event.side != self.side:
                        eprint(
                            f"[{self.side}] rejected cross-side event side={event.side} "
                            f"level={event.level}"
                        )
                        continue
                    self.event_queue.put(event)
        finally:
            try:
                self.last_exit_code = process.poll()
            except AttributeError:
                self.last_exit_code = None
            clear_sides = (self.side,) if self.side in ("left", "right") else ("left", "right")
            for clear_side in clear_sides:
                self.event_queue.put(
                    AlertEvent(
                        side=clear_side,
                        level=0,
                        event_kind="state_change",
                        ts=time.monotonic(),
                        clear_reason="detector_exit",
                    )
                )
            self.next_restart_s = time.monotonic() + self.restart_backoff_s * min(
                8.0,
                2.0**self.restart_count,
            )
            eprint(f"detector {self.side or 'single-camera'} exited; queued vibration clear")


def build_detector_command(command: str, side: str | None) -> list[str]:
    argv = shlex.split(command)
    if "--side" not in argv:
        argv.extend(["--side", side or "auto"])
    if "--emit-alert-jsonl" not in argv:
        argv.append("--emit-alert-jsonl")
    return argv


def validate_dual_camera_config(config: dict[str, object]) -> None:
    cameras = config.get("cameras")
    if not isinstance(cameras, dict):
        return
    left = cameras.get("left")
    right = cameras.get("right")
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise ValueError("cameras.left and cameras.right must both be configured")
    left_device = str(left.get("camera_device") or "").strip()
    right_device = str(right.get("camera_device") or "").strip()
    if not left_device or not right_device:
        raise ValueError("both camera_device values are required")
    if left_device == right_device or os.path.realpath(left_device) == os.path.realpath(right_device):
        raise ValueError("left and right camera_device must be different")
    left_port = int(left.get("stream_port", 18081))
    right_port = int(right.get("stream_port", 18082))
    if left_port == right_port:
        raise ValueError("left and right detector stream_port must be different")
    expected_pwm = {"left": {"left_1", "left_2"}, "right": {"right_1", "right_2"}}
    for side, camera in (("left", left), ("right", right)):
        configured_pwm = camera.get("pwm_channels")
        if configured_pwm is not None and set(configured_pwm) != expected_pwm[side]:
            raise ValueError(f"cameras.{side}.pwm_channels must stay on the {side} side")


def detector_commands_from_config(
    config: dict[str, object],
    *,
    left_video: str = "",
    right_video: str = "",
) -> tuple[str, str]:
    cameras = config.get("cameras")
    if not isinstance(cameras, dict):
        return "", ""
    validate_dual_camera_config(config)
    paths = config.get("paths") if isinstance(config.get("paths"), dict) else {}
    python_executable = str(paths.get("python", "/usr/bin/python3"))
    vision_root = Path(str(paths.get("vision", "/root/smartbag/vision")))
    model_path = str(paths.get("model", "/root/smartbag/models/yolo11n.pt"))
    detector_script = str(vision_root / "vision_obstacle_tracker.py")
    videos = {"left": left_video, "right": right_video}
    commands: dict[str, str] = {}

    for side in ("left", "right"):
        camera = cameras.get(side)
        if not isinstance(camera, dict):
            raise ValueError(f"cameras.{side} must be an object")
        video_path = videos[side]
        argv = [python_executable, detector_script]
        if video_path:
            argv.extend(["--source", "video", "--video", video_path, "--video-every-frame"])
        else:
            argv.extend(["--source", "camera", "--camera-device", str(camera["camera_device"])])
        argv.extend(
            [
                "--runtime-profile",
                str(camera.get("detector_profile", "board_dual_balanced")),
                "--model",
                model_path,
                "--side",
                side,
                "--emit-alert-jsonl",
                "--no-display",
                "--camera-height",
                str(camera.get("camera_height", 1.2)),
                "--camera-pitch",
                str(camera.get("camera_pitch", 5.0)),
                "--camera-fps",
                str(camera.get("camera_fps", 30.0)),
                "--inference-fps-limit",
                str(camera.get("inference_fps_limit", 8.0)),
                "--process-every-n",
                str(camera.get("process_every_n", 1)),
                "--camera-reconnect-attempts",
                str(camera.get("camera_reconnect_attempts", 5)),
                "--camera-reconnect-backoff",
                str(camera.get("camera_reconnect_backoff_s", 0.5)),
                "--alert-min-level",
                str(camera.get("alert_min_level", 1)),
                "--alert-rate-limit",
                str(camera.get("alert_rate_limit_s", 0.25)),
                "--stream-bind",
                "127.0.0.1",
                "--stream-port",
                str(camera.get("stream_port", 18081 if side == "left" else 18082)),
                "--jpeg-stream-width",
                str(camera.get("jpeg_stream_width", 480)),
                "--jpeg-stream-height",
                str(camera.get("jpeg_stream_height", 360)),
                "--jpeg-quality",
                str(camera.get("jpeg_quality", 70)),
                "--stream-fps-limit",
                str(camera.get("stream_fps_limit", 8.0)),
                "--risk-log-csv",
                str(camera.get("risk_log_csv", f"/var/log/smartbag/risk-{side}.csv")),
                "--profile",
            ]
        )
        calibration_file = str(camera.get("calibration_file") or "").strip()
        if calibration_file:
            argv.extend(["--calibration-file", calibration_file])
        commands[side] = shlex.join(argv)
    return commands["left"], commands["right"]


def alternating_detector_command_from_config(config: dict[str, object]) -> str:
    runtime = config.get("vision_runtime") if isinstance(config.get("vision_runtime"), dict) else {}
    if str(runtime.get("mode", "fixed_dual_process")) != "alternating_single_model":
        return ""
    alternating = config.get("alternating_camera")
    if not isinstance(alternating, dict) or not bool(alternating.get("enabled", False)):
        raise ValueError("alternating_single_model requires alternating_camera.enabled=true")
    if str(alternating.get("backend", "v4l2_stream_toggle")) != "v4l2_stream_toggle":
        raise ValueError("alternating_single_model currently supports only v4l2_stream_toggle")
    validate_dual_camera_config(config)
    paths = config.get("paths") if isinstance(config.get("paths"), dict) else {}
    cameras = config["cameras"]
    assert isinstance(cameras, dict)
    left = cameras["left"]
    right = cameras["right"]
    assert isinstance(left, dict) and isinstance(right, dict)
    python_executable = str(paths.get("python", "/usr/bin/python3"))
    vision_root = Path(str(paths.get("vision", "/root/smartbag/vision")))
    argv = [
        python_executable,
        str(vision_root / "alternating_dual_camera_tracker.py"),
        "--left-device",
        str(left["camera_device"]),
        "--right-device",
        str(right["camera_device"]),
        "--backend",
        "v4l2_stream_toggle",
        "--model",
        str(paths.get("model", "/root/smartbag/models/yolo11n.pt")),
        "--tracker",
        str(alternating.get("tracker", vision_root / "vehicle_botsort.yaml")),
        "--width",
        str(alternating.get("width", 640)),
        "--height",
        str(alternating.get("height", 480)),
        "--fps",
        str(alternating.get("fps", 10)),
        "--normal-slice-ms",
        str(alternating.get("normal_slice_ms", 500)),
        "--risk-slice-ms",
        str(alternating.get("risk_slice_ms", 700)),
        "--minimum-other-side-slice-ms",
        str(alternating.get("minimum_other_side_slice_ms", 250)),
        "--warmup-frames",
        str(alternating.get("warmup_frames", 2)),
        "--frames-per-slice",
        str(alternating.get("frames_per_slice", 4)),
        "--inference-frames-per-slice",
        str(alternating.get("inference_frames_per_slice", 1)),
        "--max-blind-interval-ms",
        str(alternating.get("max_blind_interval_ms", 1200)),
        "--stale-observation-timeout-ms",
        str(alternating.get("stale_observation_timeout_ms", 1800)),
        "--switch-failure-limit",
        str(alternating.get("switch_failure_limit", 3)),
        "--switch-backoff-ms",
        str(alternating.get("switch_backoff_ms", 200)),
        "--camera-reconnect-attempts",
        str(alternating.get("camera_reconnect_attempts", 5)),
        "--camera-reconnect-initial-backoff-s",
        str(alternating.get("camera_reconnect_initial_backoff_s", 0.5)),
        "--camera-reconnect-max-backoff-s",
        str(alternating.get("camera_reconnect_max_backoff_s", 8.0)),
        "--tracker-reset-after-disconnect-s",
        str(alternating.get("tracker_reset_after_disconnect_s", 3.0)),
        "--duration-s",
        str(alternating.get("duration_s", 0)),
        "--switch-count",
        str(alternating.get("switch_count", 1000000000)),
        "--output-dir",
        str(alternating.get("output_dir", "/var/log/smartbag/alternating-camera-runs")),
        "--imgsz",
        str(alternating.get("imgsz", 416)),
        "--conf",
        str(alternating.get("conf", 0.08)),
        "--max-det",
        str(alternating.get("max_det", 30)),
        "--tracker-nominal-fps",
        str(alternating.get("tracker_nominal_fps", alternating.get("fps", 10))),
        "--tracker-effective-fps-mode",
        str(alternating.get("tracker_effective_fps_mode", "effective_side")),
        "--min-confirm-slices-caution",
        str(alternating.get("min_confirm_slices_caution", 2)),
        "--min-confirm-slices-danger",
        str(alternating.get("min_confirm_slices_danger", 2)),
        "--min-confirm-slices-emergency",
        str(alternating.get("min_confirm_slices_emergency", 2)),
        "--minimum-confirmation-interval-s",
        str(alternating.get("minimum_confirmation_interval_s", 0.2)),
        "--serve-bind",
        str(alternating.get("serve_bind", "0.0.0.0")),
        "--serve-port",
        str(alternating.get("serve_port", 8080)),
        "--access-token",
        str(alternating.get("access_token", "")),
        "--jpeg-quality",
        str(alternating.get("jpeg_quality", 80)),
        "--overlay-width",
        str(alternating.get("overlay_width", 0)),
        "--overlay-height",
        str(alternating.get("overlay_height", 0)),
        "--stream-fps-limit",
        str(alternating.get("stream_fps_limit", 5.0)),
        "--calibration-mode",
        str(alternating.get("calibration_mode", "diagnostic")),
    ]
    logging_config = config.get("logging") if isinstance(config.get("logging"), dict) else {}
    if bool(logging_config.get("risk_csv_enabled", False)):
        argv.extend(
            ["--risk-log-dir", str(alternating.get("risk_log_dir", "/var/log/smartbag"))]
        )
    if bool(alternating.get("prefer_openvino", False)):
        argv.append("--prefer-openvino")
    left_calibration = str(left.get("calibration_file", "")).strip()
    right_calibration = str(right.get("calibration_file", "")).strip()
    if left_calibration:
        argv.extend(["--left-calibration-file", left_calibration])
    if right_calibration:
        argv.extend(["--right-calibration-file", right_calibration])
    if not bool(alternating.get("risk_priority_enabled", True)):
        argv.append("--disable-risk-priority")
    if not bool(alternating.get("camera_reconnect_enabled", True)):
        argv.append("--disable-camera-reconnect")
    if not bool(alternating.get("video_gateway_enabled", True)):
        argv.append("--disable-video-gateway")
    if not bool(alternating.get("allow_emergency_single_slice_fast_path", True)):
        argv.append("--disable-emergency-single-slice-fast-path")
    return shlex.join(argv)


def should_publish_alert_history(event: AlertEvent) -> bool:
    """Heartbeat refreshes PWM only; state changes are persisted to BLE/mobile history."""
    return event.event_kind == "state_change"


def alert_event_ble_payload(event: AlertEvent, *, effective_level: int | None = None) -> str:
    level = max(0, min(4, int(event.level)))
    payload: dict[str, object] = {
        "typ": "alert",
        "side": event.side,
        "level": level,
        "name": RISK_NAMES[level],
        "ts": event.ts,
        "source": AlertState.event_source(event),
        "event_kind": event.event_kind,
    }
    if effective_level is not None:
        payload["effective_level"] = normalize_level(effective_level)
    if event.score is not None:
        payload["score"] = round(float(event.score), 4)
    if event.track_id is not None:
        payload["track_id"] = int(event.track_id)
    if event.class_name:
        payload["class"] = event.class_name
    if event.distance_m is not None:
        payload["distance_m"] = round(float(event.distance_m), 3)
    if event.source_id is not None:
        payload["source_id"] = event.source_id
    if event.ttc_s is not None:
        payload["ttc_s"] = round(float(event.ttc_s), 3)
    if event.closing_speed_mps is not None:
        payload["closing_speed_mps"] = round(float(event.closing_speed_mps), 3)
    if event.lateral_distance_m is not None:
        payload["lateral_distance_m"] = round(float(event.lateral_distance_m), 3)
    if event.longitudinal_distance_m is not None:
        payload["longitudinal_distance_m"] = round(float(event.longitudinal_distance_m), 3)
    if event.clear_reason:
        payload["clear_reason"] = event.clear_reason
    if event.metadata:
        allowed = {"target_count", "measurement_count", "status"}
        metadata = {key: value for key, value in event.metadata.items() if key in allowed}
        if metadata:
            payload["metadata"] = metadata
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def controller_status_payload(
    state: AlertState,
    detectors: list[DetectorProcess],
    modules: dict[str, "RoutedModuleProcess"],
    resource_sampler: ResourceSampler,
    *,
    actuators: Mapping[str, ManagedActuator] | None = None,
    radars: Iterable[MR20RadarWorker] = (),
    module_states: Mapping[str, str] | None = None,
) -> dict[str, object]:
    return {
        "typ": "sys",
        "ts": status_timestamp(),
        "pid": os.getpid(),
        "levels": dict(state.levels_by_side),
        "source_levels": state.source_snapshot(),
        "detectors": [detector.status() for detector in detectors],
        "modules": {
            namespace: {
                "running": bool(module.process is not None and module.process.poll() is None),
                "pid": module.process.pid if module.process is not None and module.process.poll() is None else None,
            }
            for namespace, module in sorted(modules.items())
        },
        "module_states": dict(module_states or {}),
        "actuators": {
            name: actuator.status() for name, actuator in (actuators or {}).items()
        },
        "radars": [radar.status() for radar in radars],
        "resources": resource_sampler.sample(),
        "battery": None,
        "ble_video": False,
    }


class RoutedModuleProcess:
    def __init__(
        self,
        namespace: str,
        command: str,
        response_queue: "queue.Queue[tuple[str, str]]",
        cwd: Path | None = None,
    ) -> None:
        self.namespace = namespace
        self.command = command
        self.response_queue = response_queue
        self.cwd = cwd
        self.process: subprocess.Popen[str] | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.process = subprocess.Popen(
            shlex.split(self.command),
            cwd=str(self.cwd) if self.cwd else None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()
        eprint(f"started {self.namespace} module pid={self.process.pid}")

    def send(self, command: str) -> None:
        if self.process is None or self.process.poll() is not None or self.process.stdin is None:
            raise RuntimeError(f"{self.namespace} module is not running")
        self.process.stdin.write(command.rstrip() + "\n")
        self.process.stdin.flush()

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def _reader(self) -> None:
        if self.process is None or self.process.stdout is None:
            return
        for line in self.process.stdout:
            text = line.strip()
            if text:
                self.response_queue.put((self.namespace, text))


def load_controller_config(path: str) -> dict[str, object]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("controller config must be a JSON object")
    return data


def _int_config(value: object) -> int:
    return int(str(value), 0) if isinstance(value, str) else int(value)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def default_legacy_hardware_config(
    pwm_config: Mapping[str, object],
    audio_config: Mapping[str, object],
) -> dict[str, object]:
    return {
        "profile": "legacy_pwm_haptics",
        "i2c_mux": {"enabled": False, "required": False, "failure_policy": "degrade"},
        "imu": {"backend": "bmi270", "required": False, "failure_policy": "degrade"},
        "haptics": {
            "backend": "legacy_pwm",
            "period_ns": int(pwm_config.get("period_ns", DEFAULT_PWM_PERIOD_NS)),
            "level_duty_percent": pwm_config.get(
                "level_duty_percent", DEFAULT_LEVEL_DUTY_PERCENT
            ),
            "required": True,
            "failure_policy": "fail_service",
        },
        "lights": {"enabled": False, "required": False, "failure_policy": "degrade"},
        "radar": {"enabled": False, "required": False, "failure_policy": "degrade"},
        "audio": {
            "enabled": bool(audio_config.get("enabled", False)),
            "backend": "max98357",
            "required": False,
            "failure_policy": "degrade",
        },
    }


def hardware_config_from_controller(
    config: Mapping[str, object],
    pwm_config: Mapping[str, object],
    audio_config: Mapping[str, object],
) -> dict[str, object]:
    hardware = config.get("hardware")
    if isinstance(hardware, Mapping):
        result = dict(hardware)
    else:
        profile_file = str(config.get("hardware_profile_file", "")).strip()
        if profile_file:
            loaded = json.loads(Path(profile_file).read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("hardware profile file must contain a JSON object")
            result = loaded
        else:
            result = default_legacy_hardware_config(pwm_config, audio_config)
    validate_hardware_profile(result)
    return result


def module_failure_policy(config: Mapping[str, object]) -> tuple[bool, str]:
    required = bool(config.get("required", False))
    policy = str(config.get("failure_policy", "fail_service" if required else "degrade"))
    return required, policy


class ManagedActuator:
    def __init__(
        self,
        name: str,
        backend: object,
        fallback: object,
        config: Mapping[str, object],
        *,
        disabled: bool = False,
    ) -> None:
        self.name = name
        self.backend = backend
        self.fallback = fallback
        self.required, self.failure_policy = module_failure_policy(config)
        self.state = "disabled" if disabled else "starting"
        self.last_error = ""

    def initialize(self, *, preflight_only: bool = False) -> None:
        if self.state == "disabled":
            return
        try:
            self.backend.preflight()  # type: ignore[attr-defined]
            if not preflight_only:
                self.backend.setup()  # type: ignore[attr-defined]
                self.backend.stop_all()  # type: ignore[attr-defined]
            self.state = "online"
        except Exception as exc:
            self._handle_failure(exc)

    def apply_levels(self, levels: Mapping[str, int], now: float | None = None) -> None:
        if self.state == "disabled":
            return
        try:
            self.backend.apply_levels(levels, now=now)  # type: ignore[attr-defined]
        except Exception as exc:
            self._handle_failure(exc)

    def tick(self, now: float | None = None) -> None:
        if self.state == "disabled":
            return
        try:
            self.backend.tick(now=now)  # type: ignore[attr-defined]
        except Exception as exc:
            self._handle_failure(exc)

    def stop_all(self) -> None:
        try:
            self.backend.stop_all()  # type: ignore[attr-defined]
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            eprint(f"ERROR {self.name} stop_all failed: {exc}")

    def status(self) -> dict[str, object]:
        try:
            detail = self.backend.status()  # type: ignore[attr-defined]
        except Exception as exc:
            detail = {"status_error": f"{type(exc).__name__}: {exc}"}
        return {
            "state": self.state,
            "required": self.required,
            "failure_policy": self.failure_policy,
            "last_error": self.last_error,
            "detail": detail,
        }

    def _handle_failure(self, exc: Exception) -> None:
        self.last_error = f"{type(exc).__name__}: {exc}"
        if self.required or self.failure_policy == "fail_service":
            self.state = "error"
            raise RuntimeError(f"required module {self.name} failed: {exc}") from exc
        eprint(f"WARN optional module {self.name} degraded: {exc}")
        try:
            self.backend.stop_all()  # type: ignore[attr-defined]
        except Exception:
            pass
        self.backend = self.fallback
        self.backend.setup()  # type: ignore[attr-defined]
        self.state = "degraded"


def build_actuator_runtime(
    hardware: Mapping[str, object],
    args: argparse.Namespace,
    legacy_pwm: PwmController,
) -> tuple[ManagedActuator, ManagedActuator, OutputPolicy]:
    profile = str(hardware["profile"])
    haptic_config = _mapping(hardware.get("haptics"))
    light_config = _mapping(hardware.get("lights"))
    mux_config = _mapping(hardware.get("i2c_mux"))

    if args.disable_haptics or args.dry_run:
        haptic_backend: object = DryRunHapticBackend()
    elif profile == "legacy_pwm_haptics":
        haptic_backend = LegacyPwmHapticBackend(
            legacy_pwm,
            period_ns=int(haptic_config.get("period_ns", DEFAULT_PWM_PERIOD_NS)),
            level_duty_percent=_mapping(haptic_config.get("level_duty_percent")),
        )
    else:
        mux_enabled = bool(mux_config.get("enabled", False))
        mux_address = _int_config(mux_config.get("address", "0x70")) if mux_enabled else None
        lock_file = str(mux_config.get("lock_file", "/run/lock/smartbag-i2c0-mux.lock"))
        device = str(mux_config.get("device", "/dev/i2c-0"))
        target_address = _int_config(haptic_config.get("address", "0x2d"))
        transactions = {
            "left": I2cMuxTransaction(
                device,
                target_address,
                mux_address=mux_address,
                mux_channel=int(haptic_config.get("left_channel", 1)) if mux_enabled else None,
                lock_file=lock_file,
            ),
            "right": I2cMuxTransaction(
                device,
                target_address,
                mux_address=mux_address,
                mux_channel=int(haptic_config.get("right_channel", 2)) if mux_enabled else None,
                lock_file=lock_file,
            ),
        }
        haptic_backend = Tm6605HapticBackend(
            transactions,
            _mapping(haptic_config.get("level_effects")),
        )

    haptics = ManagedActuator(
        "haptics",
        haptic_backend,
        DryRunHapticBackend(),
        haptic_config,
        disabled=args.disable_haptics,
    )

    lights_enabled = bool(light_config.get("enabled", False)) and not args.disable_lights
    if lights_enabled:
        pwm = LinuxSysfsPwm(Path(args.pwm_root), dry_run=args.dry_run)
        channels = {
            side: PwmChannelSpec(
                side=side,
                channel=int(_mapping(light_config.get(side))["channel"]),
                pin=int(_mapping(light_config.get(side))["pin"]),
                chip=_mapping(light_config.get(side)).get("chip", "auto"),
            )
            for side in ("left", "right")
        }
        light_backend: object = PwmLightBackend(
            pwm,
            channels,
            _mapping(light_config.get("level_patterns")),
            period_ns=int(light_config.get("period_ns", DEFAULT_PWM_PERIOD_NS)),
        )
    else:
        light_backend = DisabledLightBackend()
    lights = ManagedActuator(
        "lights",
        light_backend,
        DisabledLightBackend(),
        light_config,
        disabled=not lights_enabled,
    )
    output_policy = OutputPolicy.for_profile(
        profile,
        _mapping(hardware.get("output_policy")),
    )
    return haptics, lights, output_policy


def radar_alert_to_event(alert: RadarAlert) -> AlertEvent:
    return AlertEvent(
        side=alert.side,
        level=alert.level,
        event_kind=alert.event_kind,
        ts=alert.ts,
        clear_reason=alert.clear_reason,
        source=alert.source,
        source_id=alert.source_id,
        ttc_s=alert.ttc_s,
        closing_speed_mps=alert.closing_speed_mps,
        lateral_distance_m=alert.lateral_distance_m,
        longitudinal_distance_m=alert.longitudinal_distance_m,
        metadata=alert.metadata,
    )


def start_stdin_reader(
    event_queue: "queue.Queue[AlertEvent]",
    command_queue: "queue.Queue[str]",
    stop_event: threading.Event,
    stop_on_eof: bool = False,
) -> threading.Thread:
    def _run() -> None:
        while not stop_event.is_set():
            line = sys.stdin.readline()
            if not line:
                if stop_on_eof:
                    stop_event.set()
                break
            text = line.strip()
            if not text:
                continue
            if not text.startswith("{"):
                command_queue.put(text)
                continue
            try:
                event = parse_vision_alert_jsonl(text)
            except Exception as exc:
                eprint(f"stdin ignored: {text[:160]} ({exc})")
                continue
            if event is not None:
                event_queue.put(event)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread


def apply_output(output: AlertOutput, pwm: PwmController, audio: AudioPlayer) -> None:
    pwm.apply(output.duties_ns)
    audio.request(output.audio_clip)


def apply_effective_output(
    output: AlertOutput,
    haptics: ManagedActuator,
    lights: ManagedActuator,
    audio: AudioPlayer,
    policy: OutputPolicy,
    *,
    now: float | None = None,
) -> OutputDecision:
    decision = policy.decide(output.levels or {}, output.audio_clip)
    haptics.apply_levels(decision.haptic_levels, now=now)
    lights.apply_levels(decision.light_levels, now=now)
    audio.request(decision.audio_clip)
    return decision


def best_effort_stop_all(pwm: PwmController) -> None:
    try:
        pwm.stop_all()
    except Exception as exc:
        eprint(f"ERROR failed to clear all PWM outputs: {exc}")


def run_controller(args: argparse.Namespace) -> int:
    config = load_controller_config(args.config)
    validate_dual_camera_config(config)
    pwm_config = config.get("pwm", {}) if isinstance(config.get("pwm", {}), dict) else {}
    audio_config = config.get("audio", {}) if isinstance(config.get("audio", {}), dict) else {}
    hardware = hardware_config_from_controller(config, pwm_config, audio_config)
    hardware_audio = _mapping(hardware.get("audio"))
    radar_hardware = _mapping(hardware.get("radar"))
    timing_config = config.get("timing", {}) if isinstance(config.get("timing", {}), dict) else {}
    ble_config = config.get("ble", {}) if isinstance(config.get("ble", {}), dict) else {}
    pwm_period_ns = int(args.pwm_period_ns or pwm_config.get("period_ns", DEFAULT_PWM_PERIOD_NS))
    event_timeout_s = float(args.event_timeout or timing_config.get("event_timeout_s", 1.0))
    max_event_age_s = float(args.max_event_age or timing_config.get("max_event_age_s", 2.0))
    ble_name = str(args.ble_name or ble_config.get("name", BLE_NAME))
    restart_config = config.get("detector_restart", {}) if isinstance(config.get("detector_restart", {}), dict) else {}
    restart_limit = int(args.detector_restart_limit if args.detector_restart_limit is not None else restart_config.get("limit", 5))
    restart_backoff_s = float(args.detector_restart_backoff if args.detector_restart_backoff is not None else restart_config.get("backoff_s", 1.0))
    status_file = str(args.status_file or config.get("controller_status_file", ""))
    level_duties = pwm_config.get("level_duty_percent")
    event_queue: "queue.Queue[AlertEvent]" = queue.Queue()
    command_queue: "queue.Queue[str]" = queue.Queue()
    response_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
    stop_event = threading.Event()
    module_states: dict[str, str] = {
        "haptics": "disabled" if args.disable_haptics else "starting",
        "lights": "disabled" if args.disable_lights else "starting",
        "radar": "disabled" if args.disable_radar else "starting",
        "vision": "disabled" if args.disable_vision else "starting",
        "gnss": "disabled" if args.disable_gnss else "starting",
        "imu": "disabled" if args.disable_imu else "starting",
        "ble": "disabled" if args.disable_ble or args.no_ble else "starting",
        "audio": "disabled" if args.no_audio else "starting",
    }

    radar_configs = []
    radar_risk = None
    radar_enabled = bool(radar_hardware.get("enabled", False)) and not args.disable_radar
    radar_load_error = ""
    if radar_enabled:
        radar_config_path = str(args.mr20_config or radar_hardware.get("config", "")).strip()
        try:
            if not radar_config_path:
                raise ValueError("hardware.radar.config or --mr20-config is required")
            radar_configs, radar_risk = load_mr20_config(radar_config_path)
            if not radar_configs:
                raise ValueError("MR20 config has no enabled radars")
        except Exception as exc:
            radar_load_error = f"{type(exc).__name__}: {exc}"
            required, failure_policy = module_failure_policy(radar_hardware)
            if required or failure_policy == "fail_service":
                raise RuntimeError(f"required module radar configuration failed: {exc}") from exc
            module_states["radar"] = "degraded"
            eprint(f"WARN optional radar disabled: {exc}")
            radar_enabled = False

    source_timeouts_s = {
        "vision": float(timing_config.get("vision_timeout_s", event_timeout_s)),
        "radar": float(timing_config.get("radar_timeout_s", event_timeout_s)),
        "manual": float(timing_config.get("manual_timeout_s", max(30.0, event_timeout_s))),
    }
    for radar_config in radar_configs:
        source_timeouts_s[f"radar:{radar_config.name}"] = radar_config.timeout_s
    state = AlertState(
        event_timeout_s=event_timeout_s,
        period_ns=pwm_period_ns,
        level_duty_percent=level_duties if isinstance(level_duties, dict) else None,
        source_timeouts_s=source_timeouts_s,
    )
    legacy_pwm = PwmController(
        Path(args.pwm_root),
        period_ns=pwm_period_ns,
        dry_run=args.dry_run,
        skip_pinmux=args.skip_pinmux,
    )
    haptics, lights, output_policy = build_actuator_runtime(hardware, args, legacy_pwm)
    audio = AudioPlayer(
        Path(args.audio_root or str(audio_config.get("root", AUDIO_ROOT))),
        sample_audio=args.sample_audio,
        dry_run=args.dry_run,
        enabled=(
            bool(hardware_audio.get("enabled", audio_config.get("enabled", False)))
            and not args.no_audio
        ),
        default_sleep_s=args.audio_sleep_s,
        default_timeout_s=args.audio_timeout_s,
        skip_pinmux=args.skip_pinmux,
    )
    detectors: list[DetectorProcess] = []
    modules: dict[str, RoutedModuleProcess] = {}
    radars: list[MR20RadarWorker] = []
    ble: BleNusServer | None = None
    resource_sampler = ResourceSampler()
    last_status_write_s = float("-inf")

    def _stop(_signum: int | None = None, _frame: object | None = None) -> None:
        stop_event.set()

    def _status_payload() -> dict[str, object]:
        return controller_status_payload(
            state,
            detectors,
            modules,
            resource_sampler,
            actuators={"haptics": haptics, "lights": lights},
            radars=radars,
            module_states=module_states,
        )

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        haptics.initialize(preflight_only=args.preflight_only)
        lights.initialize(preflight_only=args.preflight_only)
        module_states["haptics"] = haptics.state
        module_states["lights"] = lights.state
        if args.preflight_only:
            eprint(
                json.dumps(
                    {
                        "hardware_profile": hardware["profile"],
                        "haptics": haptics.status(),
                        "lights": lights.status(),
                        "radar_config_count": len(radar_configs),
                        "radar_config_error": radar_load_error,
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                )
            )
            return 0
        try:
            audio.setup()
            audio.start()
            module_states["audio"] = "online" if audio.enabled else "disabled"
        except Exception as exc:
            required, failure_policy = module_failure_policy(hardware_audio)
            if required or failure_policy == "fail_service":
                raise RuntimeError(f"required module audio failed: {exc}") from exc
            module_states["audio"] = "degraded"
            eprint(f"WARN optional audio degraded: {exc}")

        if radar_enabled:
            assert radar_risk is not None
            for radar_config in radar_configs:
                worker = MR20RadarWorker(
                    radar_config,
                    radar_risk,
                    lambda alert: event_queue.put(radar_alert_to_event(alert)),
                )
                try:
                    worker.start()
                    radars.append(worker)
                    module_states[f"radar:{radar_config.name}"] = "online"
                except Exception as exc:
                    required, failure_policy = module_failure_policy(radar_hardware)
                    if required or failure_policy == "fail_service":
                        raise RuntimeError(f"required radar {radar_config.name} failed: {exc}") from exc
                    module_states[f"radar:{radar_config.name}"] = "degraded"
                    module_states["radar"] = "degraded"
                    eprint(f"WARN optional radar {radar_config.name} degraded: {exc}")
            if radars and module_states["radar"] != "degraded":
                module_states["radar"] = "online"
        elif module_states["radar"] == "starting":
            module_states["radar"] = "disabled"

        detector_cwd = Path(args.detector_cwd) if args.detector_cwd else None
        configured_left, configured_right = detector_commands_from_config(
            config,
            left_video=args.left_video,
            right_video=args.right_video,
        )
        left_detector_command = args.left_detector or configured_left
        right_detector_command = args.right_detector or configured_right
        alternating_detector_command = alternating_detector_command_from_config(config)
        if args.single_camera and not args.detector and not args.disable_vision:
            raise ValueError("--single-camera requires --detector COMMAND")
        if args.disable_vision:
            pass
        elif args.detector:
            detector = DetectorProcess(
                None,
                args.detector,
                event_queue,
                cwd=detector_cwd,
                restart_limit=restart_limit,
                restart_backoff_s=restart_backoff_s,
            )
            detector.start()
            detectors.append(detector)
        elif alternating_detector_command:
            detector = DetectorProcess(
                None,
                alternating_detector_command,
                event_queue,
                cwd=detector_cwd,
                restart_limit=restart_limit,
                restart_backoff_s=restart_backoff_s,
                append_alert_args=False,
            )
            detector.start()
            detectors.append(detector)
        else:
            for side, command in (("left", left_detector_command), ("right", right_detector_command)):
                if not command:
                    continue
                detector = DetectorProcess(
                    side,
                    command,
                    event_queue,
                    cwd=detector_cwd,
                    restart_limit=restart_limit,
                    restart_backoff_s=restart_backoff_s,
                )
                detector.start()
                detectors.append(detector)
        module_states["vision"] = "online" if detectors else "disabled"

        for namespace, command in (("GNSS", args.gnss_command), ("IMU", args.imu_command)):
            if (namespace == "GNSS" and args.disable_gnss) or (namespace == "IMU" and args.disable_imu):
                continue
            if not command:
                module_states[namespace.lower()] = "disabled"
                continue
            module = RoutedModuleProcess(namespace, command, response_queue, cwd=detector_cwd)
            module.start()
            modules[namespace] = module
            module_states[namespace.lower()] = "online"

        if not args.no_ble and not args.disable_ble:
            try:
                ble = BleNusServer(ble_name, command_queue.put)
                ble.start()
                module_states["ble"] = "online"
                eprint(f"BLE advertising as {ble_name}")
            except Exception as exc:
                module_states["ble"] = "degraded"
                eprint(f"WARN BLE disabled: {exc}")

        if args.stdin_jsonl:
            start_stdin_reader(
                event_queue,
                command_queue,
                stop_event,
                stop_on_eof=not detectors,
            )

        while not stop_event.is_set() or not event_queue.empty() or not command_queue.empty() or not response_queue.empty():
            for detector in detectors:
                detector.maybe_restart()
            if args.exit_when_detectors_exit and detectors and all(
                detector.process is not None
                and detector.process.poll() is not None
                and (detector.thread is None or not detector.thread.is_alive())
                for detector in detectors
            ):
                stop_event.set()
            while True:
                try:
                    event = event_queue.get_nowait()
                except queue.Empty:
                    break
                if event_is_stale(event, time.monotonic(), max_event_age_s):
                    eprint(
                        f"ignored stale event source={AlertState.event_source(event)} "
                        f"side={event.side} level={event.level} ts={event.ts}"
                    )
                    continue
                output = state.apply_event(event)
                apply_effective_output(output, haptics, lights, audio, output_policy)
                if ble is not None and should_publish_alert_history(event):
                    ble.send_line(
                        alert_event_ble_payload(
                            event,
                            effective_level=(output.levels or {})[event.side],
                        )
                    )

            while True:
                try:
                    command_text = command_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    route = route_ble_command(command_text)
                    if route.namespace == "AL":
                        command = parse_alert_command("AL " + route.command)
                        if command.kind == "clear":
                            audio.clear()
                        output = state.apply_command(command)
                        apply_effective_output(output, haptics, lights, audio, output_policy)
                        if ble is not None:
                            ble.send_line("OK AL " + route.command)
                    elif route.namespace in ("GNSS", "IMU"):
                        module = modules.get(route.namespace)
                        if module is None:
                            raise RuntimeError(f"{route.namespace} module is not configured")
                        module.send(route.command)
                    elif route.namespace == "SYS":
                        if route.command.upper() != "STATUS":
                            raise ValueError("SYS supports only STATUS")
                        if ble is not None:
                            ble.send_line(
                                json.dumps(
                                    _status_payload(),
                                    separators=(",", ":"),
                                )
                            )
                except Exception as exc:
                    if ble is not None:
                        ble.send_line("ERR " + str(exc))
                    eprint(f"WARN command failed {command_text!r}: {exc}")

            while True:
                try:
                    namespace, response = response_queue.get_nowait()
                except queue.Empty:
                    break
                if ble is not None:
                    ble.send_line(response)
                eprint(f"{namespace} response: {response[:200]}")

            expired = state.expire()
            if expired.expired_source_sides:
                apply_effective_output(expired, haptics, lights, audio, output_policy)
                if ble is not None:
                    for source, side in expired.expired_source_sides:
                        ble.send_line(
                            alert_event_ble_payload(
                                AlertEvent(
                                    side=side,
                                    level=0,
                                    source=source,
                                    ts=time.monotonic(),
                                    clear_reason="source_timeout",
                                ),
                                effective_level=(expired.levels or {})[side],
                            )
                        )
            now_s = time.monotonic()
            haptics.tick(now_s)
            lights.tick(now_s)
            module_states["haptics"] = haptics.state
            module_states["lights"] = lights.state
            for radar in radars:
                radar_status = radar.status()
                radar_name = f"radar:{radar.config.name}"
                if not radar_status["running"] and radar_status["last_error"]:
                    required, failure_policy = module_failure_policy(radar_hardware)
                    module_states[radar_name] = "error" if required else "degraded"
                    module_states["radar"] = module_states[radar_name]
                    if required or failure_policy == "fail_service":
                        raise RuntimeError(
                            f"required radar {radar.config.name} stopped: {radar_status['last_error']}"
                        )
            if status_file and now_s - last_status_write_s >= 1.0:
                try:
                    atomic_write_json(
                        status_file,
                        _status_payload(),
                    )
                except OSError as exc:
                    eprint(f"WARN could not update controller status file: {exc}")
                last_status_write_s = now_s
            time.sleep(args.poll_interval)
    finally:
        stop_event.set()
        for radar in radars:
            radar.stop()
        for detector in detectors:
            detector.stop()
        for module in modules.values():
            module.stop()
        if ble is not None:
            ble.stop()
        audio.stop()
        haptics.stop_all()
        lights.stop_all()
    return 0


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SS928 single/dual-camera smart-bag alert controller.")
    parser.add_argument("--config", default="", help="JSON config for PWM duty levels, timeout, and optional audio.")
    parser.add_argument("--detector", default="", help="Single-camera detector base command. The controller appends --side auto and --emit-alert-jsonl.")
    parser.add_argument("--single-camera", action="store_true", help="Legacy compatibility: require and use the single --detector command.")
    parser.add_argument("--left-detector", default="", help="Base command for the left vision detector.")
    parser.add_argument("--right-detector", default="", help="Base command for the right vision detector.")
    parser.add_argument("--left-video", default="", help="Override configured left camera with a video file for dual simulation.")
    parser.add_argument("--right-video", default="", help="Override configured right camera with a video file for dual simulation.")
    parser.add_argument("--gnss-command", default="", help="Optional GNSS subprocess command with --command-stdin --no-ble.")
    parser.add_argument("--imu-command", default="", help="Optional BMI270 subprocess command with --command-stdin --no-ble.")
    parser.add_argument("--detector-cwd", default="", help="Working directory for detector commands.")
    parser.add_argument("--stdin-jsonl", action="store_true", help="Also read vision JSONL or AL commands from stdin.")
    parser.add_argument("--pwm-root", default="/sys/class/pwm", help="Linux PWM sysfs root.")
    parser.add_argument("--pwm-period-ns", type=int, default=None, help="PWM period in ns; overrides config.")
    parser.add_argument("--event-timeout", type=float, default=None, help="Seconds before stale side vibration is stopped; overrides config.")
    parser.add_argument("--max-event-age", type=float, default=None, help="Reject vision events older than this many seconds; overrides config.")
    parser.add_argument("--poll-interval", type=float, default=0.05, help="Controller loop sleep interval in seconds.")
    parser.add_argument("--detector-restart-limit", type=int, default=None, help="Maximum child detector restarts; overrides config.")
    parser.add_argument("--detector-restart-backoff", type=float, default=None, help="Initial child detector restart backoff seconds.")
    parser.add_argument("--status-file", default="", help="Controller JSON status file consumed by the video gateway.")
    parser.add_argument("--exit-when-detectors-exit", action="store_true", help="Exit after all detector children finish; intended for finite video simulation.")
    parser.add_argument("--audio-root", default="", help="Root containing L1..R4 audio folders; overrides config.")
    parser.add_argument("--sample-audio", default=SAMPLE_AUDIO, help="Path to sample_audio player.")
    parser.add_argument("--audio-sleep-s", type=float, default=5.0, help="Fallback seconds before sending ENTER to sample_audio.")
    parser.add_argument("--audio-timeout-s", type=float, default=13.0, help="Fallback sample_audio timeout seconds.")
    parser.add_argument("--ble-name", default=None, help="BLE advertisement name; overrides config.")
    parser.add_argument("--no-ble", action="store_true", help="Disable BLE debug command server.")
    parser.add_argument("--disable-ble", action="store_true", help="Disable the unified BLE service (diagnostic alias).")
    parser.add_argument("--no-audio", action="store_true", help="Disable audio playback.")
    parser.add_argument("--mr20-config", default="", help="Override hardware.radar.config with an MR20 JSON config.")
    parser.add_argument("--disable-haptics", action="store_true", help="Disable all haptic hardware outputs.")
    parser.add_argument("--disable-lights", action="store_true", help="Disable both side warning lights.")
    parser.add_argument("--disable-radar", action="store_true", help="Disable all MR20 workers.")
    parser.add_argument("--disable-vision", action="store_true", help="Do not start configured vision detectors.")
    parser.add_argument("--disable-imu", action="store_true", help="Do not start the configured IMU subprocess.")
    parser.add_argument("--disable-gnss", action="store_true", help="Do not start the configured GNSS subprocess.")
    parser.add_argument("--skip-pinmux", action="store_true", help="Skip bspmm pinmux setup.")
    parser.add_argument("--dry-run", action="store_true", help="Print PWM/audio actions without touching hardware.")
    parser.add_argument("--preflight-only", action="store_true", help="Validate configuration and preflight enabled actuators without starting services.")
    return parser.parse_args(argv)


def main() -> None:
    raise SystemExit(run_controller(parse_args()))


if __name__ == "__main__":
    main()
