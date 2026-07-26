from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from smartbag_alert_controller import AudioPlayer  # noqa: E402


class RecordingAudioPlayer(AudioPlayer):
    def __init__(self, audio_root: Path, *, block_first: bool = False) -> None:
        super().__init__(audio_root, skip_pinmux=True)
        self.played: list[str] = []
        self.first_started = threading.Event()
        self.release_first = threading.Event()
        self.block_first = block_first

    def _play(self, clip: str) -> None:
        self.played.append(clip)
        if len(self.played) == 1:
            self.first_started.set()
            if self.block_first:
                self.release_first.wait(timeout=1.0)


class FakeProcess:
    def __init__(self, launched: threading.Event) -> None:
        self.launched = launched
        self.terminated = threading.Event()
        self.completed = threading.Event()
        self.launched.set()

    def poll(self) -> int | None:
        return 0 if self.completed.is_set() else None

    def terminate(self) -> None:
        self.terminated.set()
        self.completed.set()

    def kill(self) -> None:
        self.terminate()

    def communicate(self, input: bytes | None = None, timeout: float | None = None) -> tuple[bytes, bytes]:
        self.completed.set()
        return b"", b""


class AudioPlayerTest(unittest.TestCase):
    def test_pending_audio_keeps_highest_level_and_latest_clip_at_that_level(self) -> None:
        player = RecordingAudioPlayer(Path("unused"), block_first=True)
        player.request("L1")
        player.request("R4")
        player.request("L4")

        player.start()
        self.assertTrue(player.first_started.wait(timeout=1.0))
        try:
            self.assertEqual(player.played, ["L4"])
        finally:
            player.release_first.set()
            player.stop()

    def test_same_level_during_current_playback_is_not_repeated(self) -> None:
        player = RecordingAudioPlayer(Path("unused"), block_first=True)
        player.start()
        player.request("L3")
        self.assertTrue(player.first_started.wait(timeout=1.0))

        player.request("R3")
        player.release_first.set()
        time.sleep(0.1)
        player.stop()

        self.assertEqual(player.played, ["L3"])

    def test_higher_level_waits_for_current_sentence_to_finish(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            audio_root = Path(temp)
            for clip in ("L2", "R4"):
                clip_dir = audio_root / clip
                clip_dir.mkdir()
                (clip_dir / "audio_chn0.aac").write_bytes(b"test")

            launched = [threading.Event(), threading.Event()]
            processes: list[FakeProcess] = []

            def fake_popen(*_args: object, **_kwargs: object) -> FakeProcess:
                process = FakeProcess(launched[len(processes)])
                processes.append(process)
                return process

            player = AudioPlayer(
                audio_root,
                skip_pinmux=True,
                default_sleep_s=0.3,
                default_timeout_s=0.5,
            )
            with patch("smartbag_alert_controller.subprocess.Popen", side_effect=fake_popen):
                try:
                    player.start()
                    player.request("L2")
                    self.assertTrue(launched[0].wait(timeout=1.0))

                    player.request("R4")
                    self.assertFalse(processes[0].terminated.wait(timeout=0.2))
                    processes[0].completed.set()
                    self.assertTrue(launched[1].wait(timeout=1.0))
                finally:
                    player.stop()


if __name__ == "__main__":
    unittest.main()
