from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class FfmpegCameraConfig:
    device_name: str = "USB Camera"
    width: int = 1920
    height: int = 1080
    fps: float = 30.0


def build_ffmpeg_mjpeg_command(config: FfmpegCameraConfig) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-probesize",
        "32",
        "-analyzeduration",
        "0",
        "-rtbufsize",
        "2M",
        "-f",
        "dshow",
        "-video_size",
        f"{config.width}x{config.height}",
        "-framerate",
        str(int(config.fps)),
        "-vcodec",
        "mjpeg",
        "-i",
        f"video={config.device_name}",
        "-an",
        "-c:v",
        "copy",
        "-f",
        "mjpeg",
        "-flush_packets",
        "1",
        "pipe:1",
    ]


class MjpegFrameParser:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buffer.extend(chunk)
        frames: list[bytes] = []

        while True:
            start = self._buffer.find(b"\xff\xd8")
            if start < 0:
                self._buffer.clear()
                break

            if start > 0:
                del self._buffer[:start]

            end = self._buffer.find(b"\xff\xd9", 2)
            if end < 0:
                break

            frames.append(bytes(self._buffer[: end + 2]))
            del self._buffer[: end + 2]

        return frames


class FfmpegMjpegCameraCapture:
    def __init__(self, config: FfmpegCameraConfig) -> None:
        self.config = config
        self._condition = threading.Condition()
        self._latest_frame = None
        self._latest_sequence = 0
        self._last_delivered_sequence = 0
        self._closed = False
        self._process = subprocess.Popen(
            build_ffmpeg_mjpeg_command(config),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def is_opened(self) -> bool:
        return self._process.poll() is None and self._process.stdout is not None

    def read(self):
        with self._condition:
            while self._latest_sequence == self._last_delivered_sequence and not self._closed:
                self._condition.wait(timeout=1.0)

            if self._latest_frame is None or self._latest_sequence == self._last_delivered_sequence:
                return False, None

            self._last_delivered_sequence = self._latest_sequence
            return True, self._latest_frame

    def _reader_loop(self) -> None:
        parser = MjpegFrameParser()
        stdout = self._process.stdout
        if stdout is None:
            self._mark_closed()
            return

        while self._process.poll() is None:
            chunk = stdout.read(65536)
            if not chunk:
                break

            for jpg in parser.feed(chunk):
                frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    continue
                with self._condition:
                    self._latest_frame = frame
                    self._latest_sequence += 1
                    self._condition.notify_all()

        self._mark_closed()

    def _mark_closed(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def release(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=3.0)
        self._reader_thread.join(timeout=3.0)
        self._mark_closed()
