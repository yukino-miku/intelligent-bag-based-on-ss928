from __future__ import annotations

import sys
import unittest
from pathlib import Path


DIAGNOSTICS_DIR = Path(__file__).resolve().parents[1] / "diagnostics"
sys.path.insert(0, str(DIAGNOSTICS_DIR))

from om_alert_bridge import parse_alert_line, parse_sample_detection_line  # noqa: E402


class OmAlertBridgeTest(unittest.TestCase):
    def test_parse_existing_vision_alert_json(self) -> None:
        event = parse_alert_line('{"type":"vision_alert","side":"right","level":4,"score":0.9}', "left")

        self.assertIsNotNone(event)
        self.assertEqual(event["side"], "right")
        self.assertEqual(event["level"], 4)

    def test_parse_level_text_uses_default_side(self) -> None:
        event = parse_alert_line("risk level=3 score=0.72", "left")

        self.assertIsNotNone(event)
        self.assertEqual(event["side"], "left")
        self.assertEqual(event["level"], 3)

    def test_parse_al_command_text(self) -> None:
        event = parse_alert_line("AL R2", "left")

        self.assertIsNotNone(event)
        self.assertEqual(event["side"], "right")
        self.assertEqual(event["level"], 2)

    def test_sample_detection_mapping_is_explicit_fallback(self) -> None:
        event = parse_sample_detection_line("2 = 0.91000 at 10 20 100 320", "right", 640, 640)

        self.assertIsNotNone(event)
        self.assertEqual(event["side"], "right")
        self.assertEqual(event["level"], 3)


if __name__ == "__main__":
    unittest.main()
