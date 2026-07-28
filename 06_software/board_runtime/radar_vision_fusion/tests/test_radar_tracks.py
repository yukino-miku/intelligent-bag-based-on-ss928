from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

BOARD_RUNTIME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BOARD_RUNTIME))

from mr20_radar.mr20_radar import MR20Target, RadarConfig, RadarScan  # noqa: E402
from radar_vision_fusion.radar_tracks import RadarTrackManager, RadarTrackManagerConfig  # noqa: E402


def radar_config(name: str = "left_rear", side: str = "left", **changes) -> RadarConfig:
    base = RadarConfig(
        name=name, side=side, bind_host="0.0.0.0", port=2368, radar_ip="192.0.2.1",
        lateral_min_m=-10.0, lateral_max_m=10.0, longitudinal_min_m=0.0, longitudinal_max_m=30.0,
        approaching_velocity_sign=-1, min_consecutive_frames=2, log_path="unused.jsonl",
    )
    return replace(base, **changes)


def target(target_id: int, x: float, z: float, vx: float = 0.0, vz: float = -1.0) -> MR20Target:
    return MR20Target(target_id, z, x, vz, vx, "oncoming")


def scan(config: RadarConfig, count: int, now: float, *targets: MR20Target) -> RadarScan:
    return RadarScan(config.name, config.side, count, now, tuple(targets))


class RadarTrackManagerTest(unittest.TestCase):
    def test_scan_preserves_multiple_targets_and_sides_are_independent(self) -> None:
        manager = RadarTrackManager()
        left = radar_config()
        right = radar_config("right_rear", "right")
        manager.update(scan(left, 1, 1.0, target(1, -1.0, 8.0), target(2, 0.2, 4.0)), left)
        manager.update(scan(right, 1, 1.0, target(1, 1.0, 7.0)), right)
        self.assertEqual(3, len(manager.active_tracks()))
        self.assertEqual(2, len(manager.active_tracks("left")))
        self.assertEqual(1, len(manager.active_tracks("right")))

    def test_timeout_then_reused_target_id_gets_new_generation(self) -> None:
        manager = RadarTrackManager(RadarTrackManagerConfig(radar_track_timeout_s=0.5, radar_max_missed_scans=2))
        config = radar_config()
        first, _ = manager.update(scan(config, 1, 1.0, target(7, 0.0, 6.0)), config)
        first_key = first[0].track_key
        manager.update(scan(config, 2, 1.1), config)
        _active, removed = manager.update(scan(config, 3, 1.2), config)
        self.assertIn(first_key, removed)
        second, _ = manager.update(scan(config, 4, 2.0, target(7, 0.0, 6.0)), config)
        self.assertNotEqual(first_key, second[0].track_key)
        self.assertEqual(2, second[0].generation)

    def test_same_target_persists_and_accumulates_bounded_history(self) -> None:
        manager = RadarTrackManager(RadarTrackManagerConfig(history_size=3))
        config = radar_config()
        keys = []
        for count in range(1, 6):
            tracks, _ = manager.update(scan(config, count, count * 0.1, target(3, 0.0, 7.0 - count * 0.1)), config)
            keys.append(tracks[0].track_key)
        current = manager.active_tracks()[0]
        self.assertEqual(1, len(set(keys)))
        self.assertEqual(5, current.age_scans)
        self.assertEqual(3, len(current.position_history))
        self.assertLess(current.distance_trend_mps, 0.0)

    def test_target_is_retained_until_miss_limit(self) -> None:
        manager = RadarTrackManager(RadarTrackManagerConfig(radar_track_timeout_s=10.0, radar_max_missed_scans=3))
        config = radar_config()
        first, _ = manager.update(scan(config, 1, 1.0, target(4, 0.0, 6.0)), config)
        track_key = first[0].track_key
        manager.update(scan(config, 2, 1.1), config)
        manager.update(scan(config, 3, 1.2), config)
        self.assertIsNotNone(manager.get(track_key))
        _active, removed = manager.update(scan(config, 4, 1.3), config)
        self.assertIn(track_key, removed)
        self.assertIsNone(manager.get(track_key))

    def test_duplicate_measurement_is_ignored(self) -> None:
        manager = RadarTrackManager()
        config = radar_config()
        manager.update(scan(config, 1, 1.0, target(5, 0.0, 6.0)), config)
        manager.update(scan(config, 1, 1.1, target(5, 1.0, 2.0)), config)
        current = manager.active_tracks()[0]
        self.assertEqual(1, current.age_scans)
        self.assertAlmostEqual(0.0, current.x_m)
        self.assertAlmostEqual(6.0, current.z_m)

    def test_mount_inversion_and_yaw_transform_position_and_velocity(self) -> None:
        manager = RadarTrackManager()
        config = radar_config(
            mount_x_m=1.0,
            mount_z_m=2.0,
            mount_yaw_deg=90.0,
            invert_lateral=True,
            invert_longitudinal_velocity=True,
        )
        tracks, _ = manager.update(scan(config, 1, 1.0, target(1, 2.0, 5.0, vx=1.0, vz=-2.0)), config)
        track = tracks[0]
        self.assertAlmostEqual(6.0, track.x_m, places=5)
        self.assertAlmostEqual(4.0, track.z_m, places=5)
        self.assertAlmostEqual(2.0, track.vx_mps, places=5)
        self.assertAlmostEqual(-1.0, track.vz_mps, places=5)


if __name__ == "__main__":
    unittest.main()
