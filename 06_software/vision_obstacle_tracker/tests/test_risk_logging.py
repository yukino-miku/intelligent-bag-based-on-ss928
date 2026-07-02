import csv
import tempfile
import unittest
from pathlib import Path

from calibration import GroundPoint
from risk_model import MotionPattern, RiskAssessment, RiskLevel
from vision_core import TrackedObject
from vision_obstacle_tracker import RiskCsvLogger, StabilizerDebugInfo


class RiskLoggingTest(unittest.TestCase):
    def test_risk_csv_logger_writes_quality_motion_and_display_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "risk.csv"
            logger = RiskCsvLogger(str(log_path))
            point = GroundPoint(x_m=0.5, z_m=3.0)
            target = TrackedObject(
                track_id=7,
                class_name="car",
                confidence=0.82,
                bbox_xyxy=(10, 20, 110, 220),
                ground_point=point,
                distance_m=point.distance_m,
                vx_mps=-0.2,
                vz_mps=-2.0,
                speed_mps=2.01,
                timestamp_s=1.25,
                distance_source="fused",
                ground_distance_m=3.1,
                size_distance_m=3.4,
                distance_confidence=0.72,
                ground_confidence=0.80,
                size_confidence=0.65,
                quality_flags=("distance_disagreement",),
                observation_quality=0.58,
                velocity_confidence=0.62,
                ego_motion_magnitude=9.0,
            )
            raw = RiskAssessment(
                track_id=7,
                score=0.76,
                level=RiskLevel.DANGER,
                ttc_s=1.5,
                trajectory_distance_m=0.7,
                drac_mps2=4.2,
                closing_speed_mps=2.0,
                motion_pattern=MotionPattern.HEAD_ON_OR_CLOSING,
                trajectory_risk=0.80,
                ttc_risk=0.70,
                drac_risk=0.30,
                closing_risk=0.20,
                static_obstacle_risk=0.10,
            )
            display = RiskAssessment(
                track_id=7,
                score=0.60,
                level=RiskLevel.CAUTION,
                ttc_s=1.5,
                trajectory_distance_m=0.7,
                drac_mps2=4.2,
                closing_speed_mps=2.0,
                motion_pattern=MotionPattern.HEAD_ON_OR_CLOSING,
            )

            logger.write_frame(
                42,
                [target],
                {7: raw},
                {7: display},
                {
                    7: StabilizerDebugInfo(
                        pending_level=RiskLevel.DANGER,
                        pending_count=1,
                        required_frames=2,
                        reason="waiting_confirmation",
                    )
                },
            )
            logger.close()

            with log_path.open(newline="", encoding="utf-8") as csv_file:
                rows = list(csv.DictReader(csv_file))

        self.assertEqual(1, len(rows))
        row = rows[0]
        self.assertEqual("42", row["frame_index"])
        self.assertEqual("7", row["track_id"])
        self.assertEqual("0.580", row["observation_quality"])
        self.assertEqual("0.720", row["distance_confidence"])
        self.assertEqual("0.620", row["velocity_confidence"])
        self.assertEqual("distance_disagreement", row["quality_flags"])
        self.assertEqual("CLOSING", row["motion_pattern"])
        self.assertEqual("0.760", row["raw_risk_score"])
        self.assertEqual("DANGER", row["raw_risk_level"])
        self.assertEqual("0.600", row["display_risk_score"])
        self.assertEqual("CAUTION", row["display_risk_level"])
        self.assertEqual("0.800", row["trajectory_risk"])
        self.assertEqual("0.700", row["ttc_risk"])
        self.assertEqual("0.200", row["closing_risk"])
        self.assertEqual("DANGER", row["stabilizer_pending_level"])
        self.assertEqual("1", row["stabilizer_pending_count"])
        self.assertEqual("2", row["stabilizer_required_frames"])
        self.assertEqual("waiting_confirmation", row["stabilizer_reason"])


if __name__ == "__main__":
    unittest.main()
