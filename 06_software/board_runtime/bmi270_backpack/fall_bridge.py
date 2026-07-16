from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


FALL_MODULE_DIR = Path(__file__).resolve().parents[1] / "imu_fall_detector"
if str(FALL_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(FALL_MODULE_DIR))

from imu_fall_detector import DetectorConfig, FallImpactDetector, ImuSample, event_to_json


class FallEventBridge:
    """Convert BMI270 samples directly into fall-detector samples without text parsing."""

    def __init__(self, sample_hz: float = 50.0) -> None:
        self.detector = FallImpactDetector(DetectorConfig(sample_hz=float(sample_hz)))

    @staticmethod
    def convert(sample: Any) -> ImuSample:
        return ImuSample(
            t=float(sample.t),
            ax=float(sample.ax),
            ay=float(sample.ay),
            az=float(sample.az),
            gx=float(sample.gx),
            gy=float(sample.gy),
            gz=float(sample.gz),
        )

    def update_jsonl(self, sample: Any) -> list[str]:
        return [event_to_json(event) for event in self.detector.update(self.convert(sample))]
