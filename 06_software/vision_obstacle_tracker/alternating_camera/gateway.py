from __future__ import annotations

import hmac
import json
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, quote_plus, urlparse


class _DaemonServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


@dataclass(frozen=True)
class PublishedJpeg:
    side: str
    view: str
    data: bytes
    sequence: int
    captured_at_s: float
    published_at_s: float
    metadata: dict[str, object] = field(default_factory=dict)


class AlternatingCameraGateway:
    """Serve published raw/overlay frames without opening camera devices."""

    def __init__(
        self,
        capture,
        *,
        bind: str = "0.0.0.0",
        port: int = 0,
        access_token: str = "",
        stream_fps_limit: float = 5.0,
        status_provider: Callable[[], dict[str, object]] | None = None,
    ) -> None:
        self.capture = capture
        self.bind = bind
        self.port = int(port)
        self.access_token = access_token
        self.stream_fps_limit = max(0.5, min(float(stream_fps_limit), 30.0))
        self.status_provider = status_provider
        self._httpd: _DaemonServer | None = None
        self._thread: threading.Thread | None = None
        self.gateway_clients = 0
        self._client_lock = threading.Lock()
        self._frame_lock = threading.Lock()
        self._latest: dict[tuple[str, str], PublishedJpeg] = {}

    def publish_raw(self, frame, metadata: dict[str, object] | None = None) -> None:
        self._publish(
            PublishedJpeg(
                side=frame.side,
                view="raw",
                data=bytes(frame.data),
                sequence=int(frame.sequence),
                captured_at_s=float(frame.captured_at_s),
                published_at_s=time.monotonic(),
                metadata=dict(metadata or {}),
            )
        )

    def publish_overlay(
        self,
        side: str,
        data: bytes,
        *,
        sequence: int,
        captured_at_s: float,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self._publish(
            PublishedJpeg(
                side=side,
                view="overlay",
                data=bytes(data),
                sequence=int(sequence),
                captured_at_s=float(captured_at_s),
                published_at_s=time.monotonic(),
                metadata=dict(metadata or {}),
            )
        )

    def _publish(self, frame: PublishedJpeg) -> None:
        if frame.side not in ("left", "right") or frame.view not in ("raw", "overlay"):
            raise ValueError("published frame side/view is invalid")
        with self._frame_lock:
            self._latest[(frame.side, frame.view)] = frame

    def latest_frame(self, side: str, view: str) -> PublishedJpeg | None:
        with self._frame_lock:
            published = self._latest.get((side, view))
        if published is not None:
            return published
        if view != "raw":
            return None
        frame = self.capture.latest_frame(side)
        if frame is None:
            return None
        return PublishedJpeg(
            side=side,
            view="raw",
            data=bytes(frame.data),
            sequence=int(frame.sequence),
            captured_at_s=float(frame.captured_at_s),
            published_at_s=float(frame.processed_at_s),
        )

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
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="alternating-gateway",
            daemon=True,
        )
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
            status = self._combined_status()
            cameras = [self._side_status(side, status) for side in ("left", "right")]
            payload = cameras if parsed.path.endswith("cameras") else {**status, "cameras": cameras}
            self._json(handler, HTTPStatus.OK, payload)
            return
        view = query.get("view", ["raw"])[0]
        if view not in ("raw", "overlay"):
            self._json(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid_view"})
            return
        if parsed.path == "/api/v1/alternating/snapshot.jpg":
            self._alternating_snapshot(handler, view)
            return
        if parsed.path == "/api/v1/alternating/mjpeg":
            self._alternating_mjpeg(handler, view)
            return
        for side in ("left", "right"):
            base = f"/api/v1/camera/{side}"
            if parsed.path == f"{base}/status":
                self._json(handler, HTTPStatus.OK, self._side_status(side, self._combined_status()))
                return
            if parsed.path == f"{base}/snapshot.jpg":
                self._snapshot(handler, side, view)
                return
            if parsed.path == f"{base}/mjpeg":
                self._mjpeg(handler, side, view)
                return
        if parsed.path == "/":
            default_view = (
                "overlay"
                if all(self.latest_frame(side, "overlay") is not None for side in ("left", "right"))
                else "raw"
            )
            page = self._debug_page(query.get("token", [""])[0], default_view).encode("utf-8")
            handler.send_response(HTTPStatus.OK)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.send_header("Content-Length", str(len(page)))
            handler.end_headers()
            handler.wfile.write(page)
            return
        self._json(handler, HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def _combined_status(self) -> dict[str, object]:
        status = dict(self.capture.status())
        runtime = self.status_provider() if self.status_provider is not None else {}
        if runtime:
            status.update({key: value for key, value in runtime.items() if key != "sides"})
            status["runtime_sides"] = runtime.get("sides", {})
        status["gateway_clients"] = self.gateway_clients
        return status

    def _authorized(self, handler: BaseHTTPRequestHandler, query: dict[str, list[str]]) -> bool:
        if not self.access_token:
            return True
        supplied = query.get("token", [""])[0]
        if not supplied:
            auth = handler.headers.get("Authorization", "")
            supplied = auth[7:] if auth.startswith("Bearer ") else ""
        return hmac.compare_digest(supplied, self.access_token)

    def _side_status(self, side: str, status: dict[str, object]) -> dict[str, object]:
        runtime_sides = status.get("runtime_sides", {})
        runtime = dict(runtime_sides.get(side, {})) if isinstance(runtime_sides, dict) else {}
        raw = self.latest_frame(side, "raw")
        overlay = self.latest_frame(side, "overlay")
        newest = overlay or raw
        capture_age = status.get(f"{side}_last_frame_age_ms")
        age = (
            capture_age
            if isinstance(capture_age, (int, float))
            else round(max(0.0, time.monotonic() - newest.captured_at_s) * 1000.0, 3)
            if newest is not None
            else None
        )
        online = bool(status.get(f"{side}_online")) and newest is not None
        active = status.get("active_camera") == side
        if not online:
            frame_state = "offline"
        elif active and isinstance(age, (int, float)) and age <= 750.0:
            frame_state = "live"
        else:
            frame_state = "cached"
        metadata = newest.metadata if newest is not None else {}
        return {
            "side": side,
            "online": online,
            "active": active,
            "frame_state": frame_state,
            "device": runtime.get("device", ""),
            "requested_width": runtime.get("requested_width"),
            "requested_height": runtime.get("requested_height"),
            "actual_width": runtime.get("actual_width"),
            "actual_height": runtime.get("actual_height"),
            "requested_fps": runtime.get("requested_fps"),
            "actual_fps": runtime.get("actual_fps"),
            "capture_fps": status.get(f"{side}_effective_fps", 0.0),
            "effective_fps": status.get(f"{side}_effective_fps", 0.0),
            "inference_fps": runtime.get("inference_fps", 0.0),
            "inference_ms": runtime.get("inference_ms", 0.0),
            "tracking_ms": runtime.get("tracking_ms", 0.0),
            "risk_ms": runtime.get("risk_ms", 0.0),
            "overlay_ms": runtime.get("overlay_ms", 0.0),
            "jpeg_encode_ms": runtime.get("jpeg_encode_ms", 0.0),
            "last_frame_age_ms": age,
            "end_to_end_observation_gap_ms": runtime.get("end_to_end_observation_gap_ms"),
            "risk_level": metadata.get("risk_level", runtime.get("risk_level", 0)),
            "risk_name": metadata.get("risk_name", runtime.get("risk_name", "SAFE")),
            "track_id": metadata.get("track_id", runtime.get("track_id")),
            "class": metadata.get("class", runtime.get("class", "")),
            "distance_m": metadata.get("distance_m", runtime.get("distance_m")),
            "backend": status.get("model_backend", status.get("backend", "")),
            "model": status.get("model", ""),
            "slice_id": metadata.get("slice_id", runtime.get("slice_id")),
            "switch_count": status.get("switch_count", 0),
            "jpeg_quality": status.get("jpeg_quality"),
            "raw_available": raw is not None,
            "overlay_available": overlay is not None,
            "last_error": status.get(f"{side}_last_error", ""),
        }

    def _snapshot(self, handler: BaseHTTPRequestHandler, side: str, view: str) -> None:
        frame = self.latest_frame(side, view)
        if frame is None:
            self._json(
                handler,
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": f"{view}_unavailable", "side": side},
            )
            return
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", "image/jpeg")
        handler.send_header("Content-Length", str(len(frame.data)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Frame-View", view)
        handler.send_header(
            "X-Frame-Age-Ms",
            f"{max(0.0, time.monotonic() - frame.captured_at_s) * 1000.0:.1f}",
        )
        handler.end_headers()
        handler.wfile.write(frame.data)

    def _alternating_snapshot(self, handler: BaseHTTPRequestHandler, view: str) -> None:
        frame = self._newest_frame(view)
        if frame is None:
            self._json(handler, HTTPStatus.SERVICE_UNAVAILABLE, {"error": f"{view}_unavailable"})
            return
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", "image/jpeg")
        handler.send_header("Content-Length", str(len(frame.data)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Frame-View", view)
        handler.send_header("X-Frame-Side", frame.side)
        handler.send_header(
            "X-Frame-Age-Ms",
            f"{max(0.0, time.monotonic() - frame.captured_at_s) * 1000.0:.1f}",
        )
        handler.end_headers()
        handler.wfile.write(frame.data)

    def _newest_frame(self, view: str) -> PublishedJpeg | None:
        frames = [self.latest_frame(side, view) for side in ("left", "right")]
        available = [frame for frame in frames if frame is not None]
        if not available:
            return None
        return max(available, key=lambda frame: (frame.captured_at_s, frame.published_at_s))

    def _mjpeg(self, handler: BaseHTTPRequestHandler, side: str, view: str) -> None:
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        interval_s = 1.0 / self.stream_fps_limit
        last_frame_id: tuple[int, float, float] | None = None
        with self._client_lock:
            self.gateway_clients += 1
        try:
            while True:
                frame = self.latest_frame(side, view)
                frame_id = (
                    (frame.sequence, frame.captured_at_s, frame.published_at_s)
                    if frame is not None
                    else None
                )
                if frame is None or frame_id == last_frame_id:
                    time.sleep(min(interval_s, 0.1))
                    continue
                last_frame_id = frame_id
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

    def _alternating_mjpeg(self, handler: BaseHTTPRequestHandler, view: str) -> None:
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        interval_s = 1.0 / self.stream_fps_limit
        last_frame_id: tuple[str, int, float, float] | None = None
        with self._client_lock:
            self.gateway_clients += 1
        try:
            while True:
                frame = self._newest_frame(view)
                frame_id = (
                    (frame.side, frame.sequence, frame.captured_at_s, frame.published_at_s)
                    if frame is not None
                    else None
                )
                if frame is None or frame_id == last_frame_id:
                    time.sleep(min(interval_s, 0.02))
                    continue
                last_frame_id = frame_id
                handler.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                handler.wfile.write(f"Content-Length: {len(frame.data)}\r\n".encode("ascii"))
                handler.wfile.write(f"X-Frame-Side: {frame.side}\r\n\r\n".encode("ascii"))
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
    def _debug_page(token: str, default_view: str = "raw") -> str:
        if default_view not in ("raw", "overlay"):
            raise ValueError("default debug view must be raw or overlay")
        token_query = f"&token={quote_plus(token)}" if token else ""
        status_query = f"?token={quote_plus(token)}" if token else ""
        overlay_ready = default_view == "overlay"
        toggle_label = "切换为原始画面" if overlay_ready else "检测画面不可用"
        toggle_disabled = "" if overlay_ready else " disabled"
        return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SS928 交替双摄</title>
<style>body{{font-family:system-ui,sans-serif;margin:0;background:#101214;color:#eee}}header{{padding:12px 18px;background:#191d20;display:flex;gap:14px;align-items:center;flex-wrap:wrap}}button{{padding:7px 12px}}.live{{margin:12px;border:1px solid #444;background:#171a1d;padding:8px}}.live img{{max-height:68vh}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:0 12px 12px}}section{{border:1px solid #444;background:#171a1d;padding:8px}}img{{width:100%;aspect-ratio:4/3;object-fit:contain;background:#000}}pre{{white-space:pre-wrap;font-size:12px;min-height:12em}}@media(max-width:800px){{.grid{{grid-template-columns:1fr}}}}</style></head>
<body><header><strong>SS928 交替双摄</strong><button id="toggle"{toggle_disabled}>{toggle_label}</button><span id="global">读取状态中</span></header>
<section class="live"><h2>低延迟交替画面</h2><img id="alternating-img"><div id="active-note">等待摄像头</div></section><div class="grid">
<section><h2>左侧</h2><img id="left-img"><pre id="left"></pre></section>
<section><h2>右侧</h2><img id="right-img"><pre id="right"></pre></section></div>
<script>let view='{default_view}',overlayReady={str(overlay_ready).lower()};const token='{token_query}',reconnectTimers={{}},toggle=document.getElementById('toggle');
function connectStream(s){{document.getElementById(s+'-img').src=`/api/v1/camera/${{s}}/mjpeg?view=${{view}}${{token}}&t=${{Date.now()}}`;}}
function connectAlternating(){{document.getElementById('alternating-img').src=`/api/v1/alternating/mjpeg?view=${{view}}${{token}}&t=${{Date.now()}}`;}}
function setStreams(){{connectAlternating();for(const s of ['left','right'])connectStream(s);}}
function updateToggle(){{toggle.disabled=!overlayReady&&view==='raw';toggle.textContent=view==='overlay'?'切换为原始画面':overlayReady?'切换为检测画面':'检测画面不可用';}}
for(const s of ['left','right'])document.getElementById(s+'-img').onerror=()=>{{clearTimeout(reconnectTimers[s]);reconnectTimers[s]=setTimeout(()=>connectStream(s),1000);}};
document.getElementById('alternating-img').onerror=()=>{{clearTimeout(reconnectTimers.alternating);reconnectTimers.alternating=setTimeout(connectAlternating,1000);}};
toggle.onclick=()=>{{if(view==='raw'&&!overlayReady)return;view=view==='overlay'?'raw':'overlay';updateToggle();setStreams();}};
async function poll(){{try{{const r=await fetch('/api/v1/status{status_query}');const v=await r.json();overlayReady=v.cameras.length===2&&v.cameras.every(c=>c.overlay_available);if(view==='overlay'&&!overlayReady){{view='raw';setStreams();}}updateToggle();document.getElementById('global').textContent=`当前采集: ${{v.active_camera||'切换中'}} | 切换: ${{v.switch_count||0}} | E2E max: ${{v.end_to_end_max_gap_ms??'-'}} ms | CPU: ${{v.cpu_percent??'-'}}% | RSS: ${{v.process_rss_mb??'-'}} MiB`;document.getElementById('active-note').textContent=`当前来源: ${{v.active_camera||'切换中'}}；下方非活动侧显示最近缓存帧`;for(const c of v.cameras)document.getElementById(c.side).textContent=JSON.stringify(c,null,2);}}catch(e){{document.getElementById('global').textContent=String(e);}}setTimeout(poll,1000);}}setStreams();poll();</script></body></html>"""

    def __enter__(self) -> "AlternatingCameraGateway":
        self.start()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.stop()
