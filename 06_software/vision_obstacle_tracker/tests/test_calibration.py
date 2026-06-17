import unittest

from calibration import CameraCalibration, estimate_ground_point_from_bbox, estimate_size_distance_m, pixel_to_ground


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


if __name__ == "__main__":
    unittest.main()
