from __future__ import annotations

from dataclasses import dataclass


FRAME_HEAD = b"\xAA\xAA"
FRAME_TAIL = b"\x55\x55"
FRAME_SIZE = 14
OBJECT_STATUS_ID = 0x60A
OBJECT_GENERAL_ID = 0x60B


class MR20FrameError(ValueError):
    pass


@dataclass(frozen=True)
class MR20ObjectListStatus:
    target_count: int
    measurement_count: int


@dataclass(frozen=True)
class MR20Target:
    target_id: int
    longitudinal_distance_m: float
    lateral_distance_m: float
    longitudinal_velocity_mps: float
    lateral_velocity_mps: float
    status: str


@dataclass(frozen=True)
class MR20UnknownFrame:
    frame_id: int
    payload: bytes


def parse_mr20_frame(
    frame: bytes,
) -> MR20ObjectListStatus | MR20Target | MR20UnknownFrame:
    if len(frame) != FRAME_SIZE:
        raise MR20FrameError(f"MR20 frame must be {FRAME_SIZE} bytes, got {len(frame)}")
    if frame[:2] != FRAME_HEAD or frame[-2:] != FRAME_TAIL:
        raise MR20FrameError("invalid MR20 frame head or tail")
    frame_id = frame[2] | (frame[3] << 8)
    data = frame[4:12]
    if frame_id == OBJECT_STATUS_ID:
        return MR20ObjectListStatus(
            target_count=data[0],
            measurement_count=data[2] | (data[3] << 8),
        )
    if frame_id != OBJECT_GENERAL_ID:
        return MR20UnknownFrame(frame_id=frame_id, payload=data)

    statuses = {0: "stopped", 1: "oncoming", 2: "going", 3: "crossing"}
    return MR20Target(
        target_id=data[0],
        longitudinal_distance_m=round((data[1] * 32 + (data[2] >> 3)) * 0.1 - 500.0, 1),
        lateral_distance_m=round((((data[2] & 0x07) * 256 + data[3]) * 0.1) - 102.3, 1),
        longitudinal_velocity_mps=round(((data[4] << 2) + (data[5] >> 6)) * 0.25 - 128.0, 2),
        lateral_velocity_mps=round(((data[5] & 0x3F) * 8 + (data[6] >> 5)) * 0.25 - 64.0, 2),
        status=statuses.get(data[6] & 0x07, "unknown"),
    )

def parse_mr20_datagram(
    payload: bytes,
) -> tuple[MR20ObjectListStatus | MR20Target | MR20UnknownFrame, ...]:
    if not payload or len(payload) % FRAME_SIZE:
        raise MR20FrameError(
            f"MR20 UDP payload must contain complete {FRAME_SIZE}-byte frames, got {len(payload)}"
        )
    return tuple(
        parse_mr20_frame(payload[offset : offset + FRAME_SIZE])
        for offset in range(0, len(payload), FRAME_SIZE)
    )
