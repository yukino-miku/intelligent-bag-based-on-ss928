from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable


DEFAULT_DEVICE_NAME = "USB Camera"
RESOLUTION_PRESETS = ("1280x720", "1920x1080", "2560x1440", "800x600", "640x480")
DEFAULT_VIDEO_SIZE = RESOLUTION_PRESETS[0]
DEFAULT_FRAMERATE = 30
DEFAULT_CRF = 18
DEFAULT_PRESET = "veryfast"


def default_output_dir() -> Path:
    env_dir = os.environ.get("USB_CAMERA_RECORDER_OUTPUT_DIR")
    if env_dir:
        return Path(env_dir)

    fixed_project_dir = Path(r"D:\mywork\code\embedded-contest-project\08_media\camera_data")
    if fixed_project_dir.parent.exists():
        return fixed_project_dir

    search_roots = [Path.cwd()]
    executable_or_source = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()
    search_roots.append(executable_or_source.parent)

    for root in search_roots:
        for candidate in [root, *root.parents]:
            if (candidate / "06_software").exists() and (candidate / "08_media").exists():
                return candidate / "08_media" / "camera_data"

    return Path.home() / "Videos" / "usb_camera_data"


@dataclass(frozen=True)
class RecordingConfig:
    device_name: str = DEFAULT_DEVICE_NAME
    video_size: str = DEFAULT_VIDEO_SIZE
    framerate: int = DEFAULT_FRAMERATE
    output_dir: Path = field(default_factory=default_output_dir)
    crf: int = DEFAULT_CRF
    preset: str = DEFAULT_PRESET
    preview_enabled: bool = True


def ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def make_output_path(config: RecordingConfig, *, now: dt.datetime | None = None) -> Path:
    timestamp = (now or dt.datetime.now()).strftime("%Y%m%d_%H%M%S")
    return config.output_dir / f"usbcam_{timestamp}.mp4"


def build_ffmpeg_command(config: RecordingConfig, output_path: Path) -> list[str]:
    command = [
        "ffmpeg",
        "-y",
        "-fflags",
        "nobuffer",
        "-f",
        "dshow",
        "-video_size",
        config.video_size,
        "-framerate",
        str(config.framerate),
        "-vcodec",
        "mjpeg",
        "-i",
        f"video={config.device_name}",
        "-map",
        "0:v",
        "-c:v",
        "libx264",
        "-preset",
        config.preset,
        "-crf",
        str(config.crf),
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]

    if config.preview_enabled:
        command.extend(
            [
                "-map",
                "0:v",
                "-c:v:1",
                "copy",
                "-f",
                "mjpeg",
                "pipe:1",
            ]
        )

    return command


def build_ffplay_command() -> list[str]:
    return [
        "ffplay",
        "-window_title",
        "USB Camera Preview",
        "-autoexit",
        "-probesize",
        "32",
        "-analyzeduration",
        "0",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-framedrop",
        "-f",
        "mjpeg",
        "-i",
        "pipe:0",
    ]


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remaining_seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"


class FFmpegRecordingSession:
    def __init__(
        self,
        process: subprocess.Popen[bytes],
        output_path: Path,
        *,
        started_at: dt.datetime | None = None,
        log_file: BinaryIO | None = None,
        preview_process: subprocess.Popen[bytes] | None = None,
        preview_log_file: BinaryIO | None = None,
    ) -> None:
        self.process = process
        self.output_path = output_path
        self.started_at = started_at or dt.datetime.now()
        self._log_file = log_file
        self._preview_process = preview_process
        self._preview_log_file = preview_log_file

    def is_running(self) -> bool:
        poll = getattr(self.process, "poll", None)
        return poll is None or poll() is None

    def elapsed_seconds(self) -> int:
        return int((dt.datetime.now() - self.started_at).total_seconds())

    def stop(self, *, timeout: float = 8.0) -> None:
        try:
            if self.process.stdin is not None:
                self.process.stdin.write(b"q\n")
                self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass

        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=3.0)
        finally:
            if self._preview_process is not None:
                try:
                    self._preview_process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    self._preview_process.terminate()
                    self._preview_process.wait(timeout=3.0)
            if self._preview_log_file is not None:
                self._preview_log_file.close()
            if self._log_file is not None:
                self._log_file.close()


PopenFactory = Callable[..., subprocess.Popen[bytes]]


def start_recording(
    config: RecordingConfig,
    *,
    now: dt.datetime | None = None,
    popen_factory: PopenFactory = subprocess.Popen,
) -> FFmpegRecordingSession:
    ensure_output_dir(config.output_dir)
    output_path = make_output_path(config, now=now)
    log_path = output_path.with_suffix(".ffmpeg.log")
    command = build_ffmpeg_command(config, output_path)
    log_file = log_path.open("wb")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process: subprocess.Popen[bytes] | None = None
    preview_process: subprocess.Popen[bytes] | None = None
    preview_log_file: BinaryIO | None = None
    try:
        process = popen_factory(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE if config.preview_enabled else log_file,
            stderr=log_file if config.preview_enabled else subprocess.STDOUT,
            creationflags=creationflags,
        )
        if config.preview_enabled:
            preview_log_file = output_path.with_suffix(".ffplay.log").open("wb")
            preview_process = popen_factory(
                build_ffplay_command(),
                stdin=process.stdout,
                stdout=preview_log_file,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
            if process.stdout is not None:
                process.stdout.close()
    except Exception:
        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=3.0)
            except Exception:
                pass
        if preview_log_file is not None:
            preview_log_file.close()
        log_file.close()
        raise

    return FFmpegRecordingSession(
        process,
        output_path,
        started_at=now,
        log_file=log_file,
        preview_process=preview_process,
        preview_log_file=preview_log_file,
    )
