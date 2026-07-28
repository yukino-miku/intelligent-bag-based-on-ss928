from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence

try:
    from .models import AssociationMatch, ClassificationFrame, ProjectedRadarTarget
    from .radar_tracks import RadarTrack
except ImportError:
    from models import AssociationMatch, ClassificationFrame, ProjectedRadarTarget
    from radar_tracks import RadarTrack


class BindingState(str, Enum):
    UNBOUND = "UNBOUND"
    CANDIDATE = "CANDIDATE"
    BOUND = "BOUND"
    STALE = "STALE"
    CLEARED = "CLEARED"


@dataclass(frozen=True)
class BindingConfig:
    binding_min_confirmations: int = 2
    binding_max_visual_misses: int = 3
    visual_binding_timeout_s: float = 3.0
    class_switch_confirmations: int = 3
    class_vote_window: int = 5


@dataclass
class VisualClassBinding:
    radar_track_key: str
    side: str
    class_name: str = "unknown"
    class_confidence: float = 0.0
    first_bound_mono_s: float = 0.0
    last_confirmed_mono_s: float = 0.0
    last_visual_frame_id: int = -1
    confirmation_count: int = 0
    miss_count: int = 0
    class_vote_history: list[str] = field(default_factory=list)
    association_score: float | None = None
    binding_state: BindingState = BindingState.UNBOUND
    switch_candidate: str = ""
    switch_count: int = 0


@dataclass(frozen=True)
class BindingEvent:
    track_key: str
    side: str
    event: str
    state: str
    class_name: str
    frame_id: int
    timestamp: float


