from __future__ import annotations

import dataclasses
import json
import math
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
from mr20_radar.mr20_radar import (
    MR20RadarWorker,
    RadarConfig,
    RadarScan,
    RadarScanStatistics,
    RiskConfig,
    load_radar_configs,
)
from risk_model import (
    KinematicRiskTarget,
    RiskAssessment,
    RiskModel,
    RiskModelConfig,
    vehicle_risk_multiplier,
    warning_action_for_level,
)
from risk_stabilizer import StabilizerDebugInfo

try:
    from .alert_history import AlertHistoryStore
    from .alternating_snapshot_classifier import (
        AlternatingSnapshotClassifier,
        SnapshotCameraConfig,
        SnapshotClassifierConfig,
    )
    from .median_risk import MedianRiskWindowAggregator, RadarRiskSample, RiskWindowResult
    from .models import (
        ClassificationFrame,
        FusedRadarTarget,
        LatestVisualClassMap,
        VisualClassEntry,
    )
    from .radar_camera_calibration import FusionCalibration, load_fusion_calibration
    from .radar_tracks import RadarTrack, RadarTrackManager, RadarTrackManagerConfig
    from .radar_vision_association import AssociationConfig, AssociationResult, RadarVisionAssociation
    from .runtime_settings import RuntimeTuningManager, RuntimeTuningState
except ImportError:
    from alert_history import AlertHistoryStore
    from alternating_snapshot_classifier import AlternatingSnapshotClassifier, SnapshotCameraConfig, SnapshotClassifierConfig
    from median_risk import MedianRiskWindowAggregator, RadarRiskSample, RiskWindowResult
    from models import ClassificationFrame, FusedRadarTarget, LatestVisualClassMap, VisualClassEntry
    from radar_camera_calibration import FusionCalibration, load_fusion_calibration
    from radar_tracks import RadarTrack, RadarTrackManager, RadarTrackManagerConfig
    from radar_vision_association import AssociationConfig, AssociationResult, RadarVisionAssociation
    from runtime_settings import RuntimeTuningManager, RuntimeTuningState


@dataclass(frozen=True)
class FusionTargetRisk:
    fused: FusedRadarTarget
    target: KinematicRiskTarget
    raw: RiskAssessment
    stable: RiskAssessment
    stabilizer: StabilizerDebugInfo
    window: RiskWindowResult | None = None


