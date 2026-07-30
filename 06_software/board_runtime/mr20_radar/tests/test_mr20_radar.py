from __future__ import annotations

import json
import socket
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from mr20_radar import (  # noqa: E402
    MR20FrameError,
    MR20ObjectListStatus,
    MR20Target,
    RadarConfig,
    RadarRiskEvaluator,
    RadarScan,
    RiskConfig,
    MR20RadarWorker,
    MR20ScanAssembler,
    load_radar_configs,
    parse_mr20_frame,
)


def frame(frame_id: bytes, payload: bytes) -> bytes:
    return b"\xAA\xAA" + frame_id + payload + b"\x55\x55"


class MR20ParserTest(unittest.TestCase):
    def test_parses_official_target_example_with_canonical_axes(self) -> None:
        target = parse_mr20_frame(frame(b"\x0B\x06", bytes((0x57, 0x9D, 0x34, 0x1D, 0x47, 0xA0, 0x02, 0x00))))

        self.assertIsInstance(target, MR20Target)
        assert isinstance(target, MR20Target)
        self.assertEqual(target.target_id, 87)
        self.assertEqual(target.longitudinal_distance_m, 3.0)
        self.assertEqual(target.lateral_distance_m, 3.0)
        self.assertEqual(target.longitudinal_velocity_mps, -56.5)
        self.assertEqual(target.lateral_velocity_mps, 0.0)
        self.assertEqual(target.status, "going")

    def test_parses_object_list_status_and_rejects_invalid_frames(self) -> None:
        status = parse_mr20_frame(frame(b"\x0A\x06", bytes((2, 0, 0x34, 0x12, 0, 0, 0, 0))))
        self.assertEqual(status, MR20ObjectListStatus(target_count=2, measurement_count=0x1234))
        with self.assertRaises(MR20FrameError):
            parse_mr20_frame(b"\xAA\xAA\x0B")
        with self.assertRaises(MR20FrameError):
            parse_mr20_frame(frame(b"\x01\x06", bytes(8)))


class MR20RiskEvaluatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = RadarConfig(
            name="right_rear", side="right", bind_host="127.0.0.1", port=2368, radar_ip="127.0.0.1",
            lateral_min_m=-3.0, lateral_max_m=3.0, longitudinal_min_m=0.2, longitudinal_max_m=20.0,
            approaching_velocity_sign=-1, min_consecutive_frames=2, log_path="/tmp/mr20-test.jsonl",
        )
        self.risk = RiskConfig(levels=((1, 8.0, 12.0, 1.0), (2, 5.0, 8.0, 2.0), (3, 3.0, 5.0, 3.0), (4, 1.5, 3.0, 4.0)))

    def target(self, distance: float, velocity: float, lateral: float = 0.5) -> MR20Target:
        return MR20Target(7, distance, lateral, velocity, 0.0, "oncoming")

    def test_two_frames_are_required_then_ttc_selects_level(self) -> None:
        evaluator = RadarRiskEvaluator(self.config, self.risk)
        dangerous = self.target(4.0, -3.0)
        self.assertEqual(evaluator.evaluate([dangerous])[0], 0)
        level, target, ttc = evaluator.evaluate([dangerous])
        self.assertEqual(level, 3)
        self.assertEqual(target, dangerous)
        self.assertEqual(ttc, 1.33)

    def test_ignores_departing_and_out_of_lane_targets(self) -> None:
        evaluator = RadarRiskEvaluator(self.config, self.risk)
        self.assertEqual(evaluator.evaluate([self.target(2.0, 4.0)])[0], 0)
        self.assertEqual(evaluator.evaluate([self.target(2.0, -6.0, lateral=4.0)])[0], 0)

    def test_receiver_filters_non_radar_source_ip(self) -> None:
        worker = MR20RadarWorker(self.config, self.risk, lambda _event: None)
        self.assertTrue(worker.accepts_source("127.0.0.1"))
        self.assertFalse(worker.accepts_source("127.0.0.2"))

    def test_worker_aggregates_60a_target_lists_before_emitting(self) -> None:
        events = []
        with tempfile.TemporaryDirectory() as temp_dir:
            worker = MR20RadarWorker(
                replace(self.config, log_path=str(Path(temp_dir) / "mr20.jsonl")),
                self.risk,
                events.append,
            )
            target = self.target(4.0, -3.0)
            status = MR20ObjectListStatus(target_count=1, measurement_count=1)
            worker._handle_message(status, "127.0.0.1")
            worker._handle_message(target, "127.0.0.1")
            worker._handle_message(replace(status, measurement_count=2), "127.0.0.1")
            worker._handle_message(target, "127.0.0.1")

            self.assertEqual([event.level for event in events], [0, 3])
            self.assertTrue((Path(temp_dir) / "mr20.jsonl").exists())

    def test_worker_exposes_every_target_in_complete_scan(self) -> None:
        scans = []
        with tempfile.TemporaryDirectory() as temp_dir:
            worker = MR20RadarWorker(
                replace(self.config, log_path=str(Path(temp_dir) / "mr20.jsonl")),
                self.risk,
                on_scan=scans.append,
            )
            worker._handle_message(MR20ObjectListStatus(target_count=2, measurement_count=44), "127.0.0.1")
            worker._handle_message(self.target(8.0, -2.0), "127.0.0.1")
            worker._handle_message(replace(self.target(5.0, -3.0), target_id=8), "127.0.0.1")

            self.assertEqual(1, len(scans))
            self.assertIsInstance(scans[0], RadarScan)
            self.assertEqual(44, scans[0].measurement_count)
            self.assertEqual({7, 8}, {target.target_id for target in scans[0].targets})
            self.assertTrue(all(target.radar_name == "right_rear" for target in scans[0].targets))
            self.assertEqual(scans[0], worker.get_scan())

    def test_fusion_worker_can_disable_legacy_risk_evaluation(self) -> None:
        scans = []
        events = []
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "mr20.jsonl"
            worker = MR20RadarWorker(
                replace(self.config, log_path=str(log_path)),
                self.risk,
                events.append,
                on_scan=scans.append,
                evaluate_legacy_risk=False,
            )
            worker._handle_message(MR20ObjectListStatus(target_count=1, measurement_count=9), "127.0.0.1")
            worker._handle_message(self.target(2.0, -6.0), "127.0.0.1")

            record = json.loads(log_path.read_text(encoding="utf-8"))
            self.assertIsNone(worker.evaluator)
            self.assertEqual(1, len(scans))
            self.assertEqual([0], [event.level for event in events])
            self.assertFalse(record["legacy_evaluation_enabled"])

    def test_worker_reports_udp_bind_failure_in_health_status(self) -> None:
        blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        blocker.bind(("127.0.0.1", 0))
        port = blocker.getsockname()[1]
        worker = MR20RadarWorker(replace(self.config, port=port), self.risk, evaluate_legacy_risk=False)
        try:
            worker.start()
            deadline = time.monotonic() + 1.0
            while worker.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            health = worker.health_status()
            self.assertFalse(health["worker_alive"])
            self.assertIn("Error", health["worker_last_error"])
        finally:
            worker.stop()
            blocker.close()


