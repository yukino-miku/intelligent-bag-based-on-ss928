from __future__ import annotations

import hmac
import json
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote_plus, urlparse


class _DaemonServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class AlternatingCameraGateway:
    """Serve cached left/right MJPEG frames without opening camera devices."""

    def __init__(
        self,
        capture,
        *,
        bind: str = "0.0.0.0",
        port: int = 0,
        access_token: str = "",
        stream_fps_limit: float = 5.0,
    ) -> None:
        self.capture = capture
        self.bind = bind
        self.port = int(port)
        self.access_token = access_token
        self.stream_fps_limit = max(0.5, min(float(stream_fps_limit), 30.0))
        self._httpd: _DaemonServer | None = None
        self._thread: threading.Thread | None = None
        self.gateway_clients = 0
        self._client_lock = threading.Lock()

    def start(self) -> None:
        if self._httpd is not None:
            return
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                owner._handle(self)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._httpd = _DaemonServer((self.bind, self.port), Handler)
        self.port = int(self._httpd.server_address[1])
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="alternating-gateway", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._httpd = None

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        query = parse_qs(parsed.query)
        if not self._authorized(handler, query):
            self._json(handler, HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        if parsed.path in ("/api/v1/status", "/api/v1/cameras"):
            status = self.capture.status()
            cameras = [self._side_status(side, status) for side in ("left", "right")]
            payload = cameras if parsed.path.endswith("cameras") else {**status, "cameras": cameras}
            self._json(handler, HTTPStatus.OK, payload)
            return
        for side in ("left", "right"):
            base = f"/api/v1/camera/{side}"
            if parsed.path == f"{base}/status":
                self._json(handler, HTTPStatus.OK, self._side_status(side, self.capture.status()))
                return
            if parsed.path == f"{base}/snapshot.jpg":
                self._snapshot(handler, side)
                return
            if parsed.path == f"{base}/mjpeg":
                self._mjpeg(handler, side)
                return
        if parsed.path == "/":
            page = self._debug_page(query.get("token", [""])[0]).encode("utf-8")
            handler.send_response(HTTPStatus.OK)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.send_header("Content-Length", str(len(page)))
            handler.end_headers()
            handler.wfile.write(page)
            return
        self._json(handler, HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def _authorized(self, handler: BaseHTTPRequestHandler, query: dict[str, list[str]]) -> bool:
        if not self.access_token:
            return True
        supplied = query.get("token", [""])[0]
        if not supplied:
            auth = handler.headers.get("Authorization", "")
            supplied = auth[7:] if auth.startswith("Bearer ") else ""
        return hmac.compare_digest(supplied, self.access_token)

    def _side_status(self, side: str, status: dict[str, object]) -> dict[str, object]:
        age = status.get(f"{side}_last_frame_age_ms")
        online = bool(status.get(f"{side}_online"))
        active = status.get("active_camera") == side
        if not online:
            frame_state = "offline"
        elif active and isinstance(age, (int, float)) and age <= 500.0:
            frame_state = "live"
        else:
            frame_state = "cached"
        return {
            "side": side,
            "online": online,
            "active": active,
            "frame_state": frame_state,
            "last_frame_age_ms": age,
            "effective_fps": status.get(f"{side}_effective_fps", 0.0),
            "last_error": status.get(f"{side}_last_error", ""),
            "backend": status.get("backend", ""),
        }

    def _snapshot(self, handler: BaseHTTPRequestHandler, side: str) -> None:
        frame = self.capture.latest_frame(side)
        if frame is None:
            self._json(handler, HTTPStatus.SERVICE_UNAVAILABLE, {"error": "camera_offline", "side": side})
            return
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", "image/jpeg")
        handler.send_header("Content-Length", str(len(frame.data)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Frame-Age-Ms", f"{max(0.0, time.monotonic() - frame.captured_at_s) * 1000.0:.1f}")
        handler.end_headers()
        handler.wfile.write(frame.data)

    def _mjpeg(self, handler: BaseHTTPRequestHandler, side: str) -> None:
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        interval_s = 1.0 / self.stream_fps_limit
        last_sequence = -1
        with self._client_lock:
            self.gateway_clients += 1
        try:
            while True:
                frame = self.capture.latest_frame(side)
                if frame is None or frame.sequence == last_sequence:
                    time.sleep(min(interval_s, 0.1))
                    continue
                last_sequence = frame.sequence
                handler.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                handler.wfile.write(f"Content-Length: {len(frame.data)}\r\n\r\n".encode("ascii"))
                handler.wfile.write(frame.data)
                handler.wfile.write(b"\r\n")
                handler.wfile.flush()
                time.sleep(interval_s)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        finally:
            with self._client_lock:
                self.gateway_clients = max(0, self.gateway_clients - 1)

    @staticmethod
    def _json(handler: BaseHTTPRequestHandler, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)

    @staticmethod
    def _debug_page(token: str) -> str:
        suffix = f"&token={quote_plus(token)}" if token else ""
        status_suffix = f"?token={quote_plus(token)}" if token else ""
        return f"""<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><title>交替双摄实验</title>
<style>body{{font-family:sans-serif;margin:20px;background:#111;color:#eee}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}section{{border:1px solid #555;padding:10px}}img{{width:100%;background:#222}}pre{{white-space:pre-wrap}}</style>
<body><h1>SS928 交替双摄实验</h1><p>任意时刻仅一侧采集；另一侧显示最近缓存帧。</p><div class=\"grid\">
<section><h2>左侧</h2><img src=\"/api/v1/camera/left/mjpeg?view=raw{suffix}\"><pre id=\"left\"></pre></section>
<section><h2>右侧</h2><img src=\"/api/v1/camera/right/mjpeg?view=raw{suffix}\"><pre id=\"right\"></pre></section></div>
<script>for(const s of ['left','right'])setInterval(()=>fetch(`/api/v1/camera/${{s}}/status{status_suffix}`).then(r=>r.json()).then(v=>document.getElementById(s).textContent=JSON.stringify(v,null,2)).catch(e=>document.getElementById(s).textContent=e),500)</script></body></html>"""

    def __enter__(self) -> "AlternatingCameraGateway":
        self.start()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.stop()
