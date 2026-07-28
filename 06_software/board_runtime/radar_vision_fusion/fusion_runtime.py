from __future__ import annotations

import dataclasses
import json
import math
import queue
import sys
import threading
import time
from dataclasses import dataclass, replace
from enum import IntEnum
from pathlib import Path
from typing import Callable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
BOARD_RUNTIME_DIR = HERE.parent
VISION_DIR = BOARD_RUNTIME_DIR / "vision"
if not VISION_DIR.is_dir():
    VISION_DIR = BOARD_RUNTIME_DIR.parent / "vision_obstacle_tracker"
CONTROLLER_DIR = BOARD_RUNTIME_DIR / "controller"
if not CONTROLLER_DIR.is_dir():
    CONTROLLER_DIR = BOARD_RUNTIME_DIR / "smartbag_alert_controller"
for path in (BOARD_RUNTIME_DIR, VISION_DIR, CONTROLLER_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from alert_core import AlertEvent
from detector_backend import Ss928OmBackend, UltralyticsBackend
from mr20_radar.mr20_radar import MR20RadarWorker, RadarConfig, RadarScan, RiskConfig, load_radar_configs
from risk_model import KinematicRiskTarget, RiskAssessment, RiskLevel, RiskModel, RiskModelConfig, vehicle_risk_multiplier
from risk_stabilizer import RiskWarningStabilizer, StabilizerDebugInfo

try:
    from .alternating_snapshot_classifier import (
        AlternatingSnapshotClassifier,
        SnapshotCameraConfig,
        SnapshotClassifierConfig,
    )
    from .models import ClassificationFrame, FusedRadarTarget
    from .radar_camera_calibration import FusionCalibration, load_fusion_calibration
    from .radar_tracks import RadarTrack, RadarTrackManager, RadarTrackManagerConfig
    from .radar_vision_association import AssociationConfig, AssociationResult, RadarVisionAssociation
    from .visual_binding import BindingConfig, BindingEvent, VisualClassBindingManager
except ImportError:
    from alternating_snapshot_classifier import AlternatingSnapshotClassifier, SnapshotCameraConfig, SnapshotClassifierConfig
    from models import ClassificationFrame, FusedRadarTarget
    from radar_camera_calibration import FusionCalibration, load_fusion_calibration
    from radar_tracks import RadarTrack, RadarTrackManager, RadarTrackManagerConfig
    from radar_vision_association import AssociationConfig, AssociationResult, RadarVisionAssociation
    from visual_binding import BindingConfig, BindingEvent, VisualClassBindingManager


@dataclass(frozen=True)
class FusionTargetRisk:
    fused: FusedRadarTarget
    target: KinematicRiskTarget
    raw: RiskAssessment
    stable: RiskAssessment
    stabilizer: StabilizerDebugInfo


@dataclass(frozen=True)
class FusionRuntimeSettings:
    event_rate_limit_s: float = 0.25
    queue_size: int = 16
    record_dir: str = ""


class FusionJsonlRecorder:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root) if str(root) else None
        self._lock = threading.Lock()

    def write(self, stream: str, payload: object) -> None:
        if self.root is None:
            return
        record = _jsonable(payload)
        if isinstance(record, dict):
            record = {"type": stream, **record}
        else:
            record = {"type": stream, "value": record}
        path = self.root / f"{stream}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