class MR20ScanAssemblerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.assembler = MR20ScanAssembler("left_rear", "left", timeout_s=0.1, max_targets=4)

    @staticmethod
    def target(identifier: int) -> MR20Target:
        return MR20Target(identifier, 5.0, 0.0, -1.0, 0.0, "oncoming")

    def test_zero_target_scan_is_complete(self) -> None:
        scans = self.assembler.push(MR20ObjectListStatus(0, 10), 1.0)
        self.assertEqual(1, len(scans))
        self.assertTrue(scans[0].complete)
        self.assertEqual("zero_target_scan", scans[0].completion_reason)

    def test_next_status_flushes_incomplete_scan_without_hiding_received_targets(self) -> None:
        self.assembler.push(MR20ObjectListStatus(2, 20), 2.0)
        self.assembler.push(self.target(1), 2.01)
        scans = self.assembler.push(MR20ObjectListStatus(1, 21), 2.05)
        self.assertEqual(1, len(scans))
        self.assertFalse(scans[0].complete)
        self.assertEqual(1, scans[0].unique_target_count)
        self.assertEqual(1, scans[0].missing_target_count)

    def test_duplicate_target_and_timeout_are_reported(self) -> None:
        self.assembler.push(MR20ObjectListStatus(2, 30), 3.0)
        self.assembler.push(self.target(1), 3.01)
        self.assembler.push(self.target(1), 3.02)
        scans = self.assembler.flush_timeout(3.11)
        self.assertEqual(1, len(scans))
        self.assertFalse(scans[0].complete)
        self.assertEqual(2, scans[0].received_target_count)
        self.assertEqual(1, scans[0].duplicate_target_count)
        self.assertEqual(1, self.assembler.statistics.scan_timeouts)

    def test_measurement_sequence_gap_is_recorded(self) -> None:
        self.assembler.push(MR20ObjectListStatus(0, 40), 4.0)
        scan = self.assembler.push(MR20ObjectListStatus(0, 43), 4.1)[0]
        self.assertEqual(2, scan.measurement_sequence_gap)
        self.assertFalse(scan.complete)
        self.assertEqual("measurement_sequence_gap", scan.completion_reason)
        self.assertEqual(2, self.assembler.statistics.sequence_gaps)

    def test_orphan_and_excessive_target_count_are_not_normal_scans(self) -> None:
        orphan = self.assembler.push(self.target(1), 5.0)
        self.assertEqual(1, len(orphan))
        self.assertFalse(orphan[0].complete)
        self.assertEqual("orphan_target_frame", orphan[0].completion_reason)
        self.assertEqual(1, orphan[0].unique_target_count)
        scans = self.assembler.push(MR20ObjectListStatus(8, 50), 5.1)
        self.assertFalse(scans[0].complete)
        self.assertEqual("target_count_exceeds_limit", scans[0].completion_reason)
        self.assertEqual(1, self.assembler.statistics.orphan_target_frames)


class MR20DualRadarConfigTest(unittest.TestCase):
    def test_example_config_keeps_left_and_right_ports_independent(self) -> None:
        config_path = PROJECT_DIR / "config.example.json"
        radars, _risk = load_radar_configs(config_path)

        endpoints = {
            radar.name: (radar.side, radar.bind_host, radar.port, radar.radar_ip)
            for radar in radars
        }
        self.assertEqual(
            endpoints,
            {
                "right_rear": ("right", "0.0.0.0", 2368, "192.168.1.200"),
                "left_rear": ("left", "0.0.0.0", 2378, "192.168.1.201"),
            },
        )


if __name__ == "__main__":
    unittest.main()
