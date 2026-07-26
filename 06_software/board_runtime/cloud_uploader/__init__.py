"""Shared CloudBase telemetry helpers for SmartBag board processes."""

from .telemetry_client import (
    TelemetryClient,
    build_fall_payload,
    build_hunch_reminder_payload,
    build_posture_payload,
    build_track_payload,
    read_fresh_location,
    write_latest_location,
)

__all__ = [
    "TelemetryClient",
    "build_fall_payload",
    "build_hunch_reminder_payload",
    "build_posture_payload",
    "build_track_payload",
    "read_fresh_location",
    "write_latest_location",
]
