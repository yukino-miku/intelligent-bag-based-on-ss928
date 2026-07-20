#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from .mr20_radar import MR20RadarWorker, RadarAlert, load_mr20_config
except ImportError:  # Direct execution from the package directory.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from mr20_radar import MR20RadarWorker, RadarAlert, load_mr20_config


def replay_hex_lines(worker: MR20RadarWorker, path: Path) -> list[RadarAlert]:
    events: list[RadarAlert] = []
    original_emit = worker.emit
    worker.emit = lambda event: (events.append(event), original_emit(event))[0]
    for line in path.read_text(encoding="ascii").splitlines():
        text = line.split("#", 1)[0].strip().replace(" ", "")
        if text:
            worker.handle_datagram(
                bytes.fromhex(text),
                (worker.config.source_ip, worker.config.source_port or 0),
            )
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay anonymized MR20 hex datagrams")
    parser.add_argument("--config", required=True)
    parser.add_argument("--radar", default="right_rear")
    parser.add_argument("hex_file", type=Path)
    args = parser.parse_args()
    configs, risk = load_mr20_config(args.config)
    config = next(item for item in configs if item.name == args.radar)
    worker = MR20RadarWorker(config, risk, lambda event: print(json.dumps(event.__dict__, ensure_ascii=True)))
    replay_hex_lines(worker, args.hex_file)
    print(json.dumps(worker.status(), ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
