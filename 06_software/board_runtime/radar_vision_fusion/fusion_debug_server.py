from __future__ import annotations

import json
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

try:
    from .fusion_runtime import RadarVisionFusionRuntime, _risk_record_dict
except ImportError:
    from fusion_runtime import RadarVisionFusionRuntime, _risk_record_dict


class FusionDebugServer:
    def __init__(
        self,
        runtime: RadarVisionFusionRuntime,
        bind: str = "0.0.0.0",
        port: int = 8080,
        access_token: str = "",
    ) -> None:
        self.runtime = runtime
        self.bind = bind
        self.port = int(port)
        self.access_token = access_token
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                owner._handle(self)

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
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        if self.access_token and parse_qs(parsed.query).get("token", [""])[0] != self.access_token:
            self._json(handler, HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        if parsed.path == "/api/v1/fusion/status":
            self._json(handler, HTTPStatus.OK, self.runtime.status())
            return
        if parsed.path == "/api/v1/fusion/targets":
            targets = [
                _risk_record_dict(item, self.runtime.risk_model.config)
                for item in self.runtime.latest_risks()
            ]
            self._json(handler, HTTPStatus.OK, {"targets": targets})
            return
        for side in ("left", "right"):
            if parsed.path == f"/api/v1/fusion/{side}/snapshot.jpg":
                image = self._snapshot(side)
                if image is None:
                    self._json(handler, HTTPStatus.SERVICE_UNAVAILABLE, {"error": f"{side} snapshot unavailable"})
                    return
                handler.send_response(HTTPStatus.OK)
                handler.send_header("Content-Type", "image/jpeg")
                handler.send_header("Cache-Control", "no-store")
                handler.send_header("Content-Length", str(len(image)))
                handler.end_headers()
                handler.wfile.write(image)
                return
        self._json(handler, HTTPStatus.NOT_FOUND, {"error": "not found"})

    def _snapshot(self, side: str) -> bytes | None:
        import cv2

        frame = self.runtime.latest_frame(side)
        if frame is None or frame.image is None:
            return None
        image = frame.image.copy()
        association = self.runtime.latest_association(side)
        matches = {item.detection_id: item for item in association.matches} if association is not None else {}
        risks = {
            item.fused.track_key: item
            for item in self.runtime.latest_risks()
            if item.fused.side == side
        }
        if association is not None:
            matched_keys = {item.track_key for item in association.matches}
            for projection in association.projections:
                if projection.projected_u_px is None or not projection.projected_in_frame:
                    continue
                projected_u = int(round(projection.projected_u_px))
                color = (255, 120, 0) if projection.track_key in matched_keys else (0, 80, 255)
                cv2.line(image, (projected_u, 0), (projected_u, image.shape[0] - 1), color, 1)
                record = risks.get(projection.track_key)
                radar_id = record.fused.radar_target_id if record is not None else projection.track_key
                cv2.putText(
                    image,
                    f"R{radar_id}",
                    (max(0, projected_u - 14), 42),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.42,
                    color,
                    1,
                    cv2.LINE_AA,
                )
        for detection in frame.detections:
            match = matches.get(detection.detection_id)
            color = (0, 180, 0) if match is not None else (0, 180, 255)
            x1, y1, x2, y2 = (int(round(value)) for value in detection.bbox_xyxy)
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
            label = f"{detection.class_name} {detection.confidence:.2f} UNBOUND"
            if match is not None:
                record = risks.get(match.track_key)
                binding_state = record.fused.association_state if record is not None else "BOUND"
                label = f"{detection.class_name} {detection.confidence:.2f} {binding_state} cost={match.association_score:.2f}"
                projected_u = int(round(match.projected_u_px))
                cv2.line(image, (projected_u, image.shape[0] // 2), (int(detection.bbox_center_x), int(detection.bbox_center_y)), (255, 80, 0), 1)
            cv2.putText(image, label, (x1, max(18, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)
            if match is not None and record is not None:
                ttc = "--" if record.stable.ttc_s is None else f"{record.stable.ttc_s:.1f}s"
                details = (
                    f"R{record.fused.radar_target_id} x/z={record.fused.x_m:.1f}/{record.fused.z_m:.1f} "
                    f"v={record.fused.vx_mps:.1f}/{record.fused.vz_mps:.1f} TTC={ttc} "
                    f"L{int(record.stable.haptic_level)}"
                )
                cv2.putText(image, details, (x1, min(image.shape[0] - 6, y2 + 16)), cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1, cv2.LINE_AA)
        age_s = max(0.0, time.monotonic() - frame.captured_mono_s)
        state = "LIVE" if age_s <= 1.0 and frame.camera_state == "LIVE" else "CACHED"
        if frame.camera_state in {"OFFLINE", "MODEL_ERROR", "SWITCH_TIMEOUT"}:
            state = frame.camera_state
        cv2.putText(image, f"{side.upper()} {state} age={age_s:.2f}s", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2, cv2.LINE_AA)
        ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        return encoded.tobytes() if ok else None

    @staticmethod
    def _json(handler: BaseHTTPRequestHandler, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
