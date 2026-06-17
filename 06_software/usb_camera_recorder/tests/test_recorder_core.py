import datetime as dt
import unittest
from pathlib import Path

from recorder_core import (
    FFmpegRecordingSession,
    RecordingConfig,
    RESOLUTION_PRESETS,
    build_ffmpeg_command,
    build_ffplay_command,
    format_duration,
    make_output_path,
)


class FakeStdin:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.flushed = False

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def flush(self) -> None:
        self.flushed = True


class FakeProcess:
    def __init__(self) -> None:
        self.stdin = FakeStdin()
        self.wait_timeout: float | None = None
        self.terminated = False

    def wait(self, timeout: float | None = None) -> int:
        self.wait_timeout = timeout
        return 0

    def terminate(self) -> None:
        self.terminated = True


class RecorderCoreTest(unittest.TestCase):
    def test_make_output_path_uses_timestamped_mp4_name(self) -> None:
        config = RecordingConfig(output_dir=Path("D:/captures"))
        now = dt.datetime(2026, 6, 5, 14, 32, 9)

        path = make_output_path(config, now=now)

        self.assertEqual(Path("D:/captures/usbcam_20260605_143209.mp4"), path)

    def test_build_ffmpeg_command_records_usb_camera_as_mp4(self) -> None:
        config = RecordingConfig(output_dir=Path("D:/captures"))
        output = Path("D:/captures/usbcam_20260605_143209.mp4")

        command = build_ffmpeg_command(config, output)

        self.assertEqual("ffmpeg", command[0])
        self.assertIn("dshow", command)
        self.assertIn("1280x720", command)
        self.assertIn("30", command)
        self.assertIn("video=USB Camera", command)
        self.assertIn("libx264", command)
        self.assertIn("veryfast", command)
        self.assertIn("18", command)
        self.assertIn(str(output), command)

    def test_build_ffmpeg_command_copies_full_quality_preview_by_default(self) -> None:
        config = RecordingConfig(output_dir=Path("D:/captures"))
        output = Path("D:/captures/usbcam_20260605_143209.mp4")

        command = build_ffmpeg_command(config, output)

        self.assertIn("-fflags", command)
        self.assertIn("nobuffer", command)
        self.assertIn("-c:v:1", command)
        self.assertIn("copy", command)
        self.assertNotIn("scale=960:-1", command)
        self.assertNotIn("-vf:v:1", command)
        self.assertEqual("pipe:1", command[-1])

    def test_build_ffmpeg_command_can_disable_preview_pipe(self) -> None:
        config = RecordingConfig(output_dir=Path("D:/captures"), preview_enabled=False)
        output = Path("D:/captures/usbcam_20260605_143209.mp4")

        command = build_ffmpeg_command(config, output)

        self.assertEqual(str(output), command[-1])
        self.assertNotIn("pipe:1", command)
        self.assertNotIn("scale=960:-1", command)

    def test_build_ffplay_command_uses_low_latency_probe_settings(self) -> None:
        command = build_ffplay_command()

        self.assertIn("-probesize", command)
        self.assertIn("32", command)
        self.assertIn("-analyzeduration", command)
        self.assertIn("0", command)
        self.assertIn("-framedrop", command)

    def test_stop_sends_q_to_ffmpeg_before_waiting(self) -> None:
        process = FakeProcess()
        session = FFmpegRecordingSession(process, Path("D:/captures/test.mp4"))

        session.stop(timeout=1.5)

        self.assertEqual([b"q\n"], process.stdin.writes)
        self.assertTrue(process.stdin.flushed)
        self.assertEqual(1.5, process.wait_timeout)
        self.assertFalse(process.terminated)

    def test_format_duration_outputs_hh_mm_ss(self) -> None:
        self.assertEqual("00:00:00", format_duration(0))
        self.assertEqual("00:01:05", format_duration(65))
        self.assertEqual("01:02:03", format_duration(3723))

    def test_resolution_presets_put_fast_capture_first_and_keep_full_resolution(self) -> None:
        self.assertEqual("1280x720", RESOLUTION_PRESETS[0])
        self.assertIn("2560x1440", RESOLUTION_PRESETS)


if __name__ == "__main__":
    unittest.main()
