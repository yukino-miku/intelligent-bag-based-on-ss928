from __future__ import annotations

import math
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping


IMU_FALL_DIR = Path(__file__).resolve().parents[1] / "imu_fall_detector"
if str(IMU_FALL_DIR) not in sys.path:
    sys.path.insert(0, str(IMU_FALL_DIR))

from fall_fusion import (  # noqa: E402
    FallFusionConfig,
    FallFusionGate,
    event_to_json,
    read_recent_warning,
)
from imu_fall_detector import (  # noqa: E402
    DetectorConfig,
    FallImpactDetector,
    ImuSample,
    load_config,
)


STANDARD_GRAVITY = 9.80665


def to_detector_sample(sample: Any) -> ImuSample:
    """Convert board SI units to g and degrees per second."""
    return ImuSample(
        t=float(sample.t),
        ax=float(sample.ax) / STANDARD_GRAVITY,
        ay=float(sample.ay) / STANDARD_GRAVITY,
        az=float(sample.az) / STANDARD_GRAVITY,
        gx=math.degrees(float(sample.gx)),
        gy=math.degrees(float(sample.gy)),
        gz=math.degrees(float(sample.gz)),
    )


class FallFusionRuntime:
    def __init__(
        self,
        warning_marker: str | Path,
        fusion_config: FallFusionConfig | None = None,
        detector: FallImpactDetector | None = None,
        detector_config_path: str | None = None,
        alarm_log: str | Path | None = None,
        alarm_sink: Callable[[Mapping[str, Any]], None] | None = None,
        cloud_alarm_sink: Callable[[Mapping[str, Any]], Any] | None = None,
        call_alarm_sink: Callable[[Mapping[str, Any]], Any] | None = None,
        remote_thread_factory: Callable[..., Any] = threading.Thread,
        manual_trigger_path: str | Path | None = None,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.fusion_config = fusion_config or FallFusionConfig()
        if detector is None:
            detector_config = load_config(detector_config_path) if detector_config_path else DetectorConfig()
            detector_config.terminal_hold_s = max(
                detector_config.terminal_hold_s,
                self.fusion_config.recovery_window_s + 1.0,
            )
            detector = FallImpactDetector(detector_config)
        self.detector = detector
        self.gate = FallFusionGate(self.fusion_config)
        self.warning_marker = Path(warning_marker)
        self.alarm_log = Path(alarm_log) if alarm_log else None
        self.alarm_sink = alarm_sink or self._emit_alarm
        self.cloud_alarm_sink = cloud_alarm_sink
        self.call_alarm_sink = call_alarm_sink
        self.remote_thread_factory = remote_thread_factory
        self.manual_trigger_path = Path(manual_trigger_path) if manual_trigger_path else None
        self.wall_clock = wall_clock

    def update(self, sample: Any) -> dict[str, Any] | None:
        imu_sample = to_detector_sample(sample)
        imu_events = self.detector.update(imu_sample)
        now_wall = float(self.wall_clock())

        for event in imu_events:
            if event.get("event") != "fall_confirmed":
                continue
            warning = read_recent_warning(
                self.warning_marker,
                now_wall=now_wall,
                window_s=self.fusion_config.warning_window_s,
            )
            self.gate.start(event, warning, now_mono=imu_sample.t, now_wall=now_wall)

        posture_delta = float(self.detector.last_features.get("posture_delta_deg", 0.0))
        alarm = self.gate.update_motion(
            posture_delta,
            now_mono=imu_sample.t,
            now_wall=now_wall,
        )
        if alarm is not None:
            self._deliver_alarm(alarm)
        return alarm

    def consume_manual_trigger(self) -> dict[str, Any] | None:
        """Consume one BLE test request without changing normal fusion behavior."""
        if self.manual_trigger_path is None:
            return None
        try:
            request = json.loads(self.manual_trigger_path.read_text(encoding="utf-8"))
            self.manual_trigger_path.unlink()
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(request, dict) or request.get("type") != "manual_fall_trigger":
            return None
        now_wall = float(self.wall_clock())
        alarm = {
            "type": "fall_alarm",
            "alarmType": "fall_detected",
            "signal": "FALL_ALARM",
            "severity": "high",
            "ts": now_wall,
            "deviceTimestampMs": int(now_wall * 1000),
            "conditions": {"manual_ble_trigger": True},
            "evidence": {
                "source": "ble_remote",
                "requestId": str(request.get("requestId", "")),
                "requestedAt": request.get("ts"),
            },
        }
        self._deliver_alarm(alarm)
        return alarm

    def _deliver_alarm(self, alarm: Mapping[str, Any]) -> None:
        self.alarm_sink(alarm)
        if self.cloud_alarm_sink is None and self.call_alarm_sink is None:
            return
        worker = self.remote_thread_factory(
            target=lambda: self._deliver_remote_alarm(alarm),
            name="fall-upload-then-call",
            daemon=True,
        )
        worker.start()

    def _deliver_remote_alarm(self, alarm: Mapping[str, Any]) -> None:
        if self.cloud_alarm_sink is not None:
            try:
                uploaded = self.cloud_alarm_sink(alarm)
                if uploaded:
                    print("Fall cloud upload complete", flush=True)
            except Exception as exc:
                print(
                    f"WARN fall cloud upload failed: {type(exc).__name__}",
                    file=sys.stderr,
                    flush=True,
                )
        if self.call_alarm_sink is not None:
            try:
                self.call_alarm_sink(alarm)
            except Exception as exc:
                print(
                    f"WARN fall call failed: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )

    def _emit_alarm(self, event: Mapping[str, Any]) -> None:
        payload = event_to_json(event)
        print(payload, flush=True)
        if self.alarm_log is None:
            return
        self.alarm_log.parent.mkdir(parents=True, exist_ok=True)
        with self.alarm_log.open("a", encoding="utf-8") as file:
            file.write(payload + "\n")
