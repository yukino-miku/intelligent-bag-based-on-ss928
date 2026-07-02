from types import SimpleNamespace
import unittest

import numpy as np

from calibration import CameraCalibration, estimate_ground_point_from_bbox
from vision_obstacle_tracker import (
    StageProfiler,
    crop_frame_for_inference,
    restore_result_boxes_to_full_frame,
    target_class_ids_from_model_names,
)


class FakeBoxes:
    def __init__(self, data=None, orig_shape=(80, 200)) -> None:
        self.data = np.array([[10.0, 5.0, 30.0, 25.0, 0.9, 2.0]]) if data is None else data
        self.orig_shape = orig_shape

    def __len__(self) -> int:
        return len(self.data)


class DetectionPipelineHelpersTest(unittest.TestCase):
    def test_target_class_ids_from_model_names_uses_model_indices(self) -> None:
        model_names = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus"}

        class_ids = target_class_ids_from_model_names(model_names, {"car", "bus", "bicycle"})

        self.assertEqual([1, 2, 5], class_ids)

    def test_target_class_ids_returns_none_for_all_classes(self) -> None:
        self.assertIsNone(target_class_ids_from_model_names(["person", "car"], None))

    def test_target_class_ids_returns_none_when_model_names_are_unavailable(self) -> None:
        self.assertIsNone(target_class_ids_from_model_names(None, {"car"}))

    def test_crop_frame_for_inference_removes_top_region_and_reports_offset(self) -> None:
        frame = np.zeros((100, 200, 3), dtype=np.uint8)

        cropped = crop_frame_for_inference(frame, 0.20)

        self.assertEqual(20, cropped.y_offset_px)
        self.assertEqual((80, 200, 3), cropped.image.shape)

    def test_crop_frame_for_inference_keeps_full_frame_by_default(self) -> None:
        frame = np.zeros((100, 200, 3), dtype=np.uint8)

        cropped = crop_frame_for_inference(frame, 0.0)

        self.assertEqual(0, cropped.y_offset_px)
        self.assertIs(frame, cropped.image)

    def test_restore_result_boxes_to_full_frame_adds_roi_y_offset(self) -> None:
        result = SimpleNamespace(boxes=FakeBoxes())
        original_data = result.boxes.data

        restore_result_boxes_to_full_frame(result, 120)

        self.assertEqual(125.0, result.boxes.data[0, 1])
        self.assertEqual(145.0, result.boxes.data[0, 3])
        self.assertEqual(10.0, result.boxes.data[0, 0])
        self.assertEqual(30.0, result.boxes.data[0, 2])
        self.assertIsNot(original_data, result.boxes.data)

    def test_restored_roi_box_uses_full_frame_coordinates_for_distance(self) -> None:
        calibration = CameraCalibration(image_width=640, image_height=480)
        full_frame_bbox = (250.0, 180.0, 330.0, 360.0)
        roi_y_offset = 120
        roi_data = np.array(
            [[250.0, 60.0, 330.0, 240.0, 0.9, 2.0]],
            dtype=float,
        )
        result = SimpleNamespace(boxes=FakeBoxes(data=roi_data, orig_shape=(360, 640)))

        restore_result_boxes_to_full_frame(result, roi_y_offset)

        restored_bbox = tuple(float(value) for value in result.boxes.data[0, :4])
        full_estimate = estimate_ground_point_from_bbox(full_frame_bbox, "car", calibration)
        restored_estimate = estimate_ground_point_from_bbox(restored_bbox, "car", calibration)

        self.assertEqual(full_frame_bbox, restored_bbox)
        self.assertIsNotNone(full_estimate)
        self.assertIsNotNone(restored_estimate)
        self.assertAlmostEqual(full_estimate.point.z_m, restored_estimate.point.z_m, places=6)

    def test_stage_profiler_reports_sliding_average_in_milliseconds(self) -> None:
        profiler = StageProfiler(enabled=True)
        profiler.record("capture", 0.010)
        profiler.record("capture", 0.030)
        profiler.record("infer+track", 0.100)

        text = profiler.summary_text()

        self.assertIn("capture=20.0ms", text)
        self.assertIn("infer+track=100.0ms", text)
        self.assertIn("total~=", text)

    def test_disabled_stage_profiler_does_not_collect_samples(self) -> None:
        profiler = StageProfiler(enabled=False)

        profiler.record("capture", 1.0)

        self.assertEqual("", profiler.summary_text())


if __name__ == "__main__":
    unittest.main()
