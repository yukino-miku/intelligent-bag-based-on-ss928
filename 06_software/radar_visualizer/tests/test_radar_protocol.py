import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radar_protocol import RadarStreamParser


def build_report_frame(report_type, payload):
    body = bytes([report_type]) + payload
    head_and_payload = bytes([0x5A, len(body)]) + body
    checksum = sum(head_and_payload) & 0xFF
    return head_and_payload + bytes([checksum])


class RadarProtocolTest(unittest.TestCase):
    def test_decodes_bsd_targets_from_active_report(self):
        payload = (
            bytes([0x02, 0x00, 0x00, 0x00])
            + bytes([12, 5, 3, 1])
            + bytes([4, 0xE8, 2, 2])
        )
        parser = RadarStreamParser()

        reports = parser.feed(build_report_frame(0x07, payload))

        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].report_type, 0x07)
        self.assertEqual(len(reports[0].targets), 2)
        self.assertEqual(reports[0].targets[0].distance_m, 12)
        self.assertEqual(reports[0].targets[0].angle_deg, 5)
        self.assertEqual(reports[0].targets[0].velocity_mps, 3)
        self.assertEqual(reports[0].targets[0].target_id, 1)
        self.assertEqual(reports[0].targets[1].distance_m, 4)
        self.assertEqual(reports[0].targets[1].angle_deg, -24)
        self.assertEqual(reports[0].targets[1].velocity_mps, 2)
        self.assertEqual(reports[0].targets[1].target_id, 2)

    def test_keeps_incomplete_frame_until_more_bytes_arrive(self):
        payload = bytes([0x01, 0x00, 0x00, 0x00, 8, 0, 1, 7])
        frame = build_report_frame(0x07, payload)
        parser = RadarStreamParser()

        self.assertEqual(parser.feed(frame[:4]), [])
        reports = parser.feed(frame[4:])

        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].targets[0].target_id, 7)

    def test_ignores_noise_and_bad_checksum(self):
        payload = bytes([0x01, 0x00, 0x00, 0x00, 9, 1, 2, 3])
        good_frame = build_report_frame(0x07, payload)
        bad_frame = bytearray(good_frame)
        bad_frame[-1] ^= 0xFF
        parser = RadarStreamParser()

        reports = parser.feed(b"\x00\xAA" + bytes(bad_frame) + b"\x13" + good_frame)

        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].targets[0].target_id, 3)

    def test_limits_decoding_to_available_targets(self):
        payload = bytes([0x03, 0x00, 0x00, 0x00, 6, 1, 1, 4])
        parser = RadarStreamParser()

        reports = parser.feed(build_report_frame(0x07, payload))

        self.assertEqual(len(reports), 1)
        self.assertEqual(len(reports[0].targets), 1)


if __name__ == "__main__":
    unittest.main()
