#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def load_pwm_class() -> object:
    candidates = [
        Path("/root/smartbag/controller"),
        Path(__file__).resolve().parents[2] / "06_software/board_runtime/smartbag_alert_controller",
    ]
    for candidate in candidates:
        if (candidate / "lights.py").exists():
            sys.path.insert(0, str(candidate))
            break
    from lights import LinuxSysfsPwm
    return LinuxSysfsPwm


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover and safely probe one PWM sysfs channel")
    parser.add_argument("--root", default="/sys/class/pwm")
    parser.add_argument("--chip", default="auto")
    parser.add_argument("--channel", type=int, required=True)
    parser.add_argument("--period-ns", type=int, default=1_000_000)
    parser.add_argument("--duty-percent", type=int, default=10)
    parser.add_argument("--hold-s", type=float, default=0.5)
    parser.add_argument("--apply", action="store_true", help="Actually enable the output; otherwise discovery only")
    args = parser.parse_args()
    pwm = load_pwm_class()(Path(args.root))
    chip = pwm.resolve_chip(args.chip, args.channel)
    result = {"chips": pwm.list_chips(), "resolved_chip": chip, "channel": args.channel}
    if not args.apply:
        print(json.dumps(result, sort_keys=True))
        return 0
    pwm.setup_channel(chip, args.channel, args.period_ns)
    try:
        pwm.set_output(chip, args.channel, args.period_ns, args.duty_percent, True)
        time.sleep(max(0.0, args.hold_s))
    finally:
        pwm.set_output(chip, args.channel, args.period_ns, 0, False)
    result.update({"period_ns": args.period_ns, "duty_percent": args.duty_percent, "physical_response": "operator_confirmation_required"})
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
