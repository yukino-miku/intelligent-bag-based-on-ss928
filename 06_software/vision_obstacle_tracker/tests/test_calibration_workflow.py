import argparse
import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from tools.calibration_workflow import (
    CheckerboardObservation,
    calibrate_observations,
    checkerboard_signature,
)
from tools.validate_calibration import validation_errors
from tools.diagnose_uvc_black_frames import frame_is_effectively_black, frame_visibility_metrics


class CalibrationWorkflowTest(unittest.TestCase):
    def test_visibility_metrics_separate_black_and_structured_frames(self) -> None:
        import numpy as np

        black = np.zeros((120, 160, 3), dtype=np.uint8)
        structured = np.zeros((120, 160, 3), dtype=np.uint8)
        structured[:, 80:] = 255

        self.assertTrue(frame_is_effectively_black(frame_visibility_metrics(black)))
        self.assertFalse(frame_is_effectively_black(frame_visibility_metrics(structured)))

    def test_pose_signature_separates_board_coverage(self) -> None:
        import numpy as np

        first = np.array([[[100.0, 100.0]], [[200.0, 100.0]], [[200.0, 200.0]]])
        second = first + np.array([300.0, 100.0])

        self.assertNotEqual(
            checkerboard_signature(first, (640, 480)),
            checkerboard_signature(second, (640, 480)),
        )

    def test_synthetic_checkerboard_calibration_reports_low_error(self) -> None:
        import cv2
        import numpy as np

        board_size = (9, 6)
        square_size_m = 0.025
        object_points = np.zeros((board_size[0] * board_size[1], 3), dtype=np.float32)
        object_points[:, :2] = np.mgrid[0 : board_size[0], 0 : board_size[1]].T.reshape(-1, 2)
        object_points *= square_size_m
        matrix = np.array([[700.0, 0.0, 320.0], [0.0, 690.0, 240.0], [0.0, 0.0, 1.0]])
        observations = []
        for index in range(10):
            rvec = np.array([0.02 * index, -0.015 * index, 0.01 * index], dtype=np.float64)
            tvec = np.array(
                [-0.08 + 0.015 * index, -0.04 + 0.008 * index, 0.75 + 0.04 * index],
                dtype=np.float64,
            )
            corners, _jacobian = cv2.projectPoints(
                object_points,
                rvec,
                tvec,
                matrix,
                np.zeros(5),
            )
            observations.append(
                CheckerboardObservation(
                    Path(f"synthetic-{index}.jpg"),
                    (640, 480),
                    corners.astype(np.float32),
                    checkerboard_signature(corners, (640, 480)),
                )
            )

        result = calibrate_observations(observations, board_size, square_size_m)

        self.assertLess(result["rms_px"], 0.05)
        self.assertEqual(10, len(result["per_image_errors"]))

    def test_production_validation_checks_resolution_rotation_and_rms(self) -> None:
        data = {
            "camera_matrix": [[700.0, 0.0, 320.0], [0.0, 700.0, 240.0], [0.0, 0.0, 1.0]],
            "dist_coeffs": [0.0, 0.0, 0.0, 0.0, 0.0],
            "image_width": 640,
            "image_height": 480,
            "camera_height_m": 1.2,
            "camera_pitch_deg": 5.0,
            "distance_scale": 1.0,
            "calibration_version": "2",
            "calibration_rms_px": 0.4,
            "image_transform": {"rotation_deg": 90},
            "extrinsics": {
                "mount_yaw_deg": 0.0,
                "mount_roll_deg": 0.0,
                "mount_x_m": -0.15,
                "mount_z_m": 0.0,
                "calibrated": True,
            },
        }
        args = argparse.Namespace(
            side="left",
            mode="production",
            expected_width=640,
            expected_height=480,
            expected_rotation_deg=90,
            max_rms_px=1.0,
        )

        self.assertEqual([], validation_errors(data, args))


if __name__ == "__main__":
    unittest.main()
