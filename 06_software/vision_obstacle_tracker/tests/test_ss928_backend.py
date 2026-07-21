from pathlib import Path
import tempfile
import unittest

import numpy as np

from calibration import CameraCalibration
from detector_backend import (
    IndependentIouTracker,
    PortableDetection,
    PortableDetectionResult,
    Ss928OmBackend,
    _TensorInfo,
    _model_image_shape,
    decode_yolo_84x8400,
    letterbox_for_ss928,
)
from risk_model import RiskModel
from vision_core import StableTrackIdManager, TrackState
from vision_obstacle_tracker import (
    draw_overlay,
    restore_result_boxes_to_full_frame,
    result_to_observations,
)


def tensor_info(data_type, dims, byte_size):
    info = _TensorInfo()
    info.data_type = data_type
    info.dim_count = len(dims)
    info.byte_size = byte_size
    for index, value in enumerate(dims):
        info.dims[index] = value
    return info


class FakeRuntime:
    def __init__(self):
        self.input_info = tensor_info(4, (1, 3, 640, 640), 3 * 640 * 640)
        self.output_info = tensor_info(0, (1, 84, 8400), 84 * 8400 * 4)
        self.inputs = []
        self.closed = False

    def infer(self, input_array, output_array):
        self.inputs.append(input_array.copy())
        output_array.fill(0.0)
        predictions = output_array.reshape(84, 8400)
        predictions[0:4, 0] = (320.0, 320.0, 160.0, 120.0)
        predictions[4 + 2, 0] = 0.92
        return 24.5

    def close(self):
        self.closed = True


