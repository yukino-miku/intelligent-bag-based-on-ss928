#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


for candidate in (
    Path(__file__).resolve().parents[1] / "board_runtime" / "common",
    Path(__file__).resolve().parent.parent / "common",
):
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from runtime_metrics import ResourceSampler


class DaemonThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False


class DualCameraGateway:
    def __init__(
        self,
        bind: str,
        port: int,
        left_url: str,
        right_url: str,
        access_token: str = "",
        controller_status_file: str = "/run/smartbag/controller-status.json",
    ) -> None:
        self.bind = bind
        self.port = int(port)
        self.urls = {"left": left_url.rstrip("/"), "right": right_url.rstrip("/")}
        self.access_token = access_token
        self.controller_status_file = Path(controller_status_file)
        self.resource_sampler = ResourceSampler()
        self.httpd: ThreadingHTTPServer | None = None

    def serve_forever(self) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802
                owner.handle_get(self)

            def log_message(self, fmt: str, *args: object) -> None:
                print(f"[video-gateway] {fmt % args}", file=sys.stderr, flush=True)

        self.httpd = DaemonThreadingHTTPServer((self.bind, self.port), Handler)
        self.port = int(self.httpd.server_address[1])
        print(f"[video-gateway] listening on {self.bind}:{self.port}", file=sys.stderr, flush=True)
        self.httpd.serve_forever()

    def handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        query = parse_qs(parsed.query)
        if not self._authorized(handler, query):
            self._send_json(handler, HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        if parsed.path == "/":
            self._send_bytes(
                handler,
                HTTPStatus.OK,
                "text/html; charset=utf-8",
                self._debug_page(query.get("token", [""])[0]).encode("utf-8"),
            )
            return
        if parsed.path == "/api/v1/status":
            cameras = [self._camera_status(side) for side in ("left", "right")]
            self._send_json(
                handler,
                HTTPStatus.OK,
                {
                    "cameras": cameras,
                    "resources": self.resource_sampler.sample(),
                    "controller": self._controller_status(),
                    "video_transport": "http_snapshot_mjpeg",
                    "ble_carries_video": False,
                },
            )
            return
        if parsed.path == "/api/v1/cameras":
            self._send_json(handler, HTTPStatus.OK, [self._camera_status(side) for side in ("left", "right")])
            return
        for side in ("left", "right"):
            base = f"/api/v1/camera/{side}"
            if parsed.path == f"{base}/status":
                self._send_json(handler, HTTPStatus.OK, self._camera_status(side))
                return
            if parsed.path in (f"{base}/snapshot.jpg", f"{base}/mjpeg"):
                self._proxy(handler, side, parsed.path, query)
                return
        self._send_json(handler, HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def _camera_status(self, side: str) -> dict[str, object]:
        path = f"/api/v1/camera/{side}/status"
        try:
            payload = self._fetch_json(self.urls[side] + path)
            if isinstance(payload, dict):
                return payload
        except (OSError, ValueError, HTTPError, URLError) as exc:
            return {"side": side, "online": False, "error": str(exc)}
        return {"side": side, "online": False, "error": "invalid status response"}

    def _controller_status(self) -> dict[str, object]:
        try:
            data = json.loads(self.controller_status_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _fetch_json(self, url: str) -> object:
        request = Request(url, headers={"Accept": "application/json"})
        with urlopen(request, timeout=0.8) as response:
            return json.loads(response.read().decode("utf-8"))

    def _proxy(self, handler: BaseHTTPRequestHandler, side: str, path: str, query: dict[str, list[str]]) -> None:
        forwarded = {key: values[-1] for key, values in query.items() if key != "token" and values}
        url = self.urls[side] + path
        if forwarded:
            url += "?" + urlencode(forwarded)
        headers_sent = False
        try:
            with urlopen(Request(url), timeout=5.0) as response:
                handler.send_response(response.status)
                content_type = response.headers.get("Content-Type", "application/octet-stream")
                handler.send_header("Content-Type", content_type)
                handler.send_header("Cache-Control", "no-store")
                content_length = response.headers.get("Content-Length")
                if content_length:
                    handler.send_header("Content-Length", content_length)
                handler.end_headers()
                headers_sent = True
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    handler.wfile.write(chunk)
                    handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        except (HTTPError, URLError, OSError) as exc:
            if not headers_sent and not handler.wfile.closed:
                self._send_json(handler, HTTPStatus.SERVICE_UNAVAILABLE, {"side": side, "online": False, "error": str(exc)})

    def _authorized(self, handler: BaseHTTPRequestHandler, query: dict[str, list[str]]) -> bool:
        if not self.access_token:
            return True
        return (
            query.get("token", [""])[0] == self.access_token
            or handler.headers.get("Authorization", "") == f"Bearer {self.access_token}"
        )

    @staticmethod
    def _send_json(handler: BaseHTTPRequestHandler, status: HTTPStatus, payload: object) -> None:
        DualCameraGateway._send_bytes(
            handler,
            status,
            "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
        )

    @staticmethod
    def _send_bytes(handler: BaseHTTPRequestHandler, status: HTTPStatus, content_type: str, body: bytes) -> None:
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)

    @staticmethod
    def _debug_page(token: str = "") -> str:
        token_query = urlencode({"token": token}) if token else ""
        stream_suffix = "&" + token_query if token_query else ""
        status_suffix = "?" + token_query if token_query else ""
        page = """<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\"><title>SS928 SmartBag 双摄</title>
<style>body{font-family:sans-serif;margin:20px;background:#f4f6f8;color:#16202a}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}.cam{background:#fff;padding:12px;border:1px solid #ccd3da}.cam img{width:100%;aspect-ratio:16/9;object-fit:contain;background:#111}pre{white-space:pre-wrap;font-size:12px}</style></head>
<body><h1>SS928 SmartBag 双路调试</h1><div class=\"grid\"><section class=\"cam\"><h2>左后</h2><img src=\"/api/v1/camera/left/mjpeg?view=overlay__STREAM_SUFFIX__\"><pre id=\"left\"></pre></section><section class=\"cam\"><h2>右后</h2><img src=\"/api/v1/camera/right/mjpeg?view=overlay__STREAM_SUFFIX__\"><pre id=\"right\"></pre></section></div>
<script>for(const s of ['left','right'])setInterval(()=>fetch(`/api/v1/camera/${s}/status__STATUS_SUFFIX__`).then(r=>r.json()).then(v=>document.getElementById(s).textContent=JSON.stringify(v,null,2)).catch(e=>document.getElementById(s).textContent=e),1000)</script></body></html>"""
        return page.replace("__STREAM_SUFFIX__", stream_suffix).replace("__STATUS_SUFFIX__", status_suffix)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate two detector-local HTTP streams without reopening cameras.")
    parser.add_argument("--config", default="", help="Shared /etc/smartbag/config.json.")
    parser.add_argument("--bind", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--left-url", default=None)
    parser.add_argument("--right-url", default=None)
    parser.add_argument("--access-token", default=None)
    parser.add_argument("--controller-status-file", default=None)
    return parser.parse_args()


def gateway_settings(args: argparse.Namespace) -> dict[str, object]:
    config: dict[str, object] = {}
    if args.config:
        loaded = json.loads(Path(args.config).read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("gateway config must be a JSON object")
        config = loaded
    gateway = config.get("stream_gateway") if isinstance(config.get("stream_gateway"), dict) else {}
    cameras = config.get("cameras") if isinstance(config.get("cameras"), dict) else {}

    def camera_url(side: str, fallback_port: int) -> str:
        camera = cameras.get(side) if isinstance(cameras.get(side), dict) else {}
        port = int(camera.get("stream_port", fallback_port))
        return f"http://127.0.0.1:{port}"

    return {
        "bind": args.bind if args.bind is not None else str(gateway.get("bind", "0.0.0.0")),
        "port": args.port if args.port is not None else int(gateway.get("port", 8080)),
        "left_url": args.left_url if args.left_url is not None else camera_url("left", 18081),
        "right_url": args.right_url if args.right_url is not None else camera_url("right", 18082),
        "access_token": args.access_token if args.access_token is not None else str(gateway.get("access_token", "")),
        "controller_status_file": (
            args.controller_status_file
            if args.controller_status_file is not None
            else str(config.get("controller_status_file", "/run/smartbag/controller-status.json"))
        ),
    }


def main() -> None:
    args = parse_args()
    settings = gateway_settings(args)
    DualCameraGateway(
        str(settings["bind"]),
        int(settings["port"]),
        str(settings["left_url"]),
        str(settings["right_url"]),
        access_token=str(settings["access_token"]),
        controller_status_file=str(settings["controller_status_file"]),
    ).serve_forever()


if __name__ == "__main__":
    main()
