from dataclasses import dataclass


REPORT_HEAD = 0x5A
BSD_REPORT_TYPE = 0x07


@dataclass(frozen=True)
class RadarTarget:
    distance_m: int
    angle_deg: int
    velocity_mps: int
    target_id: int


@dataclass(frozen=True)
class RadarReport:
    report_type: int
    targets: list[RadarTarget]
    raw_payload: bytes


def _to_s8(value: int) -> int:
    return value - 256 if value & 0x80 else value


def _le_u16(data: bytes | bytearray, offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)


def parse_bsd_payload(payload: bytes) -> list[RadarTarget]:
    if len(payload) < 4:
        return []

    obj_num = _le_u16(payload, 0)
    available = (len(payload) - 4) // 4
    count = min(obj_num, available, 8)
    targets: list[RadarTarget] = []

    for idx in range(count):
        offset = 4 + idx * 4
        targets.append(
            RadarTarget(
                distance_m=_to_s8(payload[offset]),
                angle_deg=_to_s8(payload[offset + 1]),
                velocity_mps=_to_s8(payload[offset + 2]),
                target_id=_to_s8(payload[offset + 3]),
            )
        )

    return targets


class RadarStreamParser:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[RadarReport]:
        self._buffer.extend(data)
        reports: list[RadarReport] = []
        pos = 0

        while pos < len(self._buffer):
            if self._buffer[pos] != REPORT_HEAD:
                pos += 1
                continue

            if len(self._buffer) - pos < 4:
                break

            payload_len = self._buffer[pos + 1]
            if payload_len == 0:
                pos += 1
                continue

            frame_len = 2 + payload_len + 1
            if len(self._buffer) - pos < frame_len:
                break

            frame = self._buffer[pos : pos + frame_len]
            expected = sum(frame[:-1]) & 0xFF
            got = frame[-1]

            if expected != got:
                pos += 1
                continue

            report_type = frame[2]
            payload = bytes(frame[3:-1])
            reports.append(
                RadarReport(
                    report_type=report_type,
                    targets=parse_bsd_payload(payload) if report_type == BSD_REPORT_TYPE else [],
                    raw_payload=payload,
                )
            )
            pos += frame_len

        if pos:
            del self._buffer[:pos]

        return reports