class FakeNv12Runtime(FakeRuntime):
    def __init__(self):
        super().__init__()
        self.input_info = tensor_info(4, (1, 640, 640, 3), 640 * 640 * 3 // 2)


class Ss928PreprocessTest(unittest.TestCase):
    def test_letterbox_produces_rgb_chw_uint8(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:, :, 0] = 10
        frame[:, :, 1] = 20
        frame[:, :, 2] = 30

        tensor, scale, pad_x, pad_y = letterbox_for_ss928(
            frame,
            640,
            640,
            layout="chw",
            dtype=np.uint8,
        )

        self.assertEqual((3, 640, 640), tensor.shape)
        self.assertTrue(tensor.flags.c_contiguous)
        self.assertAlmostEqual(1.0, scale)
        self.assertAlmostEqual(0.0, pad_x)
        self.assertAlmostEqual(80.0, pad_y)
        self.assertEqual(30, int(tensor[0, 100, 100]))
        self.assertEqual(20, int(tensor[1, 100, 100]))
        self.assertEqual(10, int(tensor[2, 100, 100]))

    def test_model_metadata_detects_static_aipp_nv12_storage(self):
        info = tensor_info(4, (1, 640, 640, 3), 640 * 640 * 3 // 2)

        self.assertEqual((640, 640, "nv12"), _model_image_shape(info))

    def test_letterbox_produces_nv12_for_static_aipp_model(self):
        import cv2

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:, :, 0] = 10
        frame[:, :, 1] = 20
        frame[:, :, 2] = 30

        tensor, scale, pad_x, pad_y = letterbox_for_ss928(
            frame,
            640,
            640,
            layout="nv12",
            dtype=np.uint8,
        )

        padded = cv2.copyMakeBorder(
            frame,
            80,
            80,
            0,
            0,
            cv2.BORDER_CONSTANT,
            value=(114, 114, 114),
        )
        i420 = cv2.cvtColor(padded, cv2.COLOR_BGR2YUV_I420).reshape(-1)
        y_size = 640 * 640
        chroma_size = y_size // 4
        flat = tensor.reshape(-1)

        self.assertEqual((960, 640), tensor.shape)
        self.assertTrue(tensor.flags.c_contiguous)
        self.assertEqual(640 * 640 * 3 // 2, tensor.nbytes)
        self.assertAlmostEqual(1.0, scale)
        self.assertAlmostEqual(0.0, pad_x)
        self.assertAlmostEqual(80.0, pad_y)
        np.testing.assert_array_equal(flat[:y_size], i420[:y_size])
        np.testing.assert_array_equal(
            flat[y_size : y_size + 8 : 2],
            i420[y_size : y_size + 4],
        )
        np.testing.assert_array_equal(
            flat[y_size + 1 : y_size + 9 : 2],
            i420[y_size + chroma_size : y_size + chroma_size + 4],
        )

    def test_decode_filters_classes_and_restores_letterbox(self):
        output = np.zeros((84, 8400), dtype=np.float32)
        output[0:4, 0] = (320.0, 320.0, 160.0, 120.0)
        output[6, 0] = 0.90  # class 2, car
        output[0:4, 1] = (100.0, 100.0, 40.0, 40.0)
        output[4, 1] = 0.99  # class 0, person

        detections = decode_yolo_84x8400(
            output,
            source_shape=(480, 640),
            scale=1.0,
            pad_x=0.0,
            pad_y=80.0,
            confidence_threshold=0.20,
            class_filter={2},
            max_det=10,
        )

        self.assertEqual(1, len(detections))
        self.assertEqual(2, detections[0].class_id)
        self.assertEqual((240.0, 180.0, 400.0, 300.0), detections[0].bbox_xyxy)


class PortableTrackerTest(unittest.TestCase):
    def test_tracks_are_stable_and_tracker_instances_are_independent(self):
        names = {2: "car"}
        first = PortableDetectionResult(
            [PortableDetection((100.0, 100.0, 200.0, 200.0), 0.9, 2)],
            names,
            (480, 640),
        )
        second = PortableDetectionResult(
            [PortableDetection((108.0, 102.0, 208.0, 202.0), 0.88, 2)],
            names,
            (480, 640),
        )
        left = IndependentIouTracker()
        right = IndependentIouTracker()

        left_id_1 = left.update(first).detections[0].track_id
        left_id_2 = left.update(second).detections[0].track_id
        right_id = right.update(
            PortableDetectionResult(
                [PortableDetection((108.0, 102.0, 208.0, 202.0), 0.88, 2)],
                names,
                (480, 640),
            )
        ).detections[0].track_id

        self.assertEqual(left_id_1, left_id_2)
        self.assertEqual(1, right_id)

    def test_portable_result_enters_existing_distance_pipeline_after_roi_restore(self):
        result = PortableDetectionResult(
            [PortableDetection((250.0, 60.0, 330.0, 240.0), 0.9, 2, track_id=7)],
            {2: "car"},
            (360, 640),
        )

        restore_result_boxes_to_full_frame(result, 120)
        observations = result_to_observations(
            result,
            1.0,
            CameraCalibration(image_width=640, image_height=480),
            {"car"},
            "fused",
            0.75,
        )

        self.assertEqual((250.0, 180.0, 330.0, 360.0), observations[0].bbox_xyxy)
        self.assertEqual(7, observations[0].track_id)
        self.assertIsNotNone(observations[0].ground_point)


class Ss928BackendTest(unittest.TestCase):
    def test_fake_runtime_runs_detection_and_tracking_without_ultralytics(self):
        runtime = FakeRuntime()
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "fixture.om"
            model_path.write_bytes(b"fixture")
            backend = Ss928OmBackend(model_path, runtime=runtime)
            frame = np.zeros((480, 640, 3), dtype=np.uint8)

            first = backend.track(frame, conf=0.20, classes=[2], max_det=10)[0]
            second = backend.track(frame, conf=0.20, classes=[2], max_det=10)[0]

            self.assertEqual(1, len(first.detections))
            self.assertEqual(first.detections[0].track_id, second.detections[0].track_id)
            self.assertAlmostEqual(24.5, backend.last_npu_ms)
            self.assertEqual((3, 640, 640), runtime.inputs[0].shape)
            backend.close()
            self.assertTrue(runtime.closed)

    def test_static_aipp_runtime_receives_nv12_input(self):
        runtime = FakeNv12Runtime()
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "fixture.om"
            model_path.write_bytes(b"fixture")
            backend = Ss928OmBackend(model_path, runtime=runtime)
            frame = np.zeros((480, 640, 3), dtype=np.uint8)

            result = backend.predict(frame, conf=0.20, classes=[2], max_det=10)[0]

            self.assertEqual(1, len(result.detections))
            self.assertEqual("nv12", backend.input_layout)
            self.assertEqual((960, 640), runtime.inputs[0].shape)
            self.assertEqual(640 * 640 * 3 // 2, runtime.inputs[0].nbytes)
            backend.close()

    def test_fake_npu_result_reaches_tracking_risk_and_overlay(self):
        runtime = FakeRuntime()
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "fixture.om"
            model_path.write_bytes(b"fixture")
            backend = Ss928OmBackend(model_path, runtime=runtime)
            frame = np.zeros((480, 640, 3), dtype=np.uint8)

            result = backend.track(frame, conf=0.20, classes=[2], max_det=10)[0]
            observations = result_to_observations(
                result,
                1.0,
                CameraCalibration(image_width=640, image_height=480),
                {"car"},
                "fused",
                0.75,
            )
            observations = StableTrackIdManager().assign(observations)
            tracked = [TrackState().update(observation) for observation in observations]
            risks = {target.track_id: RiskModel().assess(target) for target in tracked}
            draw_overlay(frame, tracked, "FPS 1.0", "SS928 NPU", risks)

            self.assertEqual(1, len(tracked))
            self.assertGreater(int(np.count_nonzero(frame)), 0)
            backend.close()

    def test_backend_rejects_same_size_output_with_wrong_tensor_layout(self):
        runtime = FakeRuntime()
        runtime.output_info = tensor_info(0, (1, 8400, 84), 84 * 8400 * 4)
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "fixture.om"
            model_path.write_bytes(b"fixture")

            with self.assertRaisesRegex(ValueError, "1x84x8400"):
                Ss928OmBackend(model_path, runtime=runtime)
            self.assertTrue(runtime.closed)


if __name__ == "__main__":
    unittest.main()
