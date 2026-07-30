from __future__ import annotations

import sys
import unittest
from pathlib import Path

BOARD_RUNTIME = Path(__file__).resolve().parents[2]
VISION = BOARD_RUNTIME.parent / "vision_obstacle_tracker"
for path in (BOARD_RUNTIME, VISION):
    sys.path.insert(0, str(path))

from radar_vision_fusion.median_risk import MedianRiskWindowAggregator, RadarRiskSample  # noqa: E402
from radar_vision_fusion.models import FusedRadarTarget  # noqa: E402
from risk_model import RiskAssessment, RiskLevel  # noqa: E402


def sample(timestamp: float, score: float, *, key: str = "left:1", side: str = "left", class_name: str = "car", complete: bool = True) -> RadarRiskSample:
    fused = FusedRadarTarget(
        track_key=key, radar_name=side + "_rear", radar_target_id=1, side=side,
        x_m=0.0, z_m=5.0, vx_mps=0.0, vz_mps=-2.0, distance_m=5.0,
        speed_mps=2.0, radar_status="oncoming", radar_quality=1.0,
        class_name=class_name, class_confidence=0.9, class_source="vision_snapshot",
        class_age_s=0.1, association_state="matched", association_score=0.1,
        projected_u_px=320.0, timestamp=timestamp,
    )
    assessment = RiskAssessment(key, score, RiskLevel.ATTENTION, 2.5, 0.0, 0.5, 2.0)
    return RadarRiskSample(
        timestamp, key, side, class_name, 1.0, score, score, 5.0, 2.0, 2.0,
        2.5, 2.0, 0.3, True, 1.0, complete, fused, assessment,
    )


class MedianRiskWindowTest(unittest.TestCase):
    def test_odd_samples_filter_one_high_outlier(self) -> None:
        aggregator = MedianRiskWindowAggregator(0.5)
        for timestamp, score in ((1.01, 0.2), (1.13, 0.95), (1.31, 0.3)):
            aggregator.add(sample(timestamp, score))
        result = aggregator.flush_due(1.5)[0]
        self.assertAlmostEqual(0.3, result.score_median)
        self.assertEqual(3, result.sample_count)

    def test_odd_samples_filter_one_low_outlier(self) -> None:
        aggregator = MedianRiskWindowAggregator(0.5)
        for timestamp, score in ((2.01, 0.8), (2.2, 0.05), (2.4, 0.7)):
            aggregator.add(sample(timestamp, score))
        self.assertAlmostEqual(0.7, aggregator.flush_due(2.5)[0].score_median)

    def test_even_samples_use_standard_median_and_sensitivity(self) -> None:
        aggregator = MedianRiskWindowAggregator(0.5, warning_sensitivity=1.5)
        for timestamp, score in ((3.01, 0.2), (3.2, 0.6), (3.3, 0.4), (3.4, 0.8)):
            aggregator.add(sample(timestamp, score))
        result = aggregator.flush_due(3.5)[0]
        self.assertAlmostEqual(0.5, result.score_median)
        self.assertAlmostEqual(0.75, result.effective_score)

    def test_tracks_sides_and_irregular_frequencies_are_independent(self) -> None:
        aggregator = MedianRiskWindowAggregator(0.5)
        aggregator.add(sample(4.01, 0.2, key="left:1", side="left"))
        aggregator.add(sample(4.11, 0.8, key="right:2", side="right"))
        aggregator.add(sample(4.47, 0.4, key="left:1", side="left"))
        results = aggregator.flush_due(4.5)
        by_key = {item.track_key: item for item in results}
        self.assertAlmostEqual(0.3, by_key["left:1"].score_median)
        self.assertAlmostEqual(0.8, by_key["right:2"].score_median)

    def test_boundary_closes_old_window_and_class_can_change(self) -> None:
        aggregator = MedianRiskWindowAggregator(0.5)
        aggregator.add(sample(5.49, 0.4, class_name="unknown", complete=False))
        closed = aggregator.add(sample(5.50, 0.6, class_name="truck"))
        self.assertEqual(1, len(closed))
        self.assertEqual("unknown", closed[0].representative_sample.class_name)
        self.assertEqual({"left:1": 1}, aggregator.sample_counts())

    def test_runtime_sensitivity_update_is_immediate_for_closed_window(self) -> None:
        aggregator = MedianRiskWindowAggregator(0.5)
        aggregator.add(sample(6.01, 0.4))
        aggregator.set_warning_sensitivity(2.0)
        result = aggregator.flush_due(6.5)[0]
        self.assertAlmostEqual(0.8, result.effective_score)

    def test_disappearing_track_discards_partial_window(self) -> None:
        aggregator = MedianRiskWindowAggregator(0.5)
        aggregator.add(sample(7.01, 0.99))
        self.assertEqual((), aggregator.remove(("left:1",), 7.1, finish=False))
        self.assertEqual({}, aggregator.sample_counts())

    def test_new_track_starts_in_its_current_fixed_window(self) -> None:
        aggregator = MedianRiskWindowAggregator(0.5)
        aggregator.add(sample(8.27, 0.4, key="right:9", side="right"))
        result = aggregator.flush_due(8.5)[0]
        self.assertEqual(8.0, result.window_start)
        self.assertEqual(8.5, result.window_end)

    def test_single_high_sample_cannot_create_l3_or_l4(self) -> None:
        aggregator = MedianRiskWindowAggregator(0.5)
        aggregator.add(sample(9.49, 0.99))
        result = aggregator.flush_due(9.5)[0]
        self.assertFalse(result.window_valid)
        self.assertIn("insufficient_samples", result.invalid_reason)
        self.assertLessEqual(result.final_level, RiskLevel.CAUTION)

    def test_quality_fields_and_valid_window(self) -> None:
        aggregator = MedianRiskWindowAggregator(0.5)
        for timestamp in (10.01, 10.20, 10.40):
            aggregator.add(sample(timestamp, 0.8))
        result = aggregator.flush_due(10.5)[0]
        self.assertTrue(result.window_valid)
        self.assertAlmostEqual(0.39, result.observed_duration_s)
        self.assertEqual(1.0, result.complete_scan_ratio)
        self.assertEqual(1.0, result.radar_quality_median)

    def test_fast_path_still_requires_two_close_quality_samples(self) -> None:
        aggregator = MedianRiskWindowAggregator(0.5)
        first = sample(11.10, 0.99)
        aggregator.add(first)
        one = aggregator.flush_due(11.5)[0]
        self.assertEqual("", one.fast_path_reason)

        aggregator = MedianRiskWindowAggregator(0.5)
        for timestamp in (12.10, 12.20):
            close = sample(timestamp, 0.99)
            close = RadarRiskSample(**{**close.__dict__, "distance_m": 0.6, "closing_speed_mps": 2.0})
            aggregator.add(close)
        two = aggregator.flush_due(12.5)[0]
        self.assertFalse(two.window_valid)
        self.assertEqual("two_sample_close_high_quality_closing", two.fast_path_reason)
        self.assertGreater(two.final_level, RiskLevel.CAUTION)


if __name__ == "__main__":
    unittest.main()