class VisualClassBindingManager:
    def __init__(self, config: BindingConfig | None = None) -> None:
        self.config = config or BindingConfig()
        self._bindings: dict[str, VisualClassBinding] = {}

    def update(
        self,
        frame: ClassificationFrame,
        matches: Sequence[AssociationMatch],
        active_tracks: Sequence[RadarTrack],
        projections: Sequence[ProjectedRadarTarget],
    ) -> tuple[BindingEvent, ...]:
        events: list[BindingEvent] = []
        active_by_key = {track.track_key: track for track in active_tracks if track.active}
        projection_by_key = {item.track_key: item for item in projections}
        matches_by_key = {item.track_key: item for item in matches}

        for track_key, match in matches_by_key.items():
            binding = self._bindings.setdefault(
                track_key,
                VisualClassBinding(radar_track_key=track_key, side=frame.side),
            )
            event_name = self._confirm(binding, match, frame)
            if event_name:
                events.append(self._event(binding, event_name, frame))

        for track_key, track in active_by_key.items():
            if track.side != frame.side or track_key in matches_by_key:
                continue
            binding = self._bindings.get(track_key)
            if binding is None:
                continue
            projection = projection_by_key.get(track_key)
            if projection is not None and not projection.projected_in_frame:
                events.append(self._clear(binding, "left_fov", frame))
                continue
            binding.miss_count += 1
            if binding.miss_count >= self.config.binding_max_visual_misses:
                events.append(self._clear(binding, "visual_miss_limit", frame))
            elif binding.binding_state == BindingState.BOUND:
                binding.binding_state = BindingState.STALE

        active_keys = {
            track_key for track_key, track in active_by_key.items()
            if track.side == frame.side
        }
        for track_key, binding in list(self._bindings.items()):
            if binding.side == frame.side and track_key not in active_keys:
                events.append(self._clear(binding, "radar_track_removed", frame))
        self.expire(frame.captured_mono_s, events=events, frame=frame)
        return tuple(events)

    def expire(
        self,
        now_s: float,
        *,
        events: list[BindingEvent] | None = None,
        frame: ClassificationFrame | None = None,
    ) -> tuple[str, ...]:
        expired: list[str] = []
        for track_key, binding in list(self._bindings.items()):
            if binding.binding_state in {BindingState.UNBOUND, BindingState.CLEARED}:
                continue
            if now_s - binding.last_confirmed_mono_s > self.config.visual_binding_timeout_s:
                expired.append(track_key)
                if events is not None and frame is not None:
                    events.append(self._clear(binding, "binding_timeout", frame))
                else:
                    binding.binding_state = BindingState.CLEARED
        return tuple(expired)

    def remove_tracks(self, track_keys: Sequence[str]) -> None:
        for track_key in track_keys:
            self._bindings.pop(track_key, None)

    def bound_classes(self) -> dict[str, str]:
        return {
            key: binding.class_name
            for key, binding in self._bindings.items()
            if binding.binding_state in {BindingState.BOUND, BindingState.STALE}
        }

    def resolve(self, track_key: str, now_s: float) -> tuple[str, float, str, float, str, float | None]:
        binding = self._bindings.get(track_key)
        if binding is None or binding.binding_state not in {BindingState.BOUND, BindingState.STALE}:
            return "unknown", 0.0, "unknown", 0.0, BindingState.UNBOUND.value, None
        age_s = max(0.0, now_s - binding.last_confirmed_mono_s)
        if age_s > self.config.visual_binding_timeout_s:
            binding.binding_state = BindingState.CLEARED
            return "unknown", 0.0, "unknown", age_s, BindingState.CLEARED.value, None
        source = "vision_bound" if binding.binding_state == BindingState.BOUND else "cached_binding"
        return (
            binding.class_name,
            binding.class_confidence,
            source,
            age_s,
            binding.binding_state.value,
            binding.association_score,
        )

    def _confirm(self, binding: VisualClassBinding, match: AssociationMatch, frame: ClassificationFrame) -> str:
        binding.miss_count = 0
        binding.last_visual_frame_id = frame.frame_id
        binding.last_confirmed_mono_s = frame.captured_mono_s
        binding.association_score = match.association_score
        binding.class_vote_history.append(match.class_name)
        del binding.class_vote_history[:-self.config.class_vote_window]

        if binding.binding_state in {BindingState.UNBOUND, BindingState.CANDIDATE, BindingState.CLEARED}:
            if binding.class_name == match.class_name and binding.binding_state == BindingState.CANDIDATE:
                binding.confirmation_count += 1
            else:
                binding.class_name = match.class_name
                binding.class_confidence = match.class_confidence
                binding.confirmation_count = 1
                binding.first_bound_mono_s = frame.captured_mono_s
            binding.binding_state = BindingState.CANDIDATE
            if binding.confirmation_count >= self.config.binding_min_confirmations:
                binding.binding_state = BindingState.BOUND
                return "bound"
            return "candidate"

        if match.class_name == binding.class_name:
            binding.class_confidence = max(binding.class_confidence * 0.7, match.class_confidence)
            binding.confirmation_count += 1
            binding.switch_candidate = ""
            binding.switch_count = 0
            binding.binding_state = BindingState.BOUND
            return "confirmed"

        if binding.switch_candidate == match.class_name:
            binding.switch_count += 1
        else:
            binding.switch_candidate = match.class_name
            binding.switch_count = 1
        if binding.switch_count >= self.config.class_switch_confirmations:
            binding.class_name = match.class_name
            binding.class_confidence = match.class_confidence
            binding.switch_candidate = ""
            binding.switch_count = 0
            binding.binding_state = BindingState.BOUND
            return "class_switched"
        binding.binding_state = BindingState.STALE
        return "class_switch_pending"

    @staticmethod
    def _event(binding: VisualClassBinding, event: str, frame: ClassificationFrame) -> BindingEvent:
        return BindingEvent(
            track_key=binding.radar_track_key,
            side=binding.side,
            event=event,
            state=binding.binding_state.value,
            class_name=binding.class_name,
            frame_id=frame.frame_id,
            timestamp=frame.captured_mono_s,
        )

    def _clear(self, binding: VisualClassBinding, reason: str, frame: ClassificationFrame) -> BindingEvent:
        binding.binding_state = BindingState.CLEARED
        return self._event(binding, reason, frame)
