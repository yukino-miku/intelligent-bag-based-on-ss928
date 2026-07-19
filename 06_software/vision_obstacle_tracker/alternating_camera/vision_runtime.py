from __future__ import annotations

from contextlib import nullcontext, redirect_stdout
from dataclasses import dataclass
import inspect
import math
from pathlib import Path
import time
from typing import Any, Callable, Protocol, TextIO


class SideDetectionContext(Protocol):
    side: str

    def process_detection(
        self,
        result: object,
        image: object,
        timestamp_s: float,
        **context: object,
    ) -> object: ...


class SharedModelAlternatingEngine:
    """One detector model with two explicitly independent side contexts."""

    def __init__(
        self,
        model_path: str,
        context_factory: Callable[[str], SideDetectionContext],
        *,
        model_factory: Callable[[str], object] | None = None,
        predict_kwargs: dict[str, object] | None = None,
        predict_stdout: TextIO | None = None,
    ) -> None:
        if model_factory is None:
            from ultralytics import YOLO

            model_factory = YOLO
        self.model_path = str(model_path)
        self.model = model_factory(self.model_path)
        self.contexts = {side: context_factory(side) for side in ("left", "right")}
        if self.contexts["left"] is self.contexts["right"]:
            raise ValueError("left and right vision contexts must be different instances")
        self._assert_independent_context_state()
        self.predict_kwargs = dict(predict_kwargs or {})
        self.predict_stdout = predict_stdout
        self.inference_count = 0
        self.last_inference_ms = 0.0

    @property
    def names(self) -> object:
        return getattr(self.model, "names", {})

    def process(
        self,
        side: str,
        image: object,
        timestamp_s: float,
        **context: object,
    ) -> object:
        if side not in self.contexts:
            raise ValueError(f"invalid camera side: {side!r}")
        timeline = context.get("timeline")
        inference_started_s = time.perf_counter()
        if timeline is not None:
            timeline.inference_start_s = time.monotonic()
        output_context = (
            redirect_stdout(self.predict_stdout)
            if self.predict_stdout is not None
            else nullcontext()
        )
        with output_context:
            results = self.model.predict(image, **self.predict_kwargs)
        self.last_inference_ms = (time.perf_counter() - inference_started_s) * 1000.0
        if timeline is not None:
            timeline.inference_end_s = time.monotonic()
        self.inference_count += 1
        if not results:
            raise RuntimeError("detector returned no Results object")
        return self.contexts[side].process_detection(results[0], image, float(timestamp_s), **context)

    def _assert_independent_context_state(self) -> None:
        left = self.contexts["left"]
        right = self.contexts["right"]
        independent_attributes = (
            "tracker",
            "calibration",
            "stable_track_ids",
            "track_state",
            "risk_model",
            "risk_stabilizer",
            "self_object_filter",
            "risk_logger",
        )
        shared = [
            name
            for name in independent_attributes
            if hasattr(left, name) and hasattr(right, name) and getattr(left, name) is getattr(right, name)
        ]
        if shared:
            raise ValueError(f"left and right vision contexts share mutable state: {', '.join(shared)}")


@dataclass(frozen=True)
class TrackerRuntimeConfig:
    tracker_yaml: str
    frame_rate: float = 30.0
    effective_fps_mode: str = "fixed"
    expected_side_fps: float | None = None
    minimum_buffer_frames: int = 2

    def __post_init__(self) -> None:
        if self.frame_rate <= 0.0:
            raise ValueError("tracker frame_rate must be positive")
        if self.effective_fps_mode not in ("fixed", "negotiated", "effective_side"):
            raise ValueError("tracker effective_fps_mode must be fixed, negotiated, or effective_side")


def tracker_buffer_frames(
    effective_fps: float,
    track_buffer: int,
    *,
    reference_fps: float = 30.0,
    minimum_frames: int = 2,
) -> int:
    """Convert Ultralytics' 30 FPS track buffer to an equivalent time window."""

    retention_s = max(1, int(track_buffer)) / max(float(reference_fps), 1.0)
    return max(int(minimum_frames), min(300, int(math.ceil(max(effective_fps, 0.1) * retention_s))))


class IndependentUltralyticsTracker:
    """A private BoT-SORT/ByteTrack instance for one camera only."""

    def __init__(self, config: TrackerRuntimeConfig) -> None:
        from ultralytics.trackers import BOTSORT, BYTETracker
        from ultralytics.utils import YAML, IterableSimpleNamespace
        from ultralytics.utils.checks import check_yaml

        tracker_path = check_yaml(str(Path(config.tracker_yaml)))
        tracker_args = IterableSimpleNamespace(**YAML.load(tracker_path))
        tracker_type = str(getattr(tracker_args, "tracker_type", "botsort")).lower()
        if tracker_type == "botsort":
            tracker_cls = BOTSORT
        elif tracker_type == "bytetrack":
            tracker_cls = BYTETracker
        else:
            raise ValueError(f"unsupported Ultralytics tracker_type: {tracker_type!r}")
        initial_fps = (
            config.expected_side_fps
            if config.effective_fps_mode == "effective_side" and config.expected_side_fps
            else config.frame_rate
        )
        tracker_parameters = inspect.signature(tracker_cls).parameters
        tracker_kwargs: dict[str, object] = {"args": tracker_args}
        if "frame_rate" in tracker_parameters:
            tracker_kwargs["frame_rate"] = max(1, int(round(initial_fps)))
        self.tracker = tracker_cls(**tracker_kwargs)
        self.config = config
        self.tracker_args = tracker_args
        self.configured_track_buffer = max(1, int(getattr(tracker_args, "track_buffer", 30)))
        self.current_effective_fps = float(initial_fps)
        self.update_effective_fps(float(initial_fps))

    def update_effective_fps(self, effective_fps: float) -> None:
        if self.config.effective_fps_mode != "effective_side" or effective_fps <= 0.0:
            return
        self.current_effective_fps = float(effective_fps)
        if hasattr(self.tracker, "frame_rate"):
            self.tracker.frame_rate = max(1, int(round(effective_fps)))
        if hasattr(self.tracker, "max_time_lost"):
            self.tracker.max_time_lost = tracker_buffer_frames(
                effective_fps,
                self.configured_track_buffer,
                minimum_frames=self.config.minimum_buffer_frames,
            )

    def update(self, result: Any, image: object) -> Any:
        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return result

        import numpy as np
        import torch

        detections = boxes.cpu().numpy()
        tracks = self.tracker.update(detections, image)
        if len(tracks) == 0:
            result.update(boxes=torch.empty((0, 7)))
            return result
        tracks = np.asarray(tracks)
        source_indices = tracks[:, -1].astype(int)
        tracked_result = result[source_indices]
        tracked_result.update(boxes=torch.as_tensor(tracks[:, :-1]))
        return tracked_result
