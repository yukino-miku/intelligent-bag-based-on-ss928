from __future__ import annotations

from dataclasses import dataclass, replace

from risk_model import RiskAssessment, RiskLevel, warning_action_for_level


@dataclass(frozen=True)
class RiskWarningStabilizerConfig:
    min_confirm_frames_attention: int = 1
    min_confirm_frames_caution: int = 2
    min_confirm_frames_danger: int = 3
    min_confirm_frames_emergency: int = 2
    low_quality_extra_frames: int = 1
    low_quality_threshold: float = 0.55
    high_quality_fast_path_threshold: float = 0.80
    emergency_fast_path_ttc_s: float = 0.80
    emergency_fast_path_distance_m: float = 0.80
    downgrade_hold_frames: int = 2
    low_conflict_consistency_threshold: float = 0.50
    low_approach_consistency_threshold: float = 0.50
    low_conflict_extra_frames: int = 2


@dataclass(frozen=True)
class StabilizerDebugInfo:
    pending_level: RiskLevel = RiskLevel.SAFE
    pending_count: int = 0
    required_frames: int = 0
    reason: str = "none"


@dataclass
class _RiskDisplayState:
    displayed_level: RiskLevel = RiskLevel.SAFE
    displayed_score: float = 0.0
    pending_level: RiskLevel = RiskLevel.SAFE
    pending_count: int = 0
    downgrade_count: int = 0