@dataclass(frozen=True)
class FusionRuntimeSettings:
    event_rate_limit_s: float = 0.25
    record_dir: str = ""
    visual_class_max_age_s: float = 1.5
    risk_window_s: float = 0.5
    warning_sensitivity: float = 1.0
    runtime_tuning_path: str = "/etc/smartbag/runtime-tuning.json"
    alert_history_root: str = "/var/lib/smartbag/alarm-events"
    max_alarm_snapshot_age_s: float = 2.0


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
    """Radar-driven fusion using locked latest state and per-track median windows."""

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
        self.risk_model = RiskModel(risk_config)
        self.risk_windows = MedianRiskWindowAggregator(
            self.settings.risk_window_s,
            self.settings.warning_sensitivity,
        )
        self.recorder = FusionJsonlRecorder(self.settings.record_dir)
        self._stop = threading.Event()
        self._started = False
        self._workers: list[MR20RadarWorker] = []
        self._workers_by_name: dict[str, MR20RadarWorker] = {}
        self._latest_risks: dict[str, FusionTargetRisk] = {}
        self._latest_frames: dict[str, ClassificationFrame] = {}
        self._latest_associations: dict[str, AssociationResult] = {}
        self._latest_class_maps: dict[str, LatestVisualClassMap] = {}
        self._latest_scans: dict[str, RadarScan] = {}
        self._latest_complete_scans: dict[str, RadarScan] = {}
        self._scan_stats = {name: RadarScanStatistics() for name in self.radar_configs}
        self._last_emitted: dict[str, tuple[int, str | None, float]] = {}
        self._side_window_index: dict[str, int] = {}
        self._latest_side_median: dict[str, dict[str, object]] = {}
        self._settings_version = 1
        self._lock = threading.RLock()
        self.tuning = RuntimeTuningManager(
            self.calibrations,
            self.association.config,
            self.risk_model.config,
            self.settings.warning_sensitivity,
            path=self.settings.runtime_tuning_path,
            on_apply=self._apply_tuning,
        )
        self.alert_history = AlertHistoryStore(
            self.settings.alert_history_root,
            max_snapshot_age_s=self.settings.max_alarm_snapshot_age_s,
            snapshot_provider=self.latest_frame,
        )

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self._stop.clear()
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
            self._workers_by_name[config.name] = worker
        if self.classifier is not None:
            self.classifier.on_frame = self.submit_classification
            self.classifier.start()

    def stop(self) -> None:
        self._stop.set()
        for worker in self._workers:
            worker.stop()
        self._workers.clear()
        self._workers_by_name.clear()
        if self.classifier is not None:
            self.classifier.stop()
        with self._lock:
            self._started = False
        for side in ("left", "right"):
            self.emit(
                AlertEvent(
                    side=side,
                    level=0,
                    source="radar_vision_fusion",
                    ts=time.monotonic(),
                    clear_reason="runtime_stopped",
                    event_kind="clear",
                )
            )

    def submit_scan(self, scan: RadarScan) -> None:
        try:
            self.process_scan(scan)
        except Exception as exc:
            print(f"[fusion] scan processing failed: {exc}", file=sys.stderr, flush=True)

    def submit_classification(self, frame: ClassificationFrame) -> None:
        try:
            self.process_classification(frame)
        except Exception as exc:
            print(f"[fusion] classification processing failed: {exc}", file=sys.stderr, flush=True)

    def process_scan(self, scan: RadarScan) -> tuple[FusionTargetRisk, ...]:
        radar_config = self.radar_configs.get(scan.radar_name)
        if radar_config is None:
            raise ValueError(f"unknown radar in scan: {scan.radar_name}")
        with self._lock:
            self.recorder.write("radar_scans", scan)
            self._record_scan_status(scan)
            _active_side, removed = self.track_manager.update(scan, radar_config)
            # A disappearing track must not turn a partial window, possibly
            # containing one bad sample, into a formal warning result.
            self.risk_windows.remove(removed, scan.captured_mono_s, finish=False)
            closed_windows: list[RiskWindowResult] = []
            observed_ids = {target.target_id for target in scan.targets}
            for track in self.track_manager.active_tracks(scan.side):
                if track.radar_name != scan.radar_name or track.target_id not in observed_ids:
                    continue
                closed_windows.extend(self.risk_windows.add(self._risk_sample(track, scan)))
            closed_windows.extend(self.risk_windows.flush_due(scan.captured_mono_s))

            current_index = math.floor(scan.captured_mono_s / self.settings.risk_window_s)
            previous_index = self._side_window_index.get(scan.side)
            crossed_boundary = previous_index is not None and current_index > previous_index
            self._side_window_index[scan.side] = current_index
            records = self._publish_window_results(closed_windows, scan.captured_mono_s)
            if crossed_boundary and scan.side not in {record.fused.side for record in records}:
                self._clear_side(scan.side, scan.captured_mono_s, "empty_risk_window")
            return records

    def process_classification(self, frame: ClassificationFrame) -> AssociationResult:
        with self._lock:
            calibration = self.calibrations.get(frame.side)
            if calibration is None:
                raise ValueError(f"no fusion calibration configured for {frame.side}")
            tracks = self.track_manager.active_tracks(frame.side)
            started = time.perf_counter()
            result = self.association.associate(frame, tracks, calibration)
            association_latency_ms = (time.perf_counter() - started) * 1000.0
            updated_frame = replace(frame, association_latency_ms=association_latency_ms)
            entries = {
                track.track_key: VisualClassEntry(
                    association_state="ambiguous" if track.track_key in result.ambiguous_track_keys else "unknown"
                )
                for track in tracks
            }
            for match in result.matches:
                entries[match.track_key] = VisualClassEntry(
                    class_name=match.class_name,
                    confidence=match.class_confidence,
                    detection_id=match.detection_id,
                    association_score=match.association_score,
                    association_state="matched",
                )
            class_map = LatestVisualClassMap(
                side=frame.side,
                frame_id=frame.frame_id,
                captured_mono_s=frame.captured_mono_s,
                mapping=entries,
            )
            self._latest_frames[frame.side] = updated_frame
            self._latest_associations[frame.side] = result
            self._latest_class_maps[frame.side] = class_map
            if self.classifier is not None:
                self.classifier.record_association_latency(association_latency_ms)
            self.recorder.write("classification_frames", replace(updated_frame, image=None))
            self.recorder.write(
                "yolo_detections",
                {
                    "side": frame.side,
                    "frame_id": frame.frame_id,
                    "captured_mono_s": frame.captured_mono_s,
                    "detections": frame.detections,
                },
            )
            self.recorder.write("association_events", {"frame_id": frame.frame_id, "side": frame.side, "result": result})
            self.recorder.write("visual_class_map", class_map)
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

    def latest_class_map(self, side: str) -> LatestVisualClassMap | None:
        with self._lock:
            return self._latest_class_maps.get(side)

    def runtime_settings(self) -> dict[str, object]:
        return self.tuning.as_dict()

    def patch_runtime_settings(self, patch: Mapping[str, object]) -> dict[str, object]:
        return self.tuning.patch(patch)

    def reset_runtime_settings(self) -> dict[str, object]:
        return self.tuning.reset()

    def status(self) -> dict[str, object]:
        now_s = time.monotonic()
        with self._lock:
            records = tuple(self._latest_risks.values())
            active_tracks = self.track_manager.active_tracks()
            class_maps = {
                side: {
                    "frame_id": item.frame_id,
                    "age_s": max(0.0, now_s - item.captured_mono_s),
                    "mapping": _jsonable(item.mapping),
                }
                for side, item in self._latest_class_maps.items()
            }
            scan_stats = {
                name: (
                    self._workers_by_name[name].assembler.statistics.as_dict(now_s)
                    if name in self._workers_by_name else stats.as_dict(now_s)
                )
                for name, stats in self._scan_stats.items()
            }
            latest_median = dict(self._latest_side_median)
            radar_status = {}
            for name in sorted(self.radar_configs):
                latest_scan = self._latest_scans.get(name)
                radar_status[name] = {
                    "side": self.radar_configs[name].side,
                    "online": latest_scan is not None and now_s - latest_scan.captured_mono_s < 1.0,
                    "current_target_count": sum(track.radar_name == name for track in active_tracks),
                    "latest_scan_target_count": len(latest_scan.targets) if latest_scan is not None else 0,
                    "latest_scan_complete": latest_scan.complete if latest_scan is not None else None,
                    "latest_scan_completion_reason": latest_scan.completion_reason if latest_scan is not None else None,
                    **scan_stats[name],
                }
        return {
            "runtime_mode": "radar_primary_visual_classification",
            "radars": radar_status,
            "active_tracks": len(active_tracks),
            "risk_window_s": self.settings.risk_window_s,
            "risk_window_sample_counts": self.risk_windows.sample_counts(),
            "latest_median_risk": latest_median,
            "visual_class_maps": class_maps,
            "warning_sensitivity": self.risk_windows.warning_sensitivity,
            "settings_version": self._settings_version,
            "classifier": self.classifier.status() if self.classifier is not None else {"state": "BLOCKED", "error": self.classifier_error},
            "targets": [_risk_record_dict(item, self.risk_model.config) for item in records],
            "recent_level_3_4_events": self.alert_history.recent(5),
        }

    def _risk_sample(self, track: RadarTrack, scan: RadarScan) -> RadarRiskSample:
        fused, target, raw = self._assess_track(track, scan.captured_mono_s)
        return RadarRiskSample(
            timestamp=scan.captured_mono_s,
            track_key=track.track_key,
            side=track.side,
            class_name=fused.class_name,
            class_weight=vehicle_risk_multiplier(fused.class_name, self.risk_model.config),
            base_score=raw.base_score,
            weighted_score=raw.score,
            distance_m=fused.distance_m,
            speed_mps=fused.speed_mps,
            closing_speed_mps=raw.closing_speed_mps,
            ttc_s=raw.ttc_s,
            cpa_time_s=raw.cpa_time_s,
            cpa_distance_m=raw.cpa_distance_m,
            path_conflict=raw.path_conflict,
            radar_quality=fused.radar_quality,
            scan_complete=scan.complete,
            fused=fused,
            assessment=raw,
        )

    def _assess_track(self, track: RadarTrack, now_s: float) -> tuple[FusedRadarTarget, KinematicRiskTarget, RiskAssessment]:
        visual_map = self._latest_class_maps.get(track.side)
        if visual_map is None:
            entry, class_age_s = VisualClassEntry(), math.inf
        else:
            entry, class_age_s = visual_map.resolve(track.track_key, now_s, self.settings.visual_class_max_age_s)
        class_name = entry.class_name if entry.class_name else "unknown"
        class_source = "vision_snapshot" if class_name != "unknown" else entry.association_state
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
            class_confidence=entry.confidence,
            class_source=class_source,
            class_age_s=class_age_s,
            association_state=entry.association_state,
            association_score=entry.association_score,
            projected_u_px=projection,
            timestamp=track.last_seen_mono_s,
            detection_id=entry.detection_id,
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
        return fused, target, self.risk_model.assess(target)

    def _publish_window_results(
        self,
        windows: Sequence[RiskWindowResult],
        now_s: float,
    ) -> tuple[FusionTargetRisk, ...]:
        records: list[FusionTargetRisk] = []
        for window in windows:
            sample = window.representative_sample
            stable = replace(
                sample.assessment,
                score=window.effective_score,
                level=window.final_level,
                visual_level=window.final_level,
                haptic_level=window.final_level,
                warning_action=warning_action_for_level(window.final_level),
            )
            record = FusionTargetRisk(
                fused=sample.fused,
                target=_target_from_sample(sample),
                raw=sample.assessment,
                stable=stable,
                stabilizer=StabilizerDebugInfo(reason="median_500ms_window"),
                window=window,
            )
            self._latest_risks[record.fused.track_key] = record
            records.append(record)
            self.recorder.write("fused_targets", record.fused)
            self.recorder.write("risk_events", _risk_record_dict(record, self.risk_model.config))

        sides = {record.fused.side for record in records}
        for side in sides:
            candidates = [record for record in records if record.fused.side == side]
            selected = min(candidates, key=_risk_sort_key)
            self._latest_side_median[side] = {
                "track_key": selected.fused.track_key,
                "score_median": selected.window.score_median if selected.window else selected.stable.score,
                "effective_score": selected.stable.score,
                "final_level": int(selected.stable.haptic_level),
                "sample_count": selected.window.sample_count if selected.window else 0,
                "window_start": selected.window.window_start if selected.window else None,
                "window_end": selected.window.window_end if selected.window else None,
            }
            self._emit_selected(side, selected, now_s)
        return tuple(records)

    def _emit_selected(self, side: str, selected: FusionTargetRisk, now_s: float) -> None:
        level = int(selected.stable.haptic_level)
        fused = selected.fused
        event_identity = fused.track_key
        previous_level, previous_track, last_emit_s = self._last_emitted.get(side, (-1, None, float("-inf")))
        changed = level != previous_level or event_identity != previous_track
        if not changed and now_s - last_emit_s < self.settings.event_rate_limit_s:
            return
        window = selected.window
        assessment = selected.stable
        payload = {
            "score_median": window.score_median if window is not None else assessment.score,
            "effective_score": assessment.score,
            "warning_sensitivity": self.risk_windows.warning_sensitivity,
            "radar_name": fused.radar_name,
            "radar_target_id": fused.radar_target_id,
            "radar_track_key": fused.track_key,
            "class_name": fused.class_name,
            "class_confidence": fused.class_confidence,
            "class_weight": vehicle_risk_multiplier(fused.class_name, self.risk_model.config),
            "distance_m": fused.distance_m,
            "speed_mps": fused.speed_mps,
            "closing_speed_mps": assessment.closing_speed_mps,
            "ttc_s": assessment.ttc_s,
            "cpa_time_s": assessment.cpa_time_s,
            "cpa_distance_m": assessment.cpa_distance_m,
            "association_score": fused.association_score,
            "detection_id": fused.detection_id,
            "scan_complete_ratio": self._scan_stats[fused.radar_name].as_dict(now_s)["complete_scan_ratio"],
            "settings_version": self._settings_version,
        }
        stored = self.alert_history.apply(side, level, payload, now_mono_s=now_s)
        event_kind = "heartbeat" if not changed else ("clear" if level == 0 else "alert")
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
            class_weight=payload["class_weight"],
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
            clear_reason="median_window_safe" if level == 0 else None,
            event_id=str(stored["event_id"]) if stored is not None else None,
            score_median=window.score_median if window is not None else assessment.score,
            effective_score=assessment.score,
            warning_sensitivity=self.risk_windows.warning_sensitivity,
            settings_version=self._settings_version,
        )
        self.emit(event)
        self._last_emitted[side] = (level, event_identity, now_s)

    def _clear_side(self, side: str, now_s: float, reason: str) -> None:
        previous_level, previous_track, last_emit_s = self._last_emitted.get(side, (-1, None, float("-inf")))
        changed = previous_level != 0 or previous_track is not None
        if not changed and now_s - last_emit_s < self.settings.event_rate_limit_s:
            return
        self.alert_history.apply(side, 0, {}, now_mono_s=now_s)
        self._latest_side_median[side] = {"final_level": 0, "sample_count": 0, "clear_reason": reason}
        self._latest_risks = {
            key: record for key, record in self._latest_risks.items() if record.fused.side != side
        }
        self.emit(
            AlertEvent(
                side=side,
                level=0,
                source="radar_vision_fusion",
                ts=now_s,
                clear_reason=reason,
                event_kind="clear" if changed else "heartbeat",
            )
        )
        self._last_emitted[side] = (0, None, now_s)

    def _record_scan_status(self, scan: RadarScan) -> None:
        self._latest_scans[scan.radar_name] = scan
        stats = self._scan_stats[scan.radar_name]
        if scan.complete:
            stats.complete_scans += 1
            stats.latest_complete_scan_mono_s = scan.captured_mono_s
            self._latest_complete_scans[scan.radar_name] = scan
            if scan.expected_target_count == 0:
                stats.zero_target_scans += 1
        else:
            stats.incomplete_scans += 1
        stats.duplicate_targets += scan.duplicate_target_count
        stats.sequence_gaps += max(0, scan.measurement_sequence_gap)
        if scan.completion_reason == "orphan_target_frame":
            stats.orphan_target_frames += 1
        if scan.completion_reason in {"timeout", "scan_timeout"}:
            stats.scan_timeouts += 1

    def _apply_tuning(self, state: RuntimeTuningState) -> None:
        with self._lock:
            for name, old_config in tuple(self.radar_configs.items()):
                calibration = state.calibrations.get(old_config.side)
                if calibration is None:
                    continue
                new_config = replace(
                    old_config,
                    mount_x_m=calibration.radar_mount_x_m,
                    mount_yaw_deg=calibration.radar_yaw_deg,
                )
                self.track_manager.retune_mount(name, old_config, new_config)
                self.radar_configs[name] = new_config
            self.calibrations = dict(state.calibrations)
            self.association.config = state.association
            self.risk_model.config = state.risk
            self.risk_windows.clear()
            self.risk_windows.set_warning_sensitivity(state.warning_sensitivity)
            self._settings_version = state.version


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
            target_classes = tuple(
                str(value)
                for value in snapshot_section.get("target_classes", ("bicycle", "motorcycle", "car", "truck", "bus"))
            )
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
                        first_frame_timeout_ms=int(snapshot_section.get("capture_timeout_ms", 1000)),
                        switch_timeout_ms=int(snapshot_section.get("streamoff_timeout_ms", 1000)),
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
                    target_switch_interval_s=float(snapshot_section.get("target_switch_interval_s", 0.20)),
                    initial_warmup_frames=int(snapshot_section.get("initial_warmup_frames", 2)),
                    switch_warmup_frames=int(snapshot_section.get("switch_warmup_frames", 0)),
                    capture_timeout_ms=int(snapshot_section.get("capture_timeout_ms", 1000)),
                    streamoff_timeout_ms=int(snapshot_section.get("streamoff_timeout_ms", 1000)),
                    camera_reset_backoff_s=float(snapshot_section.get("camera_reset_backoff_s", 1.0)),
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
            projection_half_width_px=float(fusion_section.get("projection_half_width_px", 80.0)),
            projection_half_width_ratio=float(fusion_section.get("projection_half_width_ratio", 0.04)),
            bbox_expand_ratio=float(fusion_section.get("bbox_expand_ratio", 0.25)),
            association_max_time_delta_s=float(fusion_section.get("association_max_time_delta_s", 0.20)),
            max_center_distance_px=float(fusion_section.get("max_center_distance_px", 180.0)),
            max_association_cost=float(fusion_section.get("max_association_cost", 1.0)),
            ambiguity_cost_gap=float(fusion_section.get("ambiguity_cost_gap", 0.05)),
        ),
        risk_config=risk_config,
        settings=FusionRuntimeSettings(
            event_rate_limit_s=float(fusion_section.get("event_rate_limit_s", 0.25)),
            record_dir=str(fusion_section.get("record_dir", "")),
            visual_class_max_age_s=float(fusion_section.get("visual_class_max_age_s", 1.5)),
            risk_window_s=float(fusion_section.get("risk_window_s", 0.5)),
            warning_sensitivity=float(fusion_section.get("warning_sensitivity", 1.0)),
            runtime_tuning_path=str(fusion_section.get("runtime_tuning_path", "/etc/smartbag/runtime-tuning.json")),
            alert_history_root=str(fusion_section.get("alert_history_root", "/var/lib/smartbag/alarm-events")),
            max_alarm_snapshot_age_s=float(fusion_section.get("max_alarm_snapshot_age_s", 2.0)),
        ),
    )


