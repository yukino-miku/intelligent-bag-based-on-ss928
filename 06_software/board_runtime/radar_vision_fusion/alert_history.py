from __future__ import annotations

import json
import threading
import time
import uuid
import os
from pathlib import Path
from typing import Callable, Mapping

try:
    from .models import ClassificationFrame
except ImportError:
    from models import ClassificationFrame


class AlertHistoryStore:
    """Persist deduplicated level-3/4 events and same-side snapshot images."""

    def __init__(
        self,
        root: str | Path = "/var/lib/smartbag/alarm-events",
        *,
        max_snapshot_age_s: float = 2.0,
        snapshot_provider: Callable[..., ClassificationFrame | None] | None = None,
        max_events: int = 500,
        max_images: int = 200,
        max_storage_mb: float = 256.0,
        retention_days: float = 30.0,
    ) -> None:
        self.root = Path(root)
        self.events_path = self.root / "events.jsonl"
        self.images_dir = self.root / "images"
        self.max_snapshot_age_s = max(0.0, float(max_snapshot_age_s))
        self.snapshot_provider = snapshot_provider
        self.max_events = max(1, int(max_events))
        self.max_images = max(0, int(max_images))
        self.max_storage_bytes = max(1, int(float(max_storage_mb) * 1024 * 1024))
        self.retention_days = max(0.0, float(retention_days))
        self._lock = threading.RLock()
        self._events: dict[str, dict[str, object]] = {}
        self._order: list[str] = []
        self._active_by_side: dict[str, str] = {}
        self._load()

    def apply(
        self,
        side: str,
        level: int,
        payload: Mapping[str, object],
        *,
        now_mono_s: float | None = None,
        now_epoch_s: float | None = None,
    ) -> dict[str, object] | None:
        now_mono_s = time.monotonic() if now_mono_s is None else float(now_mono_s)
        now_epoch_s = time.time() if now_epoch_s is None else float(now_epoch_s)
        level = max(0, min(4, int(level)))
        side = str(side)
        with self._lock:
            active_id = self._active_by_side.get(side)
            active = self._events.get(active_id or "")
            if level < 3:
                self._active_by_side.pop(side, None)
                return None

            track_key = str(payload.get("radar_track_key", ""))
            create = (
                active is None
                or int(active.get("level", 0)) < 3
                or level > int(active.get("level", 0))
                or track_key != str(active.get("radar_track_key", ""))
            )
            if create:
                event_id = _event_id(side, now_epoch_s)
                event = {
                    "event_id": event_id,
                    "start_time": now_epoch_s,
                    "last_seen_time": now_epoch_s,
                    "side": side,
                    "level": level,
                    **dict(payload),
                }
                event["peak_score"] = float(payload.get("effective_score", payload.get("score", 0.0)) or 0.0)
                self._attach_snapshot(event, now_mono_s)
                self._events[event_id] = event
                self._order.append(event_id)
                self._active_by_side[side] = event_id
                self._append({"operation": "create", **event})
                self._enforce_retention(now_epoch_s)
                return dict(event)

            assert active is not None
            active["last_seen_time"] = now_epoch_s
            active["level"] = max(level, int(active.get("level", 0)))
            score = float(payload.get("effective_score", payload.get("score", 0.0)) or 0.0)
            active["peak_score"] = max(score, float(active.get("peak_score", 0.0)))
            for key, value in payload.items():
                if key not in {"event_id", "start_time", "image_path", "image_status"}:
                    active[key] = value
            self._append(
                {
                    "operation": "update",
                    "event_id": active["event_id"],
                    "last_seen_time": now_epoch_s,
                    "level": active["level"],
                    "peak_score": active["peak_score"],
                }
            )
            return dict(active)

    def history(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        min_level: int = 3,
        since: float | None = None,
    ) -> dict[str, object]:
        with self._lock:
            items = [dict(self._events[event_id]) for event_id in reversed(self._order)]
        items = [
            item for item in items
            if int(item.get("level", 0)) >= min_level
            and (since is None or float(item.get("start_time", 0.0)) >= since)
        ]
        offset = max(0, int(offset))
        limit = max(1, min(200, int(limit)))
        return {"total": len(items), "offset": offset, "limit": limit, "events": items[offset:offset + limit]}

    def get(self, event_id: str) -> dict[str, object] | None:
        with self._lock:
            event = self._events.get(str(event_id))
            return dict(event) if event is not None else None

    def image_path(self, event_id: str) -> Path | None:
        event = self.get(event_id)
        if event is None or event.get("image_status") not in {"saved", "frame_mismatch"}:
            return None
        path = Path(str(event.get("image_path", "")))
        return path if path.is_file() and path.parent.resolve() == self.images_dir.resolve() else None

    def recent(self, limit: int = 5) -> list[dict[str, object]]:
        return list(self.history(limit=limit)["events"])  # type: ignore[arg-type]

    def storage_status(self) -> dict[str, object]:
        with self._lock:
            images = [
                event for event in self._events.values()
                if event.get("image_status") in {"saved", "frame_mismatch"}
            ]
            return {
                "event_count": len(self._events),
                "image_count": len(images),
                "storage_bytes": self._storage_bytes(),
                "max_events": self.max_events,
                "max_images": self.max_images,
                "max_storage_bytes": self.max_storage_bytes,
                "retention_days": self.retention_days,
            }

    def _attach_snapshot(self, event: dict[str, object], now_mono_s: float) -> None:
        requested_frame_id = event.get("visual_frame_id")
        requested_frame_id = int(requested_frame_id) if requested_frame_id is not None else None
        frame = None
        if self.snapshot_provider is not None:
            try:
                frame = self.snapshot_provider(str(event["side"]), requested_frame_id)
            except TypeError:
                frame = self.snapshot_provider(str(event["side"]))
        if frame is None or frame.image is None:
            event.update({
                "image_path": "",
                "image_age_s": None,
                "image_status": "unavailable",
                "image_frame_id": None,
                "image_frame_timestamp": None,
                "association_relinked": False,
            })
            return
        age_s = max(0.0, now_mono_s - frame.captured_mono_s)
        exact_frame = requested_frame_id is None or frame.frame_id == requested_frame_id
        event.update({
            "image_age_s": age_s,
            "image_frame_id": frame.frame_id,
            "image_frame_timestamp": frame.captured_mono_s,
            "association_relinked": False,
        })
        if age_s > self.max_snapshot_age_s:
            event.update({"image_path": "", "image_status": "stale"})
            return
        try:
            path = self.images_dir / f"{event['event_id']}.jpg"
            self.images_dir.mkdir(parents=True, exist_ok=True)
            _write_overlay(path, frame, event, allow_selection=exact_frame)
            event.update({
                "image_path": str(path),
                "image_status": "saved" if exact_frame else "frame_mismatch",
            })
        except Exception as exc:
            event.update({"image_path": "", "image_status": "error", "image_error": str(exc)})

    def _append(self, payload: Mapping[str, object]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")

    def _enforce_retention(self, now_epoch_s: float) -> None:
        changed = False
        active = set(self._active_by_side.values())
        cutoff = now_epoch_s - self.retention_days * 86400.0
        for event_id in list(self._order):
            event = self._events[event_id]
            if event_id not in active and self.retention_days > 0.0 and float(event.get("start_time", 0.0)) < cutoff:
                self._remove_event(event_id)
                changed = True

        while len(self._events) > self.max_events:
            removable = next((event_id for event_id in self._order if event_id not in active), None)
            if removable is None:
                break
            self._remove_event(removable)
            changed = True

        def saved_in_order() -> list[str]:
            return [
                event_id for event_id in self._order
                if event_id not in active
                and self._events[event_id].get("image_status") in {"saved", "frame_mismatch"}
            ]

        while sum(
            event.get("image_status") in {"saved", "frame_mismatch"}
            for event in self._events.values()
        ) > self.max_images:
            candidates = saved_in_order()
            if not candidates:
                break
            self._prune_image(candidates[0], "image_count_limit")
            changed = True

        while self._storage_bytes() > self.max_storage_bytes:
            candidates = saved_in_order()
            if candidates:
                self._prune_image(candidates[0], "storage_limit")
                changed = True
                continue
            removable = next((event_id for event_id in self._order if event_id not in active), None)
            if removable is None:
                break
            self._remove_event(removable)
            changed = True
        if changed:
            self._compact()

    def _prune_image(self, event_id: str, reason: str) -> None:
        event = self._events[event_id]
        path = Path(str(event.get("image_path", "")))
        if path.is_file() and path.parent.resolve() == self.images_dir.resolve():
            path.unlink()
        event.update({"image_path": "", "image_status": "pruned", "image_prune_reason": reason})

    def _remove_event(self, event_id: str) -> None:
        event = self._events.pop(event_id, None)
        if event is None:
            return
        path = Path(str(event.get("image_path", "")))
        if path.is_file() and path.parent.resolve() == self.images_dir.resolve():
            path.unlink()
        self._order = [value for value in self._order if value != event_id]

    def _compact(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.events_path.with_suffix(".jsonl.tmp")
        with temporary.open("w", encoding="utf-8") as output:
            for event_id in self._order:
                output.write(json.dumps({"operation": "create", **self._events[event_id]}, ensure_ascii=False, separators=(",", ":")) + "\n")
        os.replace(temporary, self.events_path)

    def _storage_bytes(self) -> int:
        total = self.events_path.stat().st_size if self.events_path.is_file() else 0
        if self.images_dir.is_dir():
            total += sum(path.stat().st_size for path in self.images_dir.glob("*.jpg") if path.is_file())
        return total

    def _load(self) -> None:
        if not self.events_path.is_file():
            return
        for line in self.events_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict) or "event_id" not in item:
                continue
            event_id = str(item["event_id"])
            if item.get("operation") == "update":
                if event_id in self._events:
                    self._events[event_id].update({key: value for key, value in item.items() if key != "operation"})
                continue
            item.pop("operation", None)
            self._events[event_id] = item
            if event_id not in self._order:
                self._order.append(event_id)


def _event_id(side: str, epoch_s: float) -> str:
    return f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime(epoch_s))}-{side}-{uuid.uuid4().hex[:10]}"


