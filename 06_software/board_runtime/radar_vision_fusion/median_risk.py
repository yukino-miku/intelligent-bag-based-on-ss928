from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from statistics import median
from typing import Iterable

from risk_model import RiskAssessment, RiskLevel, risk_level_from_score

try:
    from .models import FusedRadarTarget
except ImportError:
    from models import FusedRadarTarget


@dataclass(frozen=True)
class RadarRiskSample:
    timestamp: float
    track_key: str
    side: str
    class_name: str
    class_weight: float
    base_score: float
    weighted_score: float
    distance_m: float
    speed_mps: float
    closing_speed_mps: float
    ttc_s: float | None
    cpa_time_s: float | None
    cpa_distance_m: float | None
    path_conflict: bool
    radar_quality: float
    scan_complete: bool
    fused: FusedRadarTarget
    assessment: RiskAssessment


@dataclass(frozen=True)
class RiskWindowResult:
    track_key: str
    side: str
    window_start: float
    window_end: float
    sample_count: int
    observed_duration_s: float
    complete_scan_ratio: float
    radar_quality_median: float
    window_valid: bool
    invalid_reason: str
    fast_path_reason: str
    score_min: float
    score_max: float
    score_median: float
    effective_score: float
    final_level: RiskLevel
    representative_sample: RadarRiskSample


@dataclass
class _Window:
    start: float
    end: float
    samples: list[RadarRiskSample]


