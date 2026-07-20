from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


RUNTIME_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RUNTIME_DIR))

from mr20_radar import (  # noqa: E402
    MR20FrameError,
    MR20ObjectListStatus,
    MR20RadarWorker,
    MR20Target,
    MR20UnknownFrame,
    RadarConfig,
    RadarRiskConfig,
    parse_mr20_frame,
)
from mr20_radar.mr20_replay import replay_hex_lines  # noqa: E402


def frame(frame_id: int, payload: bytes) -> bytes:
    return b"\xaa\xaa" + frame_id.to_bytes(2, "little") + payload + b"\x55\x55"


class MR20ProtocolTest(unittest.TestCase):
    def test_official_target_example_and_status(self) -> None:
        target = parse_mr20_frame(
            frame(0x60B, bytes((0x57, 0x9D, 0x34, 0x1D, 0x47, 0xA0, 0x02, 0x00)))
        )
        self.assertEqual(
            MR20Target(87, 3.0, 3.0, -56.5, 0.0, "going"), target
        )
        self.assertEqual(
            MR20ObjectListStatus(2, 0x1234),
            parse_mr20_frame(frame(0x60A, bytes((2, 0, 0x34, 0x12, 0, 0, 0, 0)))),
        )

    def test_unknown_frame_is_countable_and_invalid_frame_rejected(self) -> None:
        unknown = parse_mr20_frame(frame(0x201, bytes(8)))
        self.assertEqual(MR20UnknownFrame(0x201, bytes(8)), unknown)
        with self.assertRaises(MR20FrameError):
            parse_mr20_frame(b"\xaa\xaa")


class MR20WorkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = RadarConfig(
            name="right_rear", side="right", bind_host="127.0.0.1", bind_port=2368,
            source_ip="192.168.1.200", source_port=2369,
            lateral_min_m=-3.1, lateral_max_m=3.1,
            longitudinal_min_m=0.2, longitudinal_max_m=20.0,
            approaching_velocity_sign=-1, min_consecutive_frames=2, timeout_s=1.0,
        )
        self.risk = RadarRiskConfig(
            levels=((1, 8.0, 12.0, 1.0), (2, 5.0, 8.0, 2.0), (3, 3.0, 5.0, 3.0), (4, 1.5, 3.0, 4.0))
        )

    def test_source_ip_and_port_are_both_checked(self) -> None:
        worker = MR20RadarWorker(self.config, self.risk, lambda event: None)
        self.assertTrue(worker.accepts_source("192.168.1.200", 2369))
        self.assertFalse(worker.accepts_source("192.168.1.201", 2369))
        self.assertFalse(worker.accepts_source("192.168.1.200", 2368))

    def test_replay_requires_two_scans_then_emits_source_scoped_level(self) -> None:
        events = []
        worker = MR20RadarWorker(self.config, self.risk, events.append, clock=lambda: 123.0)
        fixture = Path(__file__).parent / "fixtures" / "official-example.hex"
        replay_hex_lines(worker, fixture)
        self.assertEqual([0, 4], [event.level for event in events])
        self.assertEqual("radar:right_rear", events[-1].source)
        self.assertEqual("right", events[-1].side)
        self.assertEqual("87", events[-1].source_id)
        self.assertEqual(2, worker.status()["status_60a_count"])
        self.assertEqual(2, worker.status()["target_60b_count"])

    def test_departing_or_out_of_lane_target_does_not_warn(self) -> None:
        worker = MR20RadarWorker(self.config, self.risk, lambda event: None)
        departing = MR20Target(1, 2.0, 0.0, 5.0, 0.0, "going")
        outside = replace(departing, target_id=2, lateral_distance_m=4.0, longitudinal_velocity_mps=-5.0)
        self.assertEqual(0, worker.evaluator.evaluate([departing, outside])[0])

    def test_unknown_and_rejected_sources_are_counted(self) -> None:
        worker = MR20RadarWorker(self.config, self.risk, lambda event: None)
        worker.handle_datagram(frame(0x201, bytes(8)), ("192.168.1.200", 2369))
        worker.handle_datagram(frame(0x201, bytes(8)), ("192.168.1.200", 9999))
        self.assertEqual(1, worker.status()["unknown_frame_count"])
        self.assertEqual(1, worker.status()["rejected_source_count"])


if __name__ == "__main__":
    unittest.main()
