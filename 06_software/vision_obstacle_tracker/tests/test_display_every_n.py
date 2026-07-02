from types import SimpleNamespace
import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from vision_obstacle_tracker import main, visualization_plan_for_frame


class FakeCapture:
    def __init__(self) -> None:
        self.frame = np.zeros((48, 64, 3), dtype=np.uint8)
        self.read_calls = 0
        self.released = False

    def read(self):
        self.read_calls += 1
        return True, self.frame.copy()

    def get(self, prop_id: int) -> float:
        return 30.0

    def release(self) -> None:
        self.released = True


class FakeModel:
    names = {2: "car"}

    def __init__(self) -> None:
        self.track_calls: list[tuple[object, dict]] = []

    def track(self, frame, **kwargs):
        self.track_calls.append((frame, kwargs))
        return [SimpleNamespace(boxes=None, names=self.names)]


class DisplayEveryNTest(unittest.TestCase):
    def test_visualization_plan_shows_frame_zero_and_every_nth_frame(self) -> None:
        visible_frames = [
            frame_index
            for frame_index in range(12)
            if visualization_plan_for_frame(
                processed_frame_index=frame_index,
                display_every_n=5,
                no_display=False,
                has_writer=False,
            ).should_show_window
        ]

        self.assertEqual([0, 5, 10], visible_frames)

    def test_display_every_one_keeps_preview_every_processed_frame(self) -> None:
        capture, model, draw_overlay, imshow, wait_key, _writer = self._run_main(
            "--display-every-n",
            "1",
            "--max-frames",
            "3",
        )

        self.assertEqual(3, model_track_count(model))
        self.assertEqual(3, draw_overlay.call_count)
        self.assertEqual(3, imshow.call_count)
        self.assertEqual(3, wait_key.call_count)
        self.assertEqual(3, capture.read_calls)
        self.assertTrue(capture.released)

    def test_display_every_five_does_not_reduce_detection_or_max_frames(self) -> None:
        capture, model, draw_overlay, imshow, wait_key, _writer = self._run_main(
            "--display-every-n",
            "5",
            "--max-frames",
            "11",
        )

        self.assertEqual(11, model_track_count(model))
        self.assertEqual(3, draw_overlay.call_count)
        self.assertEqual(3, imshow.call_count)
        self.assertEqual(3, wait_key.call_count)
        self.assertEqual(11, capture.read_calls)

    def test_non_display_frames_do_not_generate_overlay_when_not_saving(self) -> None:
        _capture, model, draw_overlay, imshow, _wait_key, _writer = self._run_main(
            "--display-every-n",
            "5",
            "--max-frames",
            "2",
        )

        self.assertEqual(2, model_track_count(model))
        self.assertEqual(1, draw_overlay.call_count)
        self.assertEqual(1, imshow.call_count)

    def test_save_output_draws_and_writes_every_frame_but_shows_every_nth_frame(self) -> None:
        writer = MagicMock()
        _capture, model, draw_overlay, imshow, wait_key, returned_writer = self._run_main(
            "--display-every-n",
            "5",
            "--max-frames",
            "7",
            "--save-output",
            "overlay.mp4",
            writer=writer,
        )

        self.assertIs(writer, returned_writer)
        self.assertEqual(7, model_track_count(model))
        self.assertEqual(7, draw_overlay.call_count)
        self.assertEqual(7, writer.write.call_count)
        self.assertEqual(2, imshow.call_count)
        self.assertEqual(2, wait_key.call_count)
        writer.release.assert_called_once()

    def test_no_display_does_not_draw_or_show_when_not_saving(self) -> None:
        _capture, model, draw_overlay, imshow, wait_key, _writer = self._run_main(
            "--no-display",
            "--max-frames",
            "5",
        )

        self.assertEqual(5, model_track_count(model))
        self.assertEqual(0, draw_overlay.call_count)
        self.assertEqual(0, imshow.call_count)
        self.assertEqual(0, wait_key.call_count)

    def _run_main(self, *extra_args: str, writer=None):
        capture = FakeCapture()
        model = FakeModel()
        argv = [
            "vision_obstacle_tracker.py",
            "--source",
            "video",
            "--video",
            "input.mp4",
            "--video-every-frame",
            *extra_args,
        ]

        with (
            patch.object(sys, "argv", argv),
            patch("vision_obstacle_tracker.open_capture", return_value=capture),
            patch("vision_obstacle_tracker.create_yolo_model", return_value=model),
            patch("vision_obstacle_tracker.create_writer", return_value=writer),
            patch("vision_obstacle_tracker.draw_overlay") as draw_overlay,
            patch("cv2.namedWindow"),
            patch("cv2.imshow") as imshow,
            patch("cv2.waitKey", return_value=-1) as wait_key,
            patch("cv2.destroyAllWindows"),
        ):
            main()

        return capture, model, draw_overlay, imshow, wait_key, writer


def model_track_count(model: FakeModel) -> int:
    return len(model.track_calls)


if __name__ == "__main__":
    unittest.main()