class MedianRiskWindowAggregator:
    """Independent, non-overlapping monotonic risk windows per radar track."""

    def __init__(
        self,
        window_s: float = 0.5,
        warning_sensitivity: float = 1.0,
        *,
        min_samples_per_window: int = 3,
        min_observed_duration_s: float = 0.25,
        min_complete_scan_ratio: float = 0.67,
        min_radar_quality: float = 0.5,
        fast_path_min_samples: int = 2,
        fast_path_max_distance_m: float = 0.8,
        fast_path_min_closing_speed_mps: float = 1.5,
        fast_path_min_radar_quality: float = 0.75,
    ) -> None:
        if window_s <= 0.0:
            raise ValueError("window_s must be positive")
        self.window_s = float(window_s)
        self._warning_sensitivity = _validate_sensitivity(warning_sensitivity)
        if min_samples_per_window < 1 or fast_path_min_samples < 2:
            raise ValueError("risk window sample thresholds are invalid")
        for name, value in (
            ("min_complete_scan_ratio", min_complete_scan_ratio),
            ("min_radar_quality", min_radar_quality),
            ("fast_path_min_radar_quality", fast_path_min_radar_quality),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if min_observed_duration_s < 0.0 or fast_path_max_distance_m <= 0.0:
            raise ValueError("risk window duration and distance thresholds are invalid")
        self.min_samples_per_window = int(min_samples_per_window)
        self.min_observed_duration_s = float(min_observed_duration_s)
        self.min_complete_scan_ratio = float(min_complete_scan_ratio)
        self.min_radar_quality = float(min_radar_quality)
        self.fast_path_min_samples = int(fast_path_min_samples)
        self.fast_path_max_distance_m = float(fast_path_max_distance_m)
        self.fast_path_min_closing_speed_mps = float(fast_path_min_closing_speed_mps)
        self.fast_path_min_radar_quality = float(fast_path_min_radar_quality)
        self._windows: dict[str, _Window] = {}
        self._lock = threading.RLock()

    @property
    def warning_sensitivity(self) -> float:
        with self._lock:
            return self._warning_sensitivity

    def set_warning_sensitivity(self, value: float) -> None:
        value = _validate_sensitivity(value)
        with self._lock:
            self._warning_sensitivity = value

    def add(self, sample: RadarRiskSample) -> tuple[RiskWindowResult, ...]:
        if not math.isfinite(sample.timestamp) or not math.isfinite(sample.weighted_score):
            return ()
        with self._lock:
            results: list[RiskWindowResult] = []
            current = self._windows.get(sample.track_key)
            if current is not None and sample.timestamp >= current.end:
                results.append(self._finish(sample.track_key, current))
                current = None
            if current is None:
                start = math.floor(sample.timestamp / self.window_s) * self.window_s
                current = _Window(start=start, end=start + self.window_s, samples=[])
                self._windows[sample.track_key] = current
            if sample.timestamp < current.start:
                return tuple(results)
            current.samples.append(sample)
            return tuple(results)

    def flush_due(self, now_s: float) -> tuple[RiskWindowResult, ...]:
        with self._lock:
            due = [key for key, window in self._windows.items() if now_s >= window.end]
            return tuple(self._finish(key, self._windows[key]) for key in sorted(due))

    def remove(self, track_keys: Iterable[str], now_s: float, *, finish: bool = True) -> tuple[RiskWindowResult, ...]:
        with self._lock:
            results: list[RiskWindowResult] = []
            for key in track_keys:
                window = self._windows.get(key)
                if window is None:
                    continue
                if finish and window.samples:
                    results.append(self._finish(key, window, window_end=max(window.start, min(now_s, window.end))))
                else:
                    self._windows.pop(key, None)
            return tuple(results)

    def sample_counts(self) -> dict[str, int]:
        with self._lock:
            return {key: len(window.samples) for key, window in self._windows.items()}

    def clear(self) -> None:
        with self._lock:
            self._windows.clear()

    def _finish(self, track_key: str, window: _Window, *, window_end: float | None = None) -> RiskWindowResult:
        self._windows.pop(track_key, None)
        if not window.samples:
            raise ValueError("cannot finish an empty risk window")
        scores = [max(0.0, min(1.0, sample.weighted_score)) for sample in window.samples]
        score_median = float(median(scores))
        effective = max(0.0, min(1.0, score_median * self._warning_sensitivity))
        timestamps = [sample.timestamp for sample in window.samples]
        observed_duration_s = max(timestamps) - min(timestamps)
        complete_scan_ratio = sum(1 for sample in window.samples if sample.scan_complete) / len(window.samples)
        radar_quality_median = float(median(sample.radar_quality for sample in window.samples))
        invalid_reasons: list[str] = []
        if len(window.samples) < self.min_samples_per_window:
            invalid_reasons.append("insufficient_samples")
        if observed_duration_s < self.min_observed_duration_s:
            invalid_reasons.append("insufficient_observed_duration")
        if complete_scan_ratio < self.min_complete_scan_ratio:
            invalid_reasons.append("low_complete_scan_ratio")
        if radar_quality_median < self.min_radar_quality:
            invalid_reasons.append("low_radar_quality")
        window_valid = not invalid_reasons
        fast_path_reason = ""
        if not window_valid and self._is_fast_path(window.samples, radar_quality_median):
            fast_path_reason = "two_sample_close_high_quality_closing"
        final_level = risk_level_from_score(effective)
        if not window_valid and not fast_path_reason and final_level > RiskLevel.CAUTION:
            final_level = RiskLevel.CAUTION
        representative = min(
            window.samples,
            key=lambda sample: (abs(max(0.0, min(1.0, sample.weighted_score)) - score_median), -sample.timestamp),
        )
        return RiskWindowResult(
            track_key=track_key,
            side=representative.side,
            window_start=window.start,
            window_end=window.end if window_end is None else window_end,
            sample_count=len(window.samples),
            observed_duration_s=observed_duration_s,
            complete_scan_ratio=complete_scan_ratio,
            radar_quality_median=radar_quality_median,
            window_valid=window_valid,
            invalid_reason=",".join(invalid_reasons),
            fast_path_reason=fast_path_reason,
            score_min=min(scores),
            score_max=max(scores),
            score_median=score_median,
            effective_score=effective,
            final_level=final_level,
            representative_sample=representative,
        )

    def _is_fast_path(self, samples: list[RadarRiskSample], radar_quality_median: float) -> bool:
        if len(samples) < self.fast_path_min_samples:
            return False
        recent = sorted(samples, key=lambda sample: sample.timestamp)[-self.fast_path_min_samples :]
        return (
            radar_quality_median >= self.fast_path_min_radar_quality
            and all(sample.scan_complete for sample in recent)
            and all(sample.path_conflict for sample in recent)
            and all(sample.distance_m <= self.fast_path_max_distance_m for sample in recent)
            and all(
                math.isfinite(sample.closing_speed_mps)
                and sample.closing_speed_mps >= self.fast_path_min_closing_speed_mps
                for sample in recent
            )
        )


def _validate_sensitivity(value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or not 0.25 <= value <= 2.0:
        raise ValueError("warning_sensitivity must be in [0.25, 2.0]")
    return value
