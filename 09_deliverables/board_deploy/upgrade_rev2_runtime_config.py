#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Upgrade controller config for Rev2 autonomous runtime")
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    data = json.loads(args.config.read_text(encoding="utf-8"))
    paths = data.setdefault("paths", {})
    paths["python"] = "/root/smartbag/venv/bin/python"
    runtime = data.setdefault("vision_runtime", {})
    runtime["mode"] = "alternating_single_model"
    alternating = data.setdefault("alternating_camera", {})
    alternating["enabled"] = True
    alternating.setdefault("backend", "v4l2_stream_toggle")
    alternating.setdefault("video_gateway_enabled", True)
    alternating.setdefault("serve_bind", "0.0.0.0")
    alternating.setdefault("serve_port", 8080)
    audio = data.setdefault("audio", {})
    audio["enabled"] = True
    audio.setdefault("root", "/root/smartbag/audio")
    backup = args.config.with_name(
        args.config.name + ".bak." + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    )
    shutil.copy2(args.config, backup)
    args.config.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"config": str(args.config), "backup": str(backup)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
