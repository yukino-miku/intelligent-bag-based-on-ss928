from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Iterable, TextIO


@dataclass(frozen=True)
class AlertCandidate:
    side: str
    level: int
    score: float
    track_id: int


class AlertJsonlEmitter:
    """Emit stabilized haptic alerts while keeping stdout machine-readable."""

    VALID_SIDES = ("left", "right")

    def __init__(
        self,
        stream: TextIO,
        fixed_side: str = "auto",
        min_level: int = 1,
        rate_limit_s: float = 0.25,
        dead_zone_m: float = 0.35,
        center_mode: str = "both",
        clock=time.monotonic,
    ) -> None:
        if fixed_side not in ("auto", "left", "right"):
            raise ValueError(f"unsupported alert side mode: {fixed_side}")
        if center_mode not in ("both", "strongest", "left", "right"):
            raise ValueError(f"unsupported center side mode: {center_mode}")
        if not 0 <= int(min_level) <= 4:
            raise ValueError("alert min level must be 0..4")
        self.stream = stream
        self.fixed_side = fixed_side
        self.min_level = int(min_level)
        self.rate_limit_s = max(0.0, float(rate_limit_s))
        self.dead_zone_m = max(0.0, float(dead_zone_m))
        self.center_mode = center_mode
        self.clock = clock
        self._last_level = {side: 0 for side in self.VALID_SIDES}
        self._last_emit_s = {side: float("-inf") for side in self.VALID_SIDES}

    def update(self, targets: Iterable[object], risks_by_track_id: dict[int, object]) -> list[dict[str, object]]:
        best = {side: None for side in self.VALID_SIDES}
        for target in targets:
            risk = risks_by_track_id.get(int(getattr(target, "track_id")))
            if risk is None:
                continue
            haptic_level = getattr(risk, "haptic_level", None)
            level = int(getattr(haptic_level, "value", haptic_level or 0))
            if level < self.min_level:
                continue
            score = float(getattr(risk, "score", 0.0))
            candidate = AlertCandidate("", level, score, int(getattr(target, "track_id")))
            for side in self._sides_for_target(target):
                current = best[side]
                if current is None or (candidate.level, candidate.score) > (current.level, current.score):
                    best[side] = AlertCandidate(side, level, score, candidate.track_id)

        now_s = float(self.clock())
        emitted: list[dict[str, object]] = []
        for side in self.VALID_SIDES:
            candidate = best[side]
            if candidate is None:
                if self._last_level[side] != 0:
                    emitted.append(self._emit(side, 0, 0.0, -1, now_s))
                continue
            level_changed = candidate.level != self._last_level[side]
            rate_ready = now_s - self._last_emit_s[side] >= self.rate_limit_s
            if level_changed or rate_ready:
                emitted.append(self._emit(side, candidate.level, candidate.score, candidate.track_id, now_s))
        return emitted

    def clear_all(self) -> list[dict[str, object]]:
        now_s = float(self.clock())
        emitted: list[dict[str, object]] = []
        for side in self.VALID_SIDES:
            if self._last_level[side] != 0:
                emitted.append(self._emit(side, 0, 0.0, -1, now_s))
        return emitted

    def _sides_for_target(self, target: object) -> tuple[str, ...]:
        if self.fixed_side in self.VALID_SIDES:
            return (self.fixed_side,)
        ground_point = getattr(target, "ground_point", None)
        x_m = float(getattr(ground_point, "x_m", 0.0)) if ground_point is not None else 0.0
        if x_m < -self.dead_zone_m:
            return ("left",)
        if x_m > self.dead_zone_m:
            return ("right",)
        if self.center_mode == "both":
            return self.VALID_SIDES
        if self.center_mode in self.VALID_SIDES:
            return (self.center_mode,)
        return ("left",) if self._last_level["left"] >= self._last_level["right"] else ("right",)

    def _emit(self, side: str, level: int, score: float, track_id: int, now_s: float) -> dict[str, object]:
        payload: dict[str, object] = {
            "type": "vision_alert",
            "side": side,
            "level": int(level),
            "score": round(float(score), 4),
            "track_id": int(track_id),
            "ts": round(now_s, 6),
        }
        self.stream.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n")
        self.stream.flush()
        self._last_level[side] = int(level)
        self._last_emit_s[side] = now_s
        return payload
