import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from view_model import polar_to_xy


class ViewModelTest(unittest.TestCase):
    def test_places_zero_degree_target_on_forward_axis(self):
        point = polar_to_xy(distance_m=10, angle_deg=0, max_range_m=20, width=800, height=600)

        self.assertEqual(point, (400, 300))

    def test_positive_angle_moves_target_right_in_screen_coordinates(self):
        center = polar_to_xy(distance_m=10, angle_deg=0, max_range_m=20, width=800, height=600)
        right = polar_to_xy(distance_m=10, angle_deg=30, max_range_m=20, width=800, height=600)

        self.assertGreater(right[0], center[0])
        self.assertGreater(right[1], center[1])

    def test_distance_is_clamped_to_configured_max_range(self):
        edge = polar_to_xy(distance_m=20, angle_deg=0, max_range_m=20, width=800, height=600)
        beyond = polar_to_xy(distance_m=50, angle_deg=0, max_range_m=20, width=800, height=600)

        self.assertEqual(beyond, edge)


if __name__ == "__main__":
    unittest.main()
