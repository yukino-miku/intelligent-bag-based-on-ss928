from __future__ import annotations

import datetime as dt
import json
import re
import time
from pathlib import Path
from typing import Any, Mapping


from cloud_uploader import (
    build_fall_payload,
    build_hunch_reminder_payload,
    build_posture_payload,
    read_fresh_location,
)


# The Mini Program's “today” is China Standard Time.  The board itself runs
# in UTC, so deriving the daily document key from the process-local timezone
# makes the two sides request different calendar dates after 08:00 CST.
DAILY_TIMEZONE = dt.timezone(dt.timedelta(hours=8), name="CST")


def read_chip_temperature(path: str | Path = "/proc/Tsensor") -> dict[str, float] | None:
    try:
        text = Path(path).read_text(encoding="utf-8")
        values = {int(index): float(value) for index, value in re.findall(r"TSENSOR\[(\d+)\]\s+DATA:\s+(-?\d+(?:\.\d+)?)", text)}
        if not all(index in values for index in (0, 1, 2)):
            return None
        return {"tsensor0": values[0], "tsensor1": values[1], "tsensor2": values[2]}
    except OSError:
        return None


class PostureDailyAccumulator:
    def __init__(self, path: str | Path, max_gap_s: float = 10.0) -> None:
        self.path = Path(path)
        self.max_gap_s = max(0.1, float(max_gap_s))
        self.state = self._load()

    @staticmethod
    def _local_date(now_wall: float) -> str:
        return dt.datetime.fromtimestamp(float(now_wall), tz=DAILY_TIMEZONE).strftime("%Y-%m-%d")

    def _empty(self, date: str) -> dict[str, Any]:
        return {
            "device_id": "bag001",
            "date": date,
            "wearing_seconds": 0.0,
            "good_seconds": 0.0,
            "bad_seconds": 0.0,
            "updated_at": 0,
            "last_wall": None,
            "last_status": None,
        }

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("daily state is not an object")
            return data
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return self._empty("")

    def _can_relabel_utc_date(self, date: str) -> bool:
        """Preserve a running daily total written by the pre-CST implementation."""
        last_wall = self.state.get("last_wall")
        if last_wall is None:
            return False
        try:
            utc_date = dt.datetime.fromtimestamp(float(last_wall), tz=dt.timezone.utc).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OverflowError):
            return False
        return self.state.get("date") == utc_date and self._local_date(float(last_wall)) == date

    def update(self, posture_status: str, now_wall: float) -> dict[str, Any]:
        if posture_status not in ("good", "bad"):
            raise ValueError("posture_status must be good or bad")
        now_wall = float(now_wall)
        date = self._local_date(now_wall)
        if self.state.get("date") != date:
            if self._can_relabel_utc_date(date):
                self.state["date"] = date
            else:
                self.state = self._empty(date)

        last_wall = self.state.get("last_wall")
        last_status = self.state.get("last_status")
        if last_wall is not None and last_status in ("good", "bad"):
            elapsed = now_wall - float(last_wall)
            if 0.0 <= elapsed <= self.max_gap_s:
                self.state["wearing_seconds"] = float(self.state["wearing_seconds"]) + elapsed
                key = "good_seconds" if last_status == "good" else "bad_seconds"
                self.state[key] = float(self.state[key]) + elapsed

        self.state["last_wall"] = now_wall
        self.state["last_status"] = posture_status
        self.state["updated_at"] = int(round(now_wall * 1000.0))
        self._persist()
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return {
            "device_id": "bag001",
            "date": str(self.state.get("date", "")),
            "wearing_seconds": round(float(self.state.get("wearing_seconds", 0.0)), 3),
            "good_seconds": round(float(self.state.get("good_seconds", 0.0)), 3),
            "bad_seconds": round(float(self.state.get("bad_seconds", 0.0)), 3),
            "updated_at": int(self.state.get("updated_at", 0)),
        }

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(
            json.dumps(self.state, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(self.path)


class PostureCloudReporter:
    def __init__(
        self,
        telemetry_client: Any,
        accumulator: PostureDailyAccumulator,
        interval_s: float = 5.0,
        latest_location_path: str | Path = "/tmp/smartbag_latest_location.json",
        location_max_age_s: float = 120.0,
    ) -> None:
        self.telemetry_client = telemetry_client
        self.accumulator = accumulator
        self.interval_s = max(0.1, float(interval_s))
        self.latest_location_path = Path(latest_location_path)
        self.location_max_age_ms = int(max(0.0, float(location_max_age_s)) * 1000.0)
        self.next_upload_mono = 0.0

    def tick(
        self,
        state: Mapping[str, Any],
        hunch_active: bool,
        now_mono: float | None = None,
        now_wall: float | None = None,
    ) -> bool:
        now_mono = time.monotonic() if now_mono is None else float(now_mono)
        now_wall = time.time() if now_wall is None else float(now_wall)
        posture_status = "bad" if hunch_active else "good"
        daily = self.accumulator.update(posture_status, now_wall)
        if now_mono < self.next_upload_mono:
            return False
        snapshot = {
            "reportedAt": int(round(now_wall * 1000.0)),
            "posture_status": posture_status,
            "is_wearing": True,
            "reminder_active": bool(hunch_active),
            "rollDeg": state["roll_deg"],
            "pitchDeg": state["pitch_deg"],
            "yawDeg": state["yaw_deg"],
        }
        temperatures = read_chip_temperature()
        if temperatures is not None:
            snapshot["chip_temperature_c"] = temperatures
        payload = build_posture_payload(snapshot, daily)
        self.telemetry_client.submit_latest_status(payload)
        self.next_upload_mono = now_mono + self.interval_s
        return True

    def report_fall(self, event: Mapping[str, Any], now_ms: int | None = None) -> bool:
        if event.get("signal") != "FALL_ALARM" or event.get("alarmType") != "fall_detected":
            return False
        event_time_ms = int(
            now_ms
            if now_ms is not None
            else event.get("deviceTimestampMs") or round(time.time() * 1000.0)
        )
        location = read_fresh_location(
            self.latest_location_path,
            now_ms=event_time_ms,
            max_age_ms=self.location_max_age_ms,
        )
        return self.telemetry_client.upload_event_now(build_fall_payload(event, location))

    def report_hunch_reminder(self, state: Mapping[str, Any], reminder: Mapping[str, Any]) -> bool:
        payload = build_hunch_reminder_payload(state, reminder)
        self.telemetry_client.submit_event(payload)
        return True
