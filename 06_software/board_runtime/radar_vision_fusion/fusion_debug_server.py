from __future__ import annotations

import json
import hmac
import ipaddress
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    from .fusion_runtime import RadarVisionFusionRuntime, _risk_record_dict
except ImportError:
    from fusion_runtime import RadarVisionFusionRuntime, _risk_record_dict


class FusionDebugServer:
    def __init__(
        self,
        runtime: RadarVisionFusionRuntime,
        bind: str = "127.0.0.1",
        port: int = 8080,
        access_token: str = "",
        admin_token: str = "",
        readonly_token: str = "",
    ) -> None:
        self.runtime = runtime
        self.bind = bind
        self.port = int(port)
        self.admin_token = admin_token or access_token
        self.readonly_token = readonly_token
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def bound_port(self) -> int:
        return int(self._server.server_address[1]) if self._server is not None else self.port

    def start(self) -> None:
        if not _is_loopback_bind(self.bind) and not (self.admin_token or self.readonly_token):
            raise ValueError("non-loopback fusion API bind requires an API token")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                owner._handle_get(self)

            def do_PATCH(self) -> None:
                owner._handle_patch(self)

            def do_POST(self) -> None:
                owner._handle_post(self)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer((self.bind, self.port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="fusion-debug-http", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        if not self._authorized(handler, write=False):
            self._json(handler, HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        if parsed.path == "/api/v1/fusion/status":
            self._json(handler, HTTPStatus.OK, self.runtime.status())
            return
        if parsed.path == "/api/v1/fusion/targets":
            targets = [_risk_record_dict(item, self.runtime.risk_model.config) for item in self.runtime.latest_risks()]
            self._json(handler, HTTPStatus.OK, {"targets": targets})
            return
        if parsed.path == "/api/v1/settings/runtime":
            self._json(handler, HTTPStatus.OK, self.runtime.runtime_settings())
            return
        if parsed.path == "/api/v1/alerts/history":
            query = parse_qs(parsed.query)
            try:
                response = self.runtime.alert_history.history(
                    offset=int(query.get("offset", [0])[0]),
                    limit=int(query.get("limit", [50])[0]),
                    min_level=int(query.get("min_level", [3])[0]),
                    since=float(query["since"][0]) if "since" in query else None,
                )
            except ValueError as exc:
                self._json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._json(handler, HTTPStatus.OK, response)
            return
        alert_parts = parsed.path.strip("/").split("/")
        if len(alert_parts) in {4, 5} and alert_parts[:3] == ["api", "v1", "alerts"]:
            event_id = alert_parts[3]
            if len(alert_parts) == 5 and alert_parts[4] == "image.jpg":
                image_path = self.runtime.alert_history.image_path(event_id)
                if image_path is None:
                    self._json(handler, HTTPStatus.NOT_FOUND, {"error": "alert image not found"})
                    return
                self._file(handler, image_path, "image/jpeg")
                return
            event = self.runtime.alert_history.get(event_id)
            self._json(
                handler,
                HTTPStatus.OK if event is not None else HTTPStatus.NOT_FOUND,
                event if event is not None else {"error": "alert not found"},
            )
            return
        for side in ("left", "right"):
            if parsed.path == f"/api/v1/fusion/{side}/snapshot.jpg":
                image = self._snapshot(side)
                if image is None:
                    self._json(handler, HTTPStatus.SERVICE_UNAVAILABLE, {"error": f"{side} snapshot unavailable"})
                    return
                self._bytes(handler, HTTPStatus.OK, image, "image/jpeg")
                return
        self._json(handler, HTTPStatus.NOT_FOUND, {"error": "not found"})

    def _handle_patch(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        if not self._authorized(handler, write=True):
            self._json(handler, HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        if parsed.path != "/api/v1/settings/runtime":
            self._json(handler, HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            payload = self._read_json(handler)
            result = self.runtime.patch_runtime_settings(payload)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            self._json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._json(handler, HTTPStatus.OK, result)

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        if not self._authorized(handler, write=True):
            self._json(handler, HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        if parsed.path != "/api/v1/settings/runtime/reset":
            self._json(handler, HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            result = self.runtime.reset_runtime_settings()
        except OSError as exc:
            self._json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._json(handler, HTTPStatus.OK, result)

    def _authorized(self, handler: BaseHTTPRequestHandler, *, write: bool) -> bool:
        token = handler.headers.get("X-SmartBag-Token", "")
        authorization = handler.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            token = authorization[7:]
        if write:
            return bool(self.admin_token) and hmac.compare_digest(token, self.admin_token)
        if not self.admin_token and not self.readonly_token and _is_loopback_bind(self.bind):
            return True
        return any(
            expected and hmac.compare_digest(token, expected)
            for expected in (self.admin_token, self.readonly_token)
        )

    def _snapshot(self, side: str) -> bytes | None:
        import cv2

        frame = self.runtime.latest_frame(side)
        if frame is None or frame.image is None:
            return None
        image = frame.image.copy()
        association = self.runtime.latest_association(side)
        matches = {item.detection_id: item for item in association.matches} if association is not None else {}
        risks = {item.fused.track_key: item for item in self.runtime.latest_risks() if item.fused.side == side}
        if association is not None:
            matched_keys = {item.track_key for item in association.matches}
            ambiguous_keys = set(association.ambiguous_track_keys)
            for projection in association.projections:
                if projection.projected_u_px is None or not projection.projected_in_frame:
                    continue
                projected_u = int(round(projection.projected_u_px))
                half_width = self.runtime.association.config.projection_half_width_px + (
                    frame.image_width * self.runtime.association.config.projection_half_width_ratio
                )
                region_left = max(0, int(round(projection.projected_u_px - half_width)))
                region_right = min(frame.image_width - 1, int(round(projection.projected_u_px + half_width)))
                if projection.track_key in ambiguous_keys:
                    color, state = (0, 165, 255), "AMBIGUOUS"
                elif projection.track_key in matched_keys:
                    color, state = (255, 120, 0), "MATCHED"
                else:
                    color, state = (0, 80, 255), "UNKNOWN"
                cv2.rectangle(image, (region_left, 8), (region_right, 34), color, 1)
                cv2.line(image, (projected_u, 0), (projected_u, image.shape[0] - 1), color, 1)
                record = risks.get(projection.track_key)
                radar_id = record.fused.radar_target_id if record is not None else projection.track_key
                cv2.putText(
                    image,
                    f"R{radar_id} {state}",
                    (region_left, 29),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.38,
                    color,
                    1,
                    cv2.LINE_AA,
                )
        for detection in frame.detections:
            match = matches.get(detection.detection_id)
            color = (0, 180, 0) if match is not None else (0, 180, 255)
            x1, y1, x2, y2 = (int(round(value)) for value in detection.bbox_xyxy)
            margin = int(round((x2 - x1) * self.runtime.association.config.bbox_expand_ratio))
            cv2.rectangle(image, (max(0, x1 - margin), y1), (min(frame.image_width - 1, x2 + margin), y2), (180, 120, 0), 1)
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
            label = f"{detection.class_name} {detection.confidence:.2f} UNKNOWN"
            record = None
            if match is not None:
                record = risks.get(match.track_key)
                label = f"{detection.class_name} {detection.confidence:.2f} R{match.track_key} cost={match.association_score:.2f}"
                overlap_left = max(match.radar_region[0], match.detection_region[0])
                overlap_right = min(match.radar_region[1], match.detection_region[1])
                cv2.line(image, (int(overlap_left), 40), (int(overlap_right), 40), (255, 0, 255), 3)
            cv2.putText(image, label, (x1, max(50, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)
            if match is not None and record is not None:
                ttc = "--" if record.stable.ttc_s is None else f"{record.stable.ttc_s:.1f}s"
                median = record.window.score_median if record.window is not None else record.stable.score
                details = (
                    f"R{record.fused.radar_target_id} d={record.fused.distance_m:.1f}m "
                    f"v={record.fused.speed_mps:.1f} TTC={ttc} med={median:.2f} L{int(record.stable.haptic_level)}"
                )
                cv2.putText(image, details, (x1, min(image.shape[0] - 6, y2 + 16)), cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1, cv2.LINE_AA)
        age_s = max(0.0, time.monotonic() - frame.captured_mono_s)
        state = "LIVE" if age_s <= 1.0 and frame.camera_state == "LIVE" else "CACHED"
        if frame.camera_state in {"OFFLINE", "MODEL_ERROR", "SWITCH_TIMEOUT"}:
            state = frame.camera_state
        cv2.putText(image, f"{side.upper()} {state} age={age_s:.2f}s", (10, image.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2, cv2.LINE_AA)
        ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        return encoded.tobytes() if ok else None

    @staticmethod
    def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, object]:
        length = int(handler.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1024 * 1024:
            raise ValueError("request body must be a JSON object under 1 MiB")
        payload = json.loads(handler.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    @staticmethod
    def _json(handler: BaseHTTPRequestHandler, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        FusionDebugServer._bytes(handler, status, body, "application/json; charset=utf-8")

    @staticmethod
    def _file(handler: BaseHTTPRequestHandler, path: Path, content_type: str) -> None:
        FusionDebugServer._bytes(handler, HTTPStatus.OK, path.read_bytes(), content_type)

    @staticmethod
    def _bytes(handler: BaseHTTPRequestHandler, status: HTTPStatus, body: bytes, content_type: str) -> None:
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)


def _is_loopback_bind(bind: str) -> bool:
    if bind.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(bind).is_loopback
    except ValueError:
        return False
