from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass

from .scheduler import CapturedFrame, percentile


@dataclass
class FrameStageTimeline:
    """Monotonic timestamps for one frame selected by the vision pipeline."""

    slice_id: int
    side: str
    capture_slice_start_s: float | None = None
    capture_slice_end_s: float | None = None
    streamoff_complete_s: float | None = None
    decode_start_s: float | None = None
    decode_end_s: float | None = None
    inference_start_s: float | None = None
    inference_end_s: float | None = None
    tracking_start_s: float | None = None
    tracking_end_s: float | None = None
    risk_start_s: float | None = None
    risk_end_s: float | None = None
    overlay_start_s: float | None = None
    overlay_end_s: float | None = None
    jpeg_encode_start_s: float | None = None
    jpeg_encode_end_s: float | None = None
    next_camera_streamon_s: float | None = None
    next_camera_first_frame_s: float | None = None
    processing_complete_s: float | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def select_latest_inference_frames(
    frames: tuple[CapturedFrame, ...] | list[CapturedFrame],
    inference_frames_per_slice: int,
) -> tuple[tuple[CapturedFrame, ...], int]:
    """Return only the newest bounded frames; there is deliberately no queue."""

    limit = int(inference_frames_per_slice)
    if limit < 1:
        raise ValueError("inference_frames_per_slice must be at least 1")
    if limit > len(frames) and frames:
        limit = len(frames)
    selected = tuple(frames[-limit:]) if frames else ()
    return selected, max(0, len(frames) - len(selected))


class ObservationGapTracker:
    """Measure gaps between frames that actually enter vision processing."""

    def __init__(self, *, history_limit: int = 20_000) -> None:
        if history_limit < 1:
            raise ValueError("history_limit must be at least 1")
        self._last_capture_by_side: dict[str, float] = {}
        self._last_observed_side: str | None = None
        self._last_observed_capture_s: float | None = None
        self.gaps_by_side: dict[str, deque[float]] = {
            "left": deque(maxlen=history_limit),
            "right": deque(maxlen=history_limit),
        }
        self.side_to_side_ms: dict[str, deque[float]] = {
            "left_to_right": deque(maxlen=history_limit),
            "right_to_left": deque(maxlen=history_limit),
        }

    def observe(self, side: str, captured_at_s: float) -> dict[str, float | None]:
        captured_at_s = float(captured_at_s)
        previous_same = self._last_capture_by_side.get(side)
        gap_ms = (
            max(0.0, captured_at_s - previous_same) * 1000.0
            if previous_same is not None
            else None
        )
        if gap_ms is not None:
            self.gaps_by_side[side].append(gap_ms)

        side_latency_ms = None
        if (
            self._last_observed_side is not None
            and self._last_observed_side != side
            and self._last_observed_capture_s is not None
        ):
            side_latency_ms = max(0.0, captured_at_s - self._last_observed_capture_s) * 1000.0
            self.side_to_side_ms[f"{self._last_observed_side}_to_{side}"].append(side_latency_ms)

        self._last_capture_by_side[side] = captured_at_s
        self._last_observed_side = side
        self._last_observed_capture_s = captured_at_s
        return {
            "end_to_end_observation_gap_ms": gap_ms,
            "side_to_side_latency_ms": side_latency_ms,
        }

    def summary(self) -> dict[str, object]:
        left_gaps = list(self.gaps_by_side["left"])
        right_gaps = list(self.gaps_by_side["right"])
        combined = left_gaps + right_gaps
        return {
            "end_to_end_left_max_gap_ms": self._maximum(left_gaps),
            "end_to_end_right_max_gap_ms": self._maximum(right_gaps),
            "end_to_end_max_gap_ms": self._maximum(combined),
            "end_to_end_p50_gap_ms": self._percentile(combined, 0.50),
            "end_to_end_p95_gap_ms": self._percentile(combined, 0.95),
            "end_to_end_p99_gap_ms": self._percentile(combined, 0.99),
            "left_to_right_p95_latency_ms": self._percentile(
                list(self.side_to_side_ms["left_to_right"]), 0.95
            ),
            "right_to_left_p95_latency_ms": self._percentile(
                list(self.side_to_side_ms["right_to_left"]), 0.95
            ),
        }

    @staticmethod
    def _maximum(values: list[float]) -> float:
        return round(max(values, default=0.0), 3)

    @staticmethod
    def _percentile(values: list[float], quantile: float) -> float | None:
        value = percentile(values, quantile)
        return round(value, 3) if value is not None else None
