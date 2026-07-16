#!/usr/bin/env python3
"""Prepare an audio file for SS928 MAX98357 sample_audio playback."""

from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
from pathlib import Path


def tool_path(name: str, env_name: str) -> str:
    configured = os.environ.get(env_name)
    if configured:
        return configured
    found = shutil.which(name)
    if not found:
        raise SystemExit(
            f"Missing {name}. Install ffmpeg or set {env_name} to the executable path."
        )
    return found


def run(command: list[str]) -> None:
    rendered = " ".join(f'"{part}"' if " " in part else part for part in command)
    print("+ " + rendered)
    subprocess.run(command, check=True)


def probe_duration_seconds(ffprobe: str | None, source: Path) -> float | None:
    if not ffprobe:
        return None
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def write_play_hint(path: Path, duration: float | None, remote_dir: str) -> None:
    if duration is None:
        sleep_seconds = 20
        timeout_seconds = 30
    else:
        sleep_seconds = max(3, math.ceil(duration) + 2)
        timeout_seconds = sleep_seconds + 8

    lines = [
        f"duration_seconds={duration:.3f}" if duration is not None else "duration_seconds=unknown",
        f"sleep_seconds={sleep_seconds}",
        f"timeout_seconds={timeout_seconds}",
        f"remote_dir={remote_dir}",
        "remote_command:",
        f"cd {remote_dir} || exit 1",
        "bspmm 0x102F010C 0x1202",
        "bspmm 0x102F0108 0x1102",
        "bspmm 0x102F0104 0x1202",
        f"{{ sleep {sleep_seconds}; printf '\\n\\n'; }} | timeout {timeout_seconds} /opt/sample/audio/sample_audio 2",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert an MP3/WAV/etc. into board-ready audio_chn0.aac and 48k stereo PCM."
    )
    parser.add_argument("source", type=Path, help="Input audio file, such as test.mp3")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("09_deliverables") / "board_deploy" / "assets" / "audio" / "custom",
        help="Output folder under the board deployment audio assets by default.",
    )
    parser.add_argument("--remote-dir", default="/root/smartbag/audio/custom")
    parser.add_argument("--aac-bitrate", default="96k")
    parser.add_argument("--no-pcm", action="store_true", help="Only create audio_chn0.aac")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Input audio file not found: {source}")

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg = tool_path("ffmpeg", "FFMPEG")
    ffprobe = os.environ.get("FFPROBE") or shutil.which("ffprobe")
    duration = probe_duration_seconds(ffprobe, source)

    aac_out = out_dir / "audio_chn0.aac"
    run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-c:a",
            "aac",
            "-b:a",
            args.aac_bitrate,
            str(aac_out),
        ]
    )

    pcm_out = None
    if not args.no_pcm:
        pcm_out = out_dir / f"{source.stem}_48k_s16le_stereo.pcm"
        run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-vn",
                "-ac",
                "2",
                "-ar",
                "48000",
                "-f",
                "s16le",
                str(pcm_out),
            ]
        )

    hint_out = out_dir / "play_hint.txt"
    write_play_hint(hint_out, duration, args.remote_dir)

    print(f"audio_chn0_aac={aac_out}")
    if pcm_out:
        print(f"pcm_s16le_48k_stereo={pcm_out}")
    print(f"play_hint={hint_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
