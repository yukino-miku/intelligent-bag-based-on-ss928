import tempfile
import unittest
from pathlib import Path

from calibration import (
    CameraCalibration,
    _load_simple_yaml_mapping,
    calibration_from_mapping,
    estimate_ground_point_from_bbox,
    estimate_size_distance_m,
    load_calibration_file,
    pixel_to_ground,
)


class CalibrationTest(unittest.TestCase):
    def test_center_bottom_pixel_returns_forward_ground_point(self) -> None:
        calibration = CameraCalibration(
            image_width=2560,
            image_height=1440,
            horizontal_fov_deg=80.0,
            camera_height_m=1.2,
            camera_pitch_deg=12.0,
        )

        point = pixel_to_ground(1280, 1300, calibration)

        self.assertIsNotNone(point)
        assert point is not None
        self.assertAlmostEqual(0.0, point.x_m, delta=0.05)
        self.assertGreater(point.z_m, 0.5)
        self.assertLess(point.z_m, 10.0)
        self.assertAlmostEqual(point.z_m, point.distance_m, delta=0.05)

    def test_pixel_above_ground_intersection_returns_none(self) -> None:
        calibration = CameraCalibration(
            image_width=2560,
            image_height=1440,
            horizontal_fov_deg=80.0,
            camera_height_m=1.2,
            camera_pitch_deg=8.0,
        )

        self.assertIsNone(pixel_to_ground(1280, 200, calibration))

    def test_lower_pixels_are_closer_than_higher_pixels(self) -> None:
        calibration = CameraCalibration(
            image_width=2560,
            image_height=1440,
            horizontal_fov_deg=80.0,
            camera_height_m=1.2,
            camera_pitch_deg=12.0,
        )

        far_point = pixel_to_ground(1280, 900, calibration)
        near_point = pixel_to_ground(1280, 1320, calibration)

        self.assertIsNotNone(far_point)
        self.assertIsNotNone(near_point)
        assert far_point is not None
        assert near_point is not None
        self.assertGreater(far_point.z_m, near_point.z_m)

    def test_diagonal_fov_120_computes_wide_angle_focal_length(self) -> None:
        calibration = CameraCalibration(
            image_width=1920,
            image_height=1080,
            fov_deg=120.0,
            fov_type="diagonal",
        )

        self.assertAlmostEqual(635.6, calibration.fx, delta=1.0)
        self.assertAlmostEqual(calibration.fx, calibration.fy, delta=0.001)

    def test_real_intrinsics_use_independent_fx_fy_cx_cy(self) -> None:
        calibration = CameraCalibration(
            image_width=1280,
            image_height=720,
            camera_matrix=((900.0, 0.0, 620.0), (0.0, 880.0, 350.0), (0.0, 0.0, 1.0)),
            dist_coeffs=(0.0, 0.0, 0.0, 0.0, 0.0),
        )

        self.assertTrue(calibration.has_intrinsics)
        self.assertEqual(900.0, calibration.fx)
        self.assertEqual(880.0, calibration.fy)
        self.assertEqual(620.0, calibration.cx)
        self.assertEqual(350.0, calibration.cy)

    def test_json_calibration_file_can_build_intrinsics_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "calibration.json"
            path.write_text(
                """
{
  "image_width": 1280,
  "image_height": 720,
  "camera_matrix": [[900, 0, 640], [0, 880, 360], [0, 0, 1]],
  "dist_coeffs": [0.1, -0.05, 0.0, 0.0, 0.0],
  "camera_height_m": 1.2,
  "camera_pitch_deg": 6.0
}
""",
                encoding="utf-8",
            )

            mapping = load_calibration_file(path)
            calibration = calibration_from_mapping(mapping, CameraCalibration())

        self.assertTrue(calibration.has_intrinsics)
        self.assertEqual((0.1, -0.05, 0.0, 0.0, 0.0), calibration.dist_coeffs)
        self.assertEqual(6.0, calibration.camera_pitch_deg)

    def test_simple_yaml_fallback_reads_block_camera_matrix(self) -> None:
        mapping = _load_simple_yaml_mapping(
            """
image_width: 1280
image_height: 720
camera_matrix:
  - [920.0, 0.0, 640.0]
  - [0.0, 918.0, 360.0]
  - [0.0, 0.0, 1.0]
dist_coeffs:
  - -0.12
  - 0.04
  - 0.0
camera_height_m: 1.2
camera_pitch_deg: 5.0
"""
        )

        self.assertEqual(1280, mapping["image_width"])
        self.assertEqual(720, mapping["image_height"])
        self.assertEqual([920.0, 0.0, 640.0], mapping["camera_matrix"][0])
        self.assertEqual([-0.12, 0.04, 0.0], mapping["dist_coeffs"])

    def test_undistort_pixel_is_noop_without_real_calibration(self) -> None:
        calibration = CameraCalibration(image_width=1280, image_height=720)

        self.assertEqual((100.0, 200.0), calibration.undistort_pixel(100.0, 200.0))

    def test_size_distance_estimates_far_vehicle_from_bbox_height(self) -> None:
        calibration = CameraCalibration(
            image_width=1920,
            image_height=1080,
            fov_deg=120.0,
            fov_type="diagonal",
        )

        distance = estimate_size_distance_m((900, 500, 1020, 560), "car", calibration)

        self.assertIsNotNone(distance)
        assert distance is not None
        self.assertGreater(distance, 10.0)

    def test_fused_estimate_prefers_vehicle_size_when_ground_projection_is_too_close(self) -> None:
        calibration = CameraCalibration(
            image_width=1920,
            image_height=1080,
            fov_deg=120.0,
            fov_type="diagonal",
            camera_height_m=1.1,
            camera_pitch_deg=5.0,
        )

        estimate = estimate_ground_point_from_bbox(
            (900, 500, 1020, 560),
            "car",
            calibration,
            mode="fused",
            size_weight=0.75,
        )

        self.assertIsNotNone(estimate)
        assert estimate is not None
        self.assertEqual("fused", estimate.source)
        self.assertGreater(estimate.point.z_m, 8.0)
        self.assertGreater(estimate.distance_confidence, 0.0)

    def test_adaptive_fusion_lowers_confidence_when_ground_and_size_disagree(self) -> None:
        calibration = CameraCalibration(
            image_width=1920,
            image_height=1080,
            fov_deg=120.0,
            fov_type="diagonal",
            camera_height_m=1.1,
            camera_pitch_deg=5.0,
        )

        estimate = estimate_ground_point_from_bbox(
            (900, 850, 960, 1010),
            "car",
            calibration,
            mode="fused",
        )

        self.assertIsNotNone(estimate)
        assert estimate is not None
        self.assertIn("distance_disagreement", estimate.quality_flags)
        self.assertLess(estimate.distance_confidence, 0.9)


if __name__ == "__main__":
    unittest.main()