class RiskWarningStabilizer:
    def __init__(self, config: RiskWarningStabilizerConfig | None = None, min_warning_frames: int | None = None) -> None:
        if config is None and min_warning_frames is not None:
            config = RiskWarningStabilizerConfig(
                min_confirm_frames_attention=max(1, min_warning_frames),
                min_confirm_frames_caution=max(1, min_warning_frames),
                min_confirm_frames_danger=max(1, min_warning_frames),
                min_confirm_frames_emergency=max(1, min_warning_frames),
            )
        self.config = config or RiskWarningStabilizerConfig()
        self._state_by_track_id: dict[int | str, _RiskDisplayState] = {}
        self._debug_by_track_id: dict[int | str, StabilizerDebugInfo] = {}

    def stabilize(
        self,
        risk_by_track_id: dict[int | str, RiskAssessment],
        tracked_objects_by_id: dict[int | str, object] | None = None,
    ) -> dict[int | str, RiskAssessment]:
        tracked_objects_by_id = tracked_objects_by_id or {}
        stabilized: dict[int | str, RiskAssessment] = {}
        active_track_ids = set(risk_by_track_id)
        for track_id, assessment in risk_by_track_id.items():
            state = self._state_by_track_id.setdefault(track_id, _RiskDisplayState())
            target = tracked_objects_by_id.get(track_id)
            observation_quality = float(getattr(target, "observation_quality", 1.0))
            if self._is_fast_path(assessment, target):
                state.displayed_level = assessment.level
                state.displayed_score = assessment.score
                state.pending_level = assessment.level
                state.pending_count = 0
                state.downgrade_count = 0
                debug = StabilizerDebugInfo(assessment.level, 0, 1, "fast_path")
                display = self._assessment_with_display_level(assessment, assessment.level, assessment.score)
            elif assessment.level > state.displayed_level:
                display, debug = self._handle_upgrade(state, assessment, observation_quality, target)
            elif assessment.level < state.displayed_level:
                display, debug = self._handle_downgrade(state, assessment)
            else:
                state.displayed_level = assessment.level
                state.displayed_score = assessment.score
                state.pending_level = assessment.level
                state.pending_count = 0
                state.downgrade_count = 0
                display = self._assessment_with_display_level(assessment, assessment.level, assessment.score)
                debug = StabilizerDebugInfo(assessment.level, 0, 0, "same_level")
            self._debug_by_track_id[track_id] = debug
            stabilized[track_id] = display

        for track_id in list(self._state_by_track_id):
            if track_id not in active_track_ids:
                del self._state_by_track_id[track_id]
                self._debug_by_track_id.pop(track_id, None)
        return stabilized

    def debug_info_by_track_id(self) -> dict[int | str, StabilizerDebugInfo]:
        return dict(self._debug_by_track_id)

    def clear_tracks(self, track_ids: set[int | str] | tuple[int | str, ...]) -> None:
        for track_id in track_ids:
            self._state_by_track_id.pop(track_id, None)
            self._debug_by_track_id.pop(track_id, None)

    def _handle_upgrade(self, state, assessment, observation_quality, target):
        if state.pending_level != assessment.level:
            state.pending_level = assessment.level
            state.pending_count = 1
        else:
            state.pending_count += 1
        state.downgrade_count = 0
        required_frames = self._required_confirm_frames(assessment, observation_quality, target)
        if state.pending_count >= required_frames:
            state.displayed_level = assessment.level
            state.displayed_score = assessment.score
            return (
                self._assessment_with_display_level(assessment, assessment.level, assessment.score),
                StabilizerDebugInfo(assessment.level, state.pending_count, required_frames, "upgraded"),
            )
        return (
            self._display_assessment_from_state(assessment, state),
            StabilizerDebugInfo(assessment.level, state.pending_count, required_frames, "waiting_confirmation"),
        )

    def _handle_downgrade(self, state, assessment):
        state.pending_level = assessment.level
        state.pending_count = 0
        state.downgrade_count += 1
        if state.downgrade_count >= self.config.downgrade_hold_frames:
            state.downgrade_count = 0
            state.displayed_level = RiskLevel(max(int(state.displayed_level) - 1, int(assessment.level)))
            state.displayed_score = max(assessment.score, risk_score_for_display_level(state.displayed_level))
            reason = "downgraded"
        else:
            reason = "holding_downgrade"
        return (
            self._display_assessment_from_state(assessment, state),
            StabilizerDebugInfo(assessment.level, state.downgrade_count, self.config.downgrade_hold_frames, reason),
        )

    def _required_confirm_frames(self, assessment: RiskAssessment, observation_quality: float, target=None) -> int:
        if assessment.level <= RiskLevel.ATTENTION:
            frames = self.config.min_confirm_frames_attention
        elif assessment.level == RiskLevel.CAUTION:
            frames = self.config.min_confirm_frames_caution
        elif assessment.level == RiskLevel.DANGER:
            frames = self.config.min_confirm_frames_danger
        else:
            frames = self.config.min_confirm_frames_emergency
        if assessment.level > RiskLevel.ATTENTION and observation_quality < self.config.low_quality_threshold:
            frames += self.config.low_quality_extra_frames
        if assessment.level > RiskLevel.ATTENTION:
            approach_consistency = float(getattr(target, "approach_consistency", 1.0))
            path_consistency = float(getattr(target, "path_conflict_consistency", 1.0))
            if not assessment.path_conflict or (
                approach_consistency < self.config.low_approach_consistency_threshold
                and path_consistency < self.config.low_conflict_consistency_threshold
            ):
                frames += self.config.low_conflict_extra_frames
        return max(1, frames)

    def _is_fast_path(self, assessment: RiskAssessment, target) -> bool:
        distance_m = getattr(target, "distance_m", None)
        quality = float(getattr(target, "observation_quality", 0.0))
        inside = distance_m is not None and distance_m <= self.config.emergency_fast_path_distance_m
        stable = (
            assessment.path_conflict
            and float(getattr(target, "approach_consistency", 0.0)) >= self.config.low_approach_consistency_threshold
            and float(getattr(target, "path_conflict_consistency", 0.0)) >= self.config.low_conflict_consistency_threshold
        )
        short_ttc = assessment.ttc_s is not None and assessment.ttc_s <= self.config.emergency_fast_path_ttc_s
        short_cpa = (
            assessment.cpa_time_s is not None
            and assessment.cpa_distance_m is not None
            and assessment.cpa_time_s <= self.config.emergency_fast_path_ttc_s
            and assessment.cpa_distance_m <= self.config.emergency_fast_path_distance_m
        )
        return assessment.level >= RiskLevel.EMERGENCY and (
            inside or (stable and quality >= self.config.high_quality_fast_path_threshold and (short_ttc or short_cpa))
        )

    @staticmethod
    def _assessment_with_display_level(assessment, display_level, display_score):
        haptic_level = RiskLevel.SAFE if display_level <= RiskLevel.SAFE else RiskLevel(
            min(int(assessment.haptic_level), int(display_level))
        )
        return replace(
            assessment,
            score=display_score,
            level=display_level,
            visual_level=display_level,
            haptic_level=haptic_level,
            warning_action=warning_action_for_level(haptic_level),
        )

    @classmethod
    def _display_assessment_from_state(cls, assessment, state):
        if state.displayed_level <= RiskLevel.SAFE:
            return cls._assessment_with_display_level(assessment, RiskLevel.SAFE, 0.0)
        score = max(state.displayed_score, risk_score_for_display_level(state.displayed_level))
        return cls._assessment_with_display_level(assessment, state.displayed_level, score)


def risk_score_for_display_level(level: RiskLevel) -> float:
    return {
        RiskLevel.SAFE: 0.0,
        RiskLevel.ATTENTION: 0.40,
        RiskLevel.CAUTION: 0.60,
        RiskLevel.DANGER: 0.70,
        RiskLevel.EMERGENCY: 0.80,
    }[level]