def _target_from_sample(sample: RadarRiskSample) -> KinematicRiskTarget:
    fused = sample.fused
    return KinematicRiskTarget(
        track_id=fused.track_key,
        class_name=fused.class_name,
        x_m=fused.x_m,
        z_m=fused.z_m,
        vx_mps=fused.vx_mps,
        vz_mps=fused.vz_mps,
        distance_m=fused.distance_m,
        speed_mps=fused.speed_mps,
        track_age_frames=1,
        velocity_confidence=fused.radar_quality,
        distance_confidence=fused.radar_quality,
        observation_quality=fused.radar_quality,
        source="radar",
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
    window = record.window
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
        "window_start": window.window_start if window else None,
        "window_end": window.window_end if window else None,
        "sample_count": window.sample_count if window else 0,
        "score_min": window.score_min if window else raw.score,
        "score_max": window.score_max if window else raw.score,
        "score_median": window.score_median if window else raw.score,
        "effective_score": window.effective_score if window else stable.score,
        "final_level": window.final_level.name if window else stable.level.name,
        "stabilizer_pending_level": record.stabilizer.pending_level.name,
        "stabilizer_pending_count": record.stabilizer.pending_count,
        "stabilizer_required_frames": record.stabilizer.required_frames,
        "stabilizer_reason": record.stabilizer.reason,
    }


def _jsonable(value: object) -> object:
    if dataclasses.is_dataclass(value):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in dataclasses.fields(value)
            if field.name != "image"
        }
    if isinstance(value, IntEnum):
        return value.name
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}
