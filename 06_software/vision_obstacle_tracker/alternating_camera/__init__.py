"""Experimental time-multiplexed USB camera runtime for SS928."""

from .scheduler import (
    AlternatingCaptureConfig,
    AlternatingV4l2Capture,
    CapturedFrame,
    SliceResult,
    SwitchEvent,
)
from .session import AlternatingSessionRecorder
from .v4l2_capture import NegotiatedFormat, V4l2MjpegDevice

__all__ = [
    "AlternatingCaptureConfig",
    "AlternatingSessionRecorder",
    "AlternatingV4l2Capture",
    "CapturedFrame",
    "NegotiatedFormat",
    "SliceResult",
    "SwitchEvent",
    "V4l2MjpegDevice",
]
