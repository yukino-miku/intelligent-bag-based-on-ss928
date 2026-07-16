from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class BoardEvent:
    event_type: str
    source: str
    payload: Mapping[str, Any]

    def to_jsonl(self) -> str:
        data = {"type": self.event_type, "source": self.source, **dict(self.payload)}
        return json.dumps(data, separators=(",", ":"), ensure_ascii=True)


def board_event_from_jsonl(line: str) -> BoardEvent:
    data = json.loads(line)
    if not isinstance(data, dict):
        raise ValueError("board event must be a JSON object")
    event_type = str(data.get("type") or "").strip()
    if not event_type:
        raise ValueError("board event requires type")
    source = str(data.get("source") or event_type.split("_", 1)[0])
    payload = {key: value for key, value in data.items() if key not in ("type", "source")}
    return BoardEvent(event_type, source, payload)
