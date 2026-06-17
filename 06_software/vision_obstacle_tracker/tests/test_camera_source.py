import unittest

from camera_source import FfmpegCameraConfig, MjpegFrameParser, build_ffmpeg_mjpeg_command


class CameraSourceTest(unittest.TestCase):
    def test_build_ffmpeg_mjpeg_command_uses_balanced_camera_profile(self) -> None:
        command = build_ffmpeg_mjpeg_command(FfmpegCameraConfig())

        self.assertIn("dshow", command)
        self.assertIn("1920x1080", command)
        self.assertIn("30", command)
        self.assertIn("video=USB Camera", command)
        self.assertIn("copy", command)
        self.assertEqual("pipe:1", command[-1])

    def test_build_ffmpeg_mjpeg_command_uses_low_latency_buffers(self) -> None:
        command = build_ffmpeg_mjpeg_command(FfmpegCameraConfig())

        self.assertIn("-rtbufsize", command)
        self.assertIn("2M", command)
        self.assertIn("-probesize", command)
        self.assertIn("32", command)
        self.assertIn("-analyzeduration", command)
        self.assertIn("0", command)
        self.assertIn("-flush_packets", command)
        self.assertIn("1", command)

    def test_mjpeg_parser_extracts_multiple_complete_frames(self) -> None:
        parser = MjpegFrameParser()
        frame_1 = b"\xff\xd8one\xff\xd9"
        frame_2 = b"\xff\xd8two\xff\xd9"

        frames = parser.feed(b"junk" + frame_1 + frame_2)

        self.assertEqual([frame_1, frame_2], frames)

    def test_mjpeg_parser_holds_partial_frame_until_complete(self) -> None:
        parser = MjpegFrameParser()

        self.assertEqual([], parser.feed(b"\xff\xd8partial"))
        self.assertEqual([b"\xff\xd8partial\xff\xd9"], parser.feed(b"\xff\xd9"))


if __name__ == "__main__":
    unittest.main()
