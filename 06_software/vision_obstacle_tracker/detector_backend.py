from __future__ import annotations

from abc import ABC, abstractmethod
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
from typing import Any


class DetectorBackend(ABC):
    @property
    @abstractmethod
    def names(self) -> object:
        raise NotImplementedError

    @abstractmethod
    def track(self, frame: object, **kwargs: object) -> object:
        raise NotImplementedError

    def detect(self, frame: object, **kwargs: object) -> object:
        return self.track(frame, persist=False, **kwargs)

    def close(self) -> None:
        return None


class UltralyticsBackend(DetectorBackend):
    def __init__(self, model: Any) -> None:
        self.model = model

    @property
    def names(self) -> object:
        return self.model.names

    def track(self, frame: object, **kwargs: object) -> object:
        return self.model.track(frame, **kwargs)

    def detect(self, frame: object, **kwargs: object) -> object:
        return self.model.predict(frame, **kwargs)


class Ss928OmBackend(DetectorBackend):
    def __init__(
        self,
        model_path: str | Path,
        *,
        runner_path: str | Path | None = None,
        imgsz: int = 640,
        confidence: float = 0.25,
        nms: float = 0.45,
        max_det: int = 50,
        target_classes: str = "car,bicycle,motorcycle,bus,truck",
        response_timeout_s: float = 5.0,
    ) -> None:
        self.model_path = Path(model_path)
        default_runner = Path(__file__).resolve().parent / "ss928_backend" / "bin" / "ss928_detection_runner"
        self.runner_path = Path(runner_path or os.environ.get("SS928_DETECTION_RUNNER", default_runner))
        self.imgsz = int(imgsz)
        if self.imgsz != 640:
            raise ValueError(
                "The current SS928 native runner supports only a fixed 640x640 OM input; "
                f"got imgsz={self.imgsz}."
            )
        self._frame_index = 0
        self._closed = False
        self._response_timeout_s = max(0.1, float(response_timeout_s))
        self._request_lock = threading.Lock()
        self._temp_dir = tempfile.TemporaryDirectory(prefix="smartbag-om-")
        if not self.model_path.is_file():
            self._temp_dir.cleanup()
            raise RuntimeError(f"SS928 OM model not found: {self.model_path}")
        if not self.runner_path.is_file():
            self._temp_dir.cleanup()
            raise RuntimeError(
                f"SS928 live OM runner not found: {self.runner_path}. "
                "Build ss928_backend/bin/ss928_detection_runner on the board first."
            )
        self._command = [
            str(self.runner_path),
            "--model", str(self.model_path),
            "--input", "-",
            "--source-width", str(self.imgsz),
            "--source-height", str(self.imgsz),
            "--conf", str(float(confidence)),
            "--nms", str(float(nms)),
            "--max-det", str(int(max_det)),
            "--target-classes", target_classes,
            "--server",
        ]
        self._process = None
        self._stdout_queue = None
        try:
            self._start_process()
        except Exception:
            self._temp_dir.cleanup()
            raise

    def _start_process(self) -> None:
        process = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        output_queue: "queue.Queue[str | None]" = queue.Queue()
        self._process = process
        self._stdout_queue = output_queue
        threading.Thread(
            target=self._read_stdout,
            args=(process, output_queue),
            name="ss928-om-stdout",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._drain_stderr,
            args=(process,),
            name="ss928-om-stderr",
            daemon=True,
        ).start()

    @property
    def names(self) -> object:
        return {1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

    def track(self, frame: object, **kwargs: object) -> object:
        raise RuntimeError("SS928 OM snapshot backend does not support tracking; call detect()")

    def detect(self, frame: object, **kwargs: object) -> object:
        if self._closed:
            raise RuntimeError("SS928 OM runner is closed")
        source_height, source_width = frame.shape[:2]  # type: ignore[attr-defined]
        nv12 = _bgr_letterbox_to_nv12(frame, self.imgsz)
        frame_index = self._frame_index
        self._frame_index += 1
        input_path = Path(self._temp_dir.name) / f"frame-{frame_index}.nv12"
        input_path.write_bytes(nv12)
        try:
            with self._request_lock:
                try:
                    return self._request(frame_index, input_path, source_width, source_height)
                except Exception as first_error:
                    self._restart_process()
                    try:
                        return self._request(frame_index, input_path, source_width, source_height)
                    except Exception as retry_error:
                        raise RuntimeError(
                            f"SS928 OM runner failed and restart did not recover: {retry_error}"
                        ) from first_error
        finally:
            input_path.unlink(missing_ok=True)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_process()
        self._temp_dir.cleanup()

    def _request(self, frame_index: int, input_path: Path, source_width: int, source_height: int) -> object:
        process = self._process
        output_queue = self._stdout_queue
        if process is None or output_queue is None or process.poll() is not None or process.stdin is None:
            raise RuntimeError("SS928 OM runner is not running")
        process.stdin.write(f"{frame_index}\t{input_path}\t{source_width}\t{source_height}\n")
        process.stdin.flush()
        try:
            line = output_queue.get(timeout=self._response_timeout_s)
        except queue.Empty as exc:
            raise RuntimeError(f"SS928 OM runner response timed out after {self._response_timeout_s:.1f}s") from exc
        if line is None:
            raise RuntimeError(f"SS928 OM runner exited with code {process.poll()}")
        payload = json.loads(line)
        if payload.get("type") != "detections" or int(payload.get("frame_index", -1)) != frame_index:
            raise RuntimeError("SS928 OM runner returned an invalid or out-of-order response")
        return payload

    def _restart_process(self) -> None:
        self._stop_process()
        if self._closed:
            raise RuntimeError("SS928 OM runner is closed")
        self._start_process()

    def _stop_process(self) -> None:
        process = self._process
        self._process = None
        self._stdout_queue = None
        if process is None:
            return
        if process.poll() is None:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()

    @staticmethod
    def _read_stdout(process: subprocess.Popen[str], output_queue: "queue.Queue[str | None]") -> None:
        assert process.stdout is not None
        for line in process.stdout:
            output_queue.put(line)
        output_queue.put(None)

    @staticmethod
    def _drain_stderr(process: subprocess.Popen[str]) -> None:
        assert process.stderr is not None
        for line in process.stderr:
            print(f"[ss928-om] {line.rstrip()}", file=sys.stderr, flush=True)


def _bgr_letterbox_to_nv12(frame: object, imgsz: int) -> bytes:
    import cv2
    import numpy as np

    height, width = frame.shape[:2]  # type: ignore[attr-defined]
    scale = min(imgsz / max(width, 1), imgsz / max(height, 1))
    resized_width = max(1, int(round(width * scale)))
    resized_height = max(1, int(round(height * scale)))
    resized = cv2.resize(frame, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
    letterbox = np.full((imgsz, imgsz, 3), 114, dtype=np.uint8)
    offset_x = (imgsz - resized_width) // 2
    offset_y = (imgsz - resized_height) // 2
    letterbox[offset_y:offset_y + resized_height, offset_x:offset_x + resized_width] = resized
    i420 = cv2.cvtColor(letterbox, cv2.COLOR_BGR2YUV_I420).reshape(-1)
    y_size = imgsz * imgsz
    chroma_size = y_size // 4
    y_plane = i420[:y_size]
    u_plane = i420[y_size:y_size + chroma_size]
    v_plane = i420[y_size + chroma_size:y_size + chroma_size * 2]
    uv_plane = np.empty(chroma_size * 2, dtype=np.uint8)
    uv_plane[0::2] = u_plane
    uv_plane[1::2] = v_plane
    return np.concatenate((y_plane, uv_plane)).tobytes()