def _write_overlay(
    path: Path,
    frame: ClassificationFrame,
    event: Mapping[str, object],
    *,
    allow_selection: bool = True,
) -> None:
    import cv2

    image = frame.image.copy()
    selected_detection_id = event.get("detection_id")
    for detection in frame.detections:
        x1, y1, x2, y2 = (int(round(value)) for value in detection.bbox_xyxy)
        selected = (
            allow_selection
            and selected_detection_id is not None
            and int(selected_detection_id) == detection.detection_id
        )
        color = (0, 0, 255) if selected else (0, 180, 255)
        thickness = 3 if selected else 2
        cv2.rectangle(image, (x1, y1), (x2, y2), color, thickness)
        radar_label = f" R{event.get('radar_target_id', '--')}" if selected else ""
        cv2.putText(
            image,
            f"{detection.class_name} {detection.confidence:.2f}{radar_label}",
            (x1, max(18, y1 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2.LINE_AA,
        )
    label = (
        f"{str(event.get('side', '')).upper()} L{int(event.get('level', 0))} "
        f"R{event.get('radar_target_id', '--')} {event.get('class_name', 'unknown')} "
        f"d={float(event.get('distance_m', 0.0) or 0.0):.1f}m "
        f"v={float(event.get('speed_mps', 0.0) or 0.0):.1f}m/s"
    )
    cv2.putText(image, label, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 255), 2, cv2.LINE_AA)
    if not cv2.imwrite(str(path), image, [int(cv2.IMWRITE_JPEG_QUALITY), 85]):
        raise RuntimeError("cv2.imwrite returned false")
