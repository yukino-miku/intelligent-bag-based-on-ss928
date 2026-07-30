#!/usr/bin/env python3
"""Generate repository-owned SS928 warning tones without third-party samples."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


TONE_SPECS = {
    "L1": (720, 0.20),
    "L2": (820, 0.28),
    "L3": (920, 0.36),
    "L4": (1020, 0.48),
    "R1": (1180, 0.20),
    "R2": (1280, 0.28),
    "R3": (1380, 0.36),
    "R4": (1480, 0.48),
    "bad": (520, 0.35),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("09_deliverables/board_deploy/assets/audio"),
    )
    args = parser.parse_args()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required to generate alert tones")
    for name, (frequency, duration) in TONE_SPECS.items():
        destination = args.output_root / name
        destination.mkdir(parents=True, exist_ok=True)
        output = destination / "audio_chn0.aac"
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
                "-ac",
                "2",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                str(output),
            ],
            check=True,
        )
        (destination / "play_hint.txt").write_text(
            "\n".join(
                [
                    f"duration_seconds={duration:.3f}",
                    "sleep_seconds=3",
                    "timeout_seconds=11",
                    f"remote_dir=/root/smartbag/audio/{name}",
                    "remote_command:",
                    f"cd /root/smartbag/audio/{name} || exit 1",
                    "bspmm 0x102F010C 0x1202",
                    "bspmm 0x102F0108 0x1102",
                    "bspmm 0x102F0104 0x1202",
                    "{ sleep 3; printf '\\n\\n'; } | timeout 11 /opt/sample/audio/sample_audio 2",
                    "",
                ]
            ),
            encoding="utf-8",
            newline="\n",
        )
        print(f"generated {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
