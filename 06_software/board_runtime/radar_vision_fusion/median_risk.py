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

    def __init__(self, window_s: float = 0.5, warning_sensitivity: float = 1.0) -> None:
        if window_s <= 0.0:
            raise ValueError("window_s must be positive")
        self.window_s = float(window_s)
        self._warning_sensitivity = _validate_sensitivity(warning_sensitivity)
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
            score_min=min(scores),
            score_max=max(scores),
            score_median=score_median,
            effective_score=effective,
            final_level=risk_level_from_score(effective),
            representative_sample=representative,
        )


def _validate_sensitivity(value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or not 0.25 <= value <= 2.0:
        raise ValueError("warning_sensitivity must be in [0.25, 2.0]")
    return value