class RadarVisionFusionRuntime:
    def __init__(
        self,
        radar_configs: Sequence[RadarConfig],
        legacy_risk_config: RiskConfig,
        calibrations: Mapping[str, FusionCalibration],
        emit: Callable[[AlertEvent], None],
        *,
        classifier: AlternatingSnapshotClassifier | None = None,
        classifier_error: str = "",
        track_config: RadarTrackManagerConfig | None = None,
        association_config: AssociationConfig | None = None,
        binding_config: BindingConfig | None = None,
        risk_config: RiskModelConfig | None = None,
        settings: FusionRuntimeSettings | None = None,
    ) -> None:
        self.radar_configs = {item.name: item for item in radar_configs}
        self.legacy_risk_config = legacy_risk_config
        self.calibrations = dict(calibrations)
        self.emit = emit
        self.classifier = classifier
        self.classifier_error = classifier_error
        self.settings = settings or FusionRuntimeSettings()
        self.track_manager = RadarTrackManager(track_config)
        self.association = RadarVisionAssociation(association_config)
        self.bindings = VisualClassBindingManager(binding_config)
        self.risk_model = RiskModel(risk_config)
        self.stabilizer = RiskWarningStabilizer()
        self.recorder = FusionJsonlRecorder(self.settings.record_dir)
        self._queue: "queue.Queue[tuple[str, object]]" = queue.Queue(maxsize=max(2, self.settings.queue_size))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._workers: list[MR20RadarWorker] = []
        self._latest_risks: dict[str, FusionTargetRisk] = {}
        self._latest_frames: dict[str, ClassificationFrame] = {}
        self._latest_associations: dict[str, AssociationResult] = {}
        self._last_emitted: dict[str, tuple[int, str | None, float]] = {}
        self._lock = threading.RLock()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="radar-vision-fusion", daemon=True)
        self._thread.start()
        for config in self.radar_configs.values():
            worker = MR20RadarWorker(
                config,
                self.legacy_risk_config,
                emit=None,
                on_scan=self.submit_scan,
                evaluate_legacy_risk=False,
            )
            worker.start()
            self._workers.append(worker)
        if self.classifier is not None:
            self.classifier.on_frame = self.submit_classification
            self.classifier.start()

    def stop(self) -> None:
        self._stop.set()
        for worker in self._workers:
            worker.stop()
        self._workers.clear()
        if self.classifier is not None:
            self.classifier.stop()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        for side in ("left", "right"):
            self.emit(AlertEvent(side=side, level=0, source="radar_vision_fusion", ts=time.monotonic(), clear_reason="runtime_stopped", event_kind="clear"))

    def submit_scan(self, scan: RadarScan) -> None:
        self._offer("scan", scan)

    def submit_classification(self, frame: ClassificationFrame) -> None:
        self._offer("classification", frame)

    def process_scan(self, scan: RadarScan) -> tuple[FusionTargetRisk, ...]:
        radar_config = self.radar_configs.get(scan.radar_name)
        if radar_config is None:
            raise ValueError(f"unknown radar in scan: {scan.radar_name}")
        self.recorder.write("radar_scans", scan)
        _active_side, removed = self.track_manager.update(scan, radar_config)
        if removed:
            self.bindings.remove_tracks(removed)
            self.association.forget(removed)
            self.stabilizer.clear_tracks(set(removed))
        records = self._assess_all(scan.captured_mono_s)
        self._emit_side_levels(scan.captured_mono_s, records)
        return records

    def process_classification(self, frame: ClassificationFrame) -> AssociationResult:
        calibration = self.calibrations.get(frame.side)
        if calibration is None:
            raise ValueError(f"no fusion calibration configured for {frame.side}")
        tracks = self.track_manager.active_tracks(frame.side)
        self.recorder.write("classification_frames", replace(frame, image=None))
        self.recorder.write("yolo_detections", {"side": frame.side, "frame_id": frame.frame_id, "captured_mono_s": frame.captured_mono_s, "detections": frame.detections})
        result = self.association.associate(frame, tracks, calibration, self.bindings.bound_classes())
        binding_events = self.bindings.update(frame, result.matches, tracks, result.projections)
        self.recorder.write("association_events", {"frame_id": frame.frame_id, "side": frame.side, "result": result})
        for event in binding_events:
            self.recorder.write("binding_events", event)
        with self._lock:
            self._latest_frames[frame.side] = frame
            self._latest_associations[frame.side] = result
        return result

    def latest_risks(self) -> tuple[FusionTargetRisk, ...]:
        with self._lock:
            return tuple(self._latest_risks.values())

    def latest_frame(self, side: str) -> ClassificationFrame | None:
        with self._lock:
            return self._latest_frames.get(side)

    def latest_association(self, side: str) -> AssociationResult | None:
        with self._lock:
            return self._latest_associations.get(side)

    def status(self) -> dict[str, object]:
        now_s = time.monotonic()
        with self._lock:
            records = tuple(self._latest_risks.values())
        return {
            "runtime_mode": "radar_primary_visual_classification",
            "radars": sorted(self.radar_configs),
            "active_tracks": len(self.track_manager.active_tracks()),
            "classifier": self.classifier.status() if self.classifier is not None else {"state": "BLOCKED", "error": self.classifier_error},
            "targets": [_risk_record_dict(item, self.risk_model.config) for item in records],
            "age_s": max((now_s - item.fused.timestamp for item in records), default=0.0),
        }

    def _assess_all(self, now_s: float) -> tuple[FusionTargetRisk, ...]:
        raw_by_key: dict[str, RiskAssessment] = {}
        target_by_key: dict[str, KinematicRiskTarget] = {}
        fused_by_key: dict[str, FusedRadarTarget] = {}
        for track in self.track_manager.active_tracks():
            class_name, class_confidence, class_source, class_age_s, binding_state, association_score = self.bindings.resolve(track.track_key, now_s)
            projection = _projection_for_track(self._latest_associations.get(track.side), track.track_key)
            fused = FusedRadarTarget(
                track_key=track.track_key,
                radar_name=track.radar_name,
                radar_target_id=track.target_id,
                side=track.side,
                x_m=track.x_m,
                z_m=track.z_m,
                vx_mps=track.vx_mps,
                vz_mps=track.vz_mps,
                distance_m=track.distance_m,
                speed_mps=track.speed_mps,
                radar_status=track.status,
                radar_quality=track.radar_quality,
                class_name=class_name,
                class_confidence=class_confidence,
                class_source=class_source,
                class_age_s=class_age_s,
                association_state=binding_state,
                association_score=association_score,
                projected_u_px=projection,
                timestamp=track.last_seen_mono_s,
            )
            quality = track.radar_quality
            target = KinematicRiskTarget(
                track_id=track.track_key,
                class_name=class_name,
                x_m=track.x_m,
                z_m=track.z_m,
                vx_mps=track.vx_mps,
                vz_mps=track.vz_mps,
                distance_m=track.distance_m,
                speed_mps=track.speed_mps,
                track_age_frames=track.age_scans,
                velocity_confidence=quality,
                distance_confidence=max(0.5, quality),
                observation_quality=quality,
                velocity_stability=quality,
                position_jitter_m=track.position_jitter_m,
                distance_trend_mps=track.distance_trend_mps,
                approach_consistency=track.approach_consistency,
                path_conflict_consistency=track.path_conflict_consistency,
                motion_quality_flags=track.motion_quality_flags,
                source="radar",
            )
            raw_by_key[track.track_key] = self.risk_model.assess(target)
            target_by_key[track.track_key] = target
            fused_by_key[track.track_key] = fused

        stable_by_key = self.stabilizer.stabilize(raw_by_key, target_by_key)
        debug_by_key = self.stabilizer.debug_info_by_track_id()
        records = tuple(
            FusionTargetRisk(
                fused=fused_by_key[key],
                target=target_by_key[key],
                raw=raw_by_key[key],
                stable=stable_by_key[key],
                stabilizer=debug_by_key.get(key, StabilizerDebugInfo()),
            )
            for key in sorted(raw_by_key)
        )
        with self._lock:
            self._latest_risks = {item.fused.track_key: item for item in records}
        for record in records:
            self.recorder.write("fused_targets", record.fused)
            self.recorder.write("risk_events", _risk_record_dict(record, self.risk_model.config))
        return records

    def _emit_side_levels(self, now_s: float, records: Sequence[FusionTargetRisk]) -> None:
        for side in ("left", "right"):
            candidates = [item for item in records if item.fused.side == side]
            selected = min(candidates, key=_risk_sort_key) if candidates else None
            level = int(selected.stable.haptic_level) if selected is not None else 0
            track_key = selected.fused.track_key if selected is not None else None
            event_identity = (
                f"{track_key}|{selected.fused.class_name}|{selected.fused.association_state}"
                if selected is not None else None
            )
            previous_level, previous_track, last_emit_s = self._last_emitted.get(side, (-1, None, float("-inf")))
            changed = level != previous_level or event_identity != previous_track
            if not changed and now_s - last_emit_s < self.settings.event_rate_limit_s:
                continue
            event_kind = "heartbeat" if not changed else ("clear" if level == 0 else "alert")
            if selected is None:
                event = AlertEvent(
                    side=side,
                    level=0,
                    source="radar_vision_fusion",
                    ts=now_s,
                    clear_reason="no_active_tracks",
                    event_kind=event_kind,
                )
            else:
                fused = selected.fused
                assessment = selected.stable
                event = AlertEvent(
                    side=side,
                    level=level,
                    source="radar_vision_fusion",
                    score=assessment.score,
                    track_id=fused.track_key,
                    ts=now_s,
                    class_name=fused.class_name,
                    distance_m=fused.distance_m,
                    radar_name=fused.radar_name,
                    radar_target_id=fused.radar_target_id,
                    radar_track_key=fused.track_key,
                    class_confidence=fused.class_confidence,
                    class_weight=vehicle_risk_multiplier(fused.class_name, self.risk_model.config),
                    class_source=fused.class_source,
                    lateral_distance_m=fused.x_m,
                    longitudinal_distance_m=fused.z_m,
                    vx_mps=fused.vx_mps,
                    vz_mps=fused.vz_mps,
                    speed_mps=fused.speed_mps,
                    closing_speed_mps=assessment.closing_speed_mps,
                    ttc_s=assessment.ttc_s,
                    cpa_time_s=assessment.cpa_time_s,
                    cpa_distance_m=assessment.cpa_distance_m,
                    association_state=fused.association_state,
                    association_score=fused.association_score,
                    event_kind=event_kind,
                    clear_reason="stable_safe" if level == 0 else None,
                )
            self.emit(event)
            self._last_emitted[side] = (level, event_identity, now_s)

    def _offer(self, kind: str, payload: object) -> None:
        try:
            self._queue.put_nowait((kind, payload))
            return
        except queue.Full:
            pass
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        self._queue.put_nowait((kind, payload))

    def _run(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            try:
                kind, payload = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if kind == "scan":
                    self.process_scan(payload)  # type: ignore[arg-type]
                elif kind == "classification":
                    self.process_classification(payload)  # type: ignore[arg-type]
            except Exception as exc:
                print(f"[fusion] {kind} processing failed: {exc}", file=sys.stderr, flush=True)


def build_fusion_runtime(config: Mapping[str, object], emit: Callable[[AlertEvent], None]) -> RadarVisionFusionRuntime:
    radar_section = _mapping(config.get("radar"))
    radar_path = str(radar_section.get("config", ""))
    if not radar_path:
        raise ValueError("radar_primary_visual_classification requires radar.config")
    radar_configs, legacy_risk = load_radar_configs(radar_path)
    fusion_section = _mapping(config.get("fusion"))
    snapshot_section = _mapping(config.get("snapshot_classifier"))
    cameras_section = _mapping(config.get("cameras"))

    calibrations: dict[str, FusionCalibration] = {}
    for side in ("left", "right"):
        camera = _mapping(cameras_section.get(side))
        calibration_path = str(fusion_section.get(f"{side}_calibration", ""))
        if calibration_path:
            calibrations[side] = load_fusion_calibration(calibration_path)
        else:
            calibrations[side] = FusionCalibration.from_mapping(
                {
                    "side": side,
                    "camera_horizontal_fov_deg": camera.get("camera_horizontal_fov_deg", 90.0),
                    "camera_rotation_deg": camera.get("rotation_deg", 0),
                    "camera_flip_horizontal": camera.get("flip_horizontal", False),
                    "camera_flip_vertical": camera.get("flip_vertical", False),
                }
            )

    classifier = None
    classifier_error = "snapshot classifier disabled"
    if bool(snapshot_section.get("enabled", True)):
        try:
            backend_name = str(snapshot_section.get("backend", "ss928_om"))
            model_path = str(snapshot_section.get("model", _mapping(config.get("paths")).get("model", "")))
            imgsz = int(snapshot_section.get("imgsz", 640))
            confidence = float(snapshot_section.get("confidence", 0.25))
            max_det = int(snapshot_section.get("max_det", 30))
            target_classes = tuple(str(value) for value in snapshot_section.get("target_classes", ("bicycle", "motorcycle", "car", "truck", "bus")))
            if backend_name == "ss928_om":
                backend = Ss928OmBackend(
                    model_path,
                    runner_path=str(snapshot_section.get("runner", "")) or None,
                    imgsz=imgsz,
                    confidence=confidence,
                    max_det=max_det,
                    target_classes=",".join(target_classes),
                    response_timeout_s=float(snapshot_section.get("inference_timeout_ms", 5000)) / 1000.0,
                )
            elif backend_name == "ultralytics":
                from ultralytics import YOLO

                backend = UltralyticsBackend(YOLO(model_path))
            else:
                raise ValueError(f"unsupported snapshot classifier backend: {backend_name}")
            camera_configs = []
            for side in ("left", "right"):
                camera = _mapping(cameras_section.get(side))
                device = str(snapshot_section.get(f"{side}_device", camera.get("camera_device", "")))
                if not device:
                    continue
                camera_configs.append(
                    SnapshotCameraConfig(
                        side=side,
                        device=device,
                        width=int(snapshot_section.get("width", camera.get("width", 640))),
                        height=int(snapshot_section.get("height", camera.get("height", 480))),
                        fps=float(snapshot_section.get("fps", camera.get("camera_fps", 10.0))),
                        warmup_frames=int(snapshot_section.get("warmup_frames", 2)),
                        capture_frames=int(snapshot_section.get("capture_frames", 1)),
                        first_frame_timeout_ms=int(snapshot_section.get("first_frame_timeout_ms", 1000)),
                        switch_timeout_ms=int(snapshot_section.get("switch_timeout_ms", 1000)),
                        rotation_deg=int(camera.get("rotation_deg", 0)),
                        flip_horizontal=bool(camera.get("flip_horizontal", False)),
                        flip_vertical=bool(camera.get("flip_vertical", False)),
                    )
                )
            classifier = AlternatingSnapshotClassifier(
                backend,
                camera_configs,
                SnapshotClassifierConfig(
                    imgsz=imgsz,
                    confidence=confidence,
                    max_det=max_det,
                    snapshot_interval_ms=int(snapshot_section.get("snapshot_interval_ms", 0)),
                    target_classes=target_classes,
                ),
            )
            classifier_error = ""
        except Exception as exc:
            classifier = None
            classifier_error = str(exc)

    risk_section = _mapping(config.get("risk"))
    multipliers = RiskModelConfig().vehicle_risk_multipliers
    configured_multipliers = _mapping(risk_section.get("vehicle_risk_multipliers"))
    if configured_multipliers:
        multipliers = {**multipliers, **{str(key): float(value) for key, value in configured_multipliers.items()}}
    risk_config = replace(RiskModelConfig(), vehicle_risk_multipliers=multipliers)
    return RadarVisionFusionRuntime(
        radar_configs,
        legacy_risk,
        calibrations,
        emit,
        classifier=classifier,
        classifier_error=classifier_error,
        track_config=RadarTrackManagerConfig(
            radar_track_timeout_s=float(fusion_section.get("radar_track_timeout_s", 0.8)),
            radar_max_missed_scans=int(fusion_section.get("radar_max_missed_scans", 3)),
        ),
        association_config=AssociationConfig(
            max_time_delta_s=float(fusion_section.get("association_max_time_delta_s", 0.20)),
            max_horizontal_error_px=float(fusion_section.get("max_horizontal_error_px", 160.0)),
            max_horizontal_error_ratio=float(fusion_section.get("max_horizontal_error_ratio", 0.15)),
            max_association_cost=float(fusion_section.get("max_association_cost", 1.0)),
        ),
        binding_config=BindingConfig(
            binding_min_confirmations=int(fusion_section.get("binding_min_confirmations", 2)),
            binding_max_visual_misses=int(fusion_section.get("binding_max_visual_misses", 3)),
            visual_binding_timeout_s=float(fusion_section.get("visual_binding_timeout_s", 3.0)),
            class_switch_confirmations=int(fusion_section.get("class_switch_confirmations", 3)),
            class_vote_window=int(fusion_section.get("class_vote_window", 5)),
        ),
        risk_config=risk_config,
        settings=FusionRuntimeSettings(
            event_rate_limit_s=float(fusion_section.get("event_rate_limit_s", 0.25)),
            queue_size=int(fusion_section.get("queue_size", 16)),
            record_dir=str(fusion_section.get("record_dir", "")),
        ),
    )


def _risk_sort_key(record: FusionTargetRisk) -> tuple[float, float, float, float, float]:
    return (
        -float(record.stable.haptic_level),
        -record.stable.score,
        record.stable.ttc_s if record.stable.ttc_s is not None else math.inf,
        record.stable.cpa_distance_m if record.stable.cpa_distance_m is not None else math.inf,
        record.fused.distance_m,
    )


def _projection_for_track(result: AssociationResult | None, track_key: str) -> float | None:
    if result is None:
        return None
    projection = next((item for item in result.projections if item.track_key == track_key), None)
    return projection.projected_u_px if projection is not None else None


def _risk_record_dict(record: FusionTargetRisk, risk_config: RiskModelConfig | None = None) -> dict[str, object]:
    raw = record.raw
    stable = record.stable
    return {
        **_jsonable(record.fused),
        "class_weight": vehicle_risk_multiplier(record.fused.class_name, risk_config or RiskModelConfig()),
        "closing_speed_mps": raw.closing_speed_mps,
        "trajectory_distance_m": raw.trajectory_distance_m,
        "ttc_s": raw.ttc_s,
        "drac_mps2": raw.drac_mps2,
        "cpa_time_s": raw.cpa_time_s,
        "cpa_distance_m": raw.cpa_distance_m,
        "path_conflict": raw.path_conflict,
        "moving_away": raw.moving_away,
        "approaching": raw.approaching,
        "corridor_zone": raw.corridor_zone.name,
        "conflict_reason": raw.conflict_reason,
        "trajectory_risk": raw.trajectory_risk,
        "ttc_risk": raw.ttc_risk,
        "drac_risk": raw.drac_risk,
        "closing_risk": raw.closing_risk,
        "base_score": raw.base_score,
        "weighted_score": raw.weighted_score,
        "raw_level": raw.level.name,
        "visual_level": stable.visual_level.name,
        "haptic_level": stable.haptic_level.name,
        "risk_action_reason": raw.risk_action_reason,
        "stabilizer_pending_level": record.stabilizer.pending_level.name,
        "stabilizer_pending_count": record.stabilizer.pending_count,
        "stabilizer_required_frames": record.stabilizer.required_frames,
        "stabilizer_reason": record.stabilizer.reason,
    }


def _jsonable(value: object) -> object:
    if dataclasses.is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in dataclasses.fields(value) if field.name != "image"}
    if isinstance(value, IntEnum):
        return value.name
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}
