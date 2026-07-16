from __future__ import annotations

import json
import sys
import threading
import time
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlparse


RISK_NAMES = ("SAFE", "ATTENTION", "CAUTION", "DANGER", "EMERGENCY")


class DaemonThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False


class DetectorVideoServer:
    """Serve one detector's latest frames without touching its camera device."""

    def __init__(
        self,
        side: str,
        device: str,
        bind: str = "127.0.0.1",
        port: int = 18081,
        stream_width: int = 640,
        stream_height: int = 360,
        jpeg_quality: int = 70,
        stream_fps_limit: float = 8.0,
        access_token: str = "",
        status_provider: Callable[[], dict[str, object]] | None = None,
    ) -> None:
        if side not in ("left", "right"):
            raise ValueError("detector video side must be left or right")
        self.side = side
        self.device = str(device)
        self.bind = bind
        self.port = int(port)
        self.stream_width = max(0, int(stream_width))
        self.stream_height = max(0, int(stream_height))
        self.jpeg_quality = min(max(int(jpeg_quality), 20), 95)
        self.stream_fps_limit = min(max(float(stream_fps_limit), 0.5), 30.0)
        self.access_token = access_token
        self.status_provider = status_provider
        self._lock = threading.Condition()
        self._frames: dict[str, tuple[int, object, float] | None] = {"raw": None, "overlay": None}
        self._jpeg_cache: dict[str, tuple[int, bytes] | None] = {"raw": None, "overlay": None}
        self._sequence = 0
        self._runtime_status: dict[str, object] = {
            "side": side,
            "online": False,
            "device": self.device,
            "risk_level": 0,
            "risk_name": "SAFE",
        }
        self._client_count = {"raw": 0, "overlay": 0}
        self._last_demand_s = {"raw": float("-inf"), "overlay": float("-inf")}
        self._served_times: deque[float] = deque(maxlen=120)
        self._encode_ms: deque[float] = deque(maxlen=120)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802
                owner._handle_get(self)

            def log_message(self, fmt: str, *args: object) -> None:
                print(f"[{owner.side}] stream {fmt % args}", file=sys.stderr, flush=True)

        self._httpd = DaemonThreadingHTTPServer((self.bind, self.port), Handler)
        self.port = int(self._httpd.server_address[1])
        self._thread = threading.Thread(target=self._httpd.serve_forever, name=f"stream-{self.side}", daemon=True)
        self._thread.start()
        print(f"[{self.side}] detector stream listening on {self.bind}:{self.port}", file=sys.stderr, flush=True)

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        with self._lock:
            self._lock.notify_all()

    def publish(self, raw_frame: object, overlay_frame: object | None, status: dict[str, object]) -> None:
        now_s = time.monotonic()
        with self._lock:
            self._sequence += 1
            self._frames["raw"] = (self._sequence, raw_frame, now_s)
            if overlay_frame is not None:
                self._frames["overlay"] = (self._sequence, overlay_frame, now_s)
            self._runtime_status.update(status)
            self._runtime_status.update({"side": self.side, "device": self.device})
            self._lock.notify_all()

    def wants_overlay(self) -> bool:
        with self._lock:
            return self._client_count["overlay"] > 0 or time.monotonic() - self._last_demand_s["overlay"] < 2.0

    def status(self) -> dict[str, object]:
        with self._lock:
            payload = dict(self._runtime_status)
            latest = self._frames["raw"]
            clients = sum(self._client_count.values())
            served_times = tuple(self._served_times)
            encode_values = tuple(self._encode_ms)
        if self.status_provider is not None:
            try:
                payload.update(self.status_provider())
            except Exception as exc:
                payload.update({"online": False, "status_error": str(exc)})
        now_s = time.monotonic()
        stream_fps = 0.0
        if len(served_times) >= 2:
            stream_fps = (len(served_times) - 1) / max(served_times[-1] - served_times[0], 1e-6)
        payload.update(
            {
                "online": bool(payload.get("online", latest is not None)),
                "stream_fps": round(stream_fps, 2),
                "video_client_count": clients,
                "jpeg_encode_ms": round(sum(encode_values) / len(encode_values), 2) if encode_values else 0.0,
                "last_frame_age_ms": round((now_s - latest[2]) * 1000.0, 1) if latest else None,
                "jpeg_stream_width": self.stream_width,
                "jpeg_stream_height": self.stream_height,
                "jpeg_quality": self.jpeg_quality,
                "stream_fps_limit": self.stream_fps_limit,
            }
        )
        return payload

    def _authorized(self, handler: BaseHTTPRequestHandler, query: dict[str, list[str]]) -> bool:
        if not self.access_token:
            return True
        query_token = query.get("token", [""])[0]
        auth = handler.headers.get("Authorization", "")
        return query_token == self.access_token or auth == f"Bearer {self.access_token}"

    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        query = parse_qs(parsed.query)
        if not self._authorized(handler, query):
            self._send_json(handler, HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        base = f"/api/v1/camera/{self.side}"
        if parsed.path in ("/api/v1/status", "/api/v1/cameras", f"{base}/status"):
            status = self.status()
            payload: object = [status] if parsed.path == "/api/v1/cameras" else status
            self._send_json(handler, HTTPStatus.OK, payload)
            return
        if parsed.path == f"{base}/snapshot.jpg":
            self._send_snapshot(handler, self._view_from_query(query))
            return
        if parsed.path == f"{base}/mjpeg":
            self._send_mjpeg(handler, self._view_from_query(query))
            return
        if parsed.path == "/":
            body = self._debug_page(query.get("token", [""])[0]).encode("utf-8")
            self._send_bytes(handler, HTTPStatus.OK, "text/html; charset=utf-8", body)
            return
        self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "not_found"})

    @staticmethod
    def _view_from_query(query: dict[str, list[str]]) -> str:
        return "raw" if query.get("view", ["overlay"])[0] == "raw" else "overlay"

    def _get_jpeg(self, view: str, wait_s: float = 1.5) -> bytes | None:
        import cv2

        with self._lock:
            self._last_demand_s[view] = time.monotonic()
            deadline = time.monotonic() + max(0.0, wait_s)
            while self._frames[view] is None and self._frames["raw"] is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return None
                self._lock.wait(timeout=remaining)
            frame_item = self._frames[view] or self._frames["raw"]
            if frame_item is None:
                return None
            sequence, frame, _captured_at_s = frame_item
            cached = self._jpeg_cache[view]
            if cached is not None and cached[0] == sequence:
                return cached[1]

        started = time.perf_counter()
        output = frame
        if self.stream_width > 0 and self.stream_height > 0:
            height, width = frame.shape[:2]
            if (width, height) != (self.stream_width, self.stream_height):
                output = cv2.resize(frame, (self.stream_width, self.stream_height), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", output, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        if not ok:
            return None
        jpeg = encoded.tobytes()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        with self._lock:
            self._jpeg_cache[view] = (sequence, jpeg)
            self._encode_ms.append(elapsed_ms)
        return jpeg

    def _send_snapshot(self, handler: BaseHTTPRequestHandler, view: str) -> None:
        jpeg = self._get_jpeg(view)
        if jpeg is None:
            self._send_json(handler, HTTPStatus.SERVICE_UNAVAILABLE, {"error": "camera_offline", "side": self.side})
            return
        with self._lock:
            self._served_times.append(time.monotonic())
        self._send_bytes(handler, HTTPStatus.OK, "image/jpeg", jpeg, extra_headers={"Cache-Control": "no-store"})

    def _send_mjpeg(self, handler: BaseHTTPRequestHandler, view: str) -> None:
        boundary = "smartbagframe"
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary}")
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        with self._lock:
            self._client_count[view] += 1
            self._last_demand_s[view] = time.monotonic()
        try:
            interval_s = 1.0 / self.stream_fps_limit
            while True:
                started = time.monotonic()
                jpeg = self._get_jpeg(view)
                if jpeg is None:
                    time.sleep(0.2)
                    continue
                handler.wfile.write(f"--{boundary}\r\n".encode("ascii"))
                handler.wfile.write(b"Content-Type: image/jpeg\r\n")
                handler.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                handler.wfile.write(jpeg)
                handler.wfile.write(b"\r\n")
                handler.wfile.flush()
                with self._lock:
                    self._served_times.append(time.monotonic())
                remaining = interval_s - (time.monotonic() - started)
                if remaining > 0.0:
                    time.sleep(remaining)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            with self._lock:
                self._client_count[view] = max(0, self._client_count[view] - 1)

    @staticmethod
    def _send_json(handler: BaseHTTPRequestHandler, status: HTTPStatus, payload: object) -> None:
        DetectorVideoServer._send_bytes(
            handler,
            status,
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
            extra_headers={"Cache-Control": "no-store"},
        )

    @staticmethod
    def _send_bytes(
        handler: BaseHTTPRequestHandler,
        status: HTTPStatus,
        content_type: str,
        body: bytes,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or {}).items():
            handler.send_header(key, value)
        handler.end_headers()
        handler.wfile.write(body)

    def _debug_page(self, token: str = "") -> str:
        base = f"/api/v1/camera/{self.side}"
        token_query = urlencode({"token": token}) if token else ""
        stream_suffix = "&" + token_query if token_query else ""
        status_suffix = "?" + token_query if token_query else ""
        return f"""<!doctype html><html><head><meta charset=\"utf-8\"><title>SmartBag {self.side}</title></head>
<body><h1>{self.side} camera</h1><img style=\"max-width:100%\" src=\"{base}/mjpeg?view=overlay{stream_suffix}\"><pre id=\"s\"></pre>
<script>setInterval(()=>fetch('{base}/status{status_suffix}').then(r=>r.json()).then(v=>s.textContent=JSON.stringify(v,null,2)),1000)</script></body></html>"""
