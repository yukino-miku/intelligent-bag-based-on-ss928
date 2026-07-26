"""Cumulative hunch reminder policy and the board-local controller handoff."""
from __future__ import annotations

import json
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Deque


class CumulativeHunchReminder:
    """Trigger once when 15 s of hunching occurs inside a 20 s rolling window."""

    def __init__(self, required_s: float = 15.0, window_s: float = 20.0) -> None:
        self.required_s = max(0.1, float(required_s))
        self.window_s = max(self.required_s, float(window_s))
        self._segments: Deque[tuple[float, float, bool]] = deque()
        self._last: tuple[float, bool] | None = None
        self._latched = False

    def update(self, is_hunched: bool, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else float(now)
        if self._last is not None:
            start, previous = self._last
            if now > start:
                self._segments.append((start, now, previous))
        self._last = (now, bool(is_hunched))
        cutoff = now - self.window_s
        while self._segments and self._segments[0][1] <= cutoff:
            self._segments.popleft()
        hunch_s = sum(max(0.0, end - max(start, cutoff)) for start, end, hunched in self._segments if hunched)
        if hunch_s >= self.required_s and not self._latched:
            self._latched = True
            return True
        # Require a meaningful recovery before another reminder can be issued.
        if hunch_s < self.required_s * 0.5:
            self._latched = False
        return False


def write_reminder_trigger(path: str | Path, *, now_wall: float | None = None) -> dict[str, object]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "type": "posture_hunch_reminder",
        "requestId": "hunch-" + uuid.uuid4().hex,
        "reportedAt": int(round((time.time() if now_wall is None else float(now_wall)) * 1000)),
        "durationS": 5,
        "audioClip": "bad",
    }
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(record, separators=(",", ":")), encoding="utf-8")
    temporary.replace(target)
    return record
