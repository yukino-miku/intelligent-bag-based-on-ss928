from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "ss928_backend"
VISION_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(VISION_DIR) not in sys.path:
    sys.path.insert(0, str(VISION_DIR))

from detection_protocol import parse_detection_jsonl  # noqa: E402
from detector_backend import Ss928OmBackend  # noqa: E402


class Ss928DetectionProtocolTests(unittest.TestCase):
    def test_parses_empty_and_populated_frames(self) -> None:
        empty = parse_detection_jsonl('{"type":"detections","frame_index":0,"detections":[]}')
        self.assertEqual(empty.frame_index, 0)
        self.assertEqual(empty.detections, ())
        frame = parse_detection_jsonl(
            '{"type":"detections","frame_index":2,"detections":['
            '{"class_id":2,"class_name":"car","confidence":0.8,"bbox":[1,2,30,40]}]}'
        )
        self.assertEqual(frame.detections[0].class_name, "car")
        self.assertEqual(frame.detections[0].bbox, (1.0, 2.0, 30.0, 40.0))

    def test_rejects_nonfinite_or_reversed_boxes(self) -> None:
        with self.assertRaises(ValueError):
            parse_detection_jsonl(
                '{"type":"detections","frame_index":0,"detections":['
                '{"class_id":2,"class_name":"car","confidence":0.8,"bbox":[3,2,1,4]}]}'
            )

    def test_live_om_backend_rejects_input_size_not_supported_by_native_runner(self) -> None:
        with self.assertRaisesRegex(ValueError, "fixed 640x640"):
            Ss928OmBackend("missing.om", imgsz=512)


if __name__ == "__main__":
    unittest.main()
