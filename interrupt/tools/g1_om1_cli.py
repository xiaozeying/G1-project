#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.g1_om1_adapter import G1Om1Adapter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Interrupt-side CLI wrapper for OM1 G1 LED/arm/TTS helpers."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    direct = subparsers.add_parser("direct", help="Execute a direct LED/arm text command.")
    direct.add_argument("text", help="Recognized user text, such as 把灯变为红色 or 向我挥手")

    speak = subparsers.add_parser("speak", help="Speak a short acknowledgement.")
    speak.add_argument("text", help="Text to speak")
    speak.add_argument("--speaker-id", type=int, default=0)
    speak.add_argument("--volume", type=int, default=100)

    led = subparsers.add_parser("led", help="Set a static LED color.")
    led.add_argument("color", help="LED color")

    breathe = subparsers.add_parser("breathe", help="Start a breathing LED effect.")
    breathe.add_argument("color", help="LED color")
    breathe.add_argument("--period", type=float, default=2.0)

    navigate = subparsers.add_parser("navigate", help="Navigate to a saved location label.")
    navigate.add_argument("location", help="Saved location label")

    remember = subparsers.add_parser("remember", help="Remember the current pose as a location label.")
    remember.add_argument("location", help="Location label")
    remember.add_argument("--description", default="")

    subparsers.add_parser("list-locations", help="List saved navigation locations.")
    subparsers.add_parser("start-nav-bridge", help="Start the configured local navigation bridge in the background.")

    subparsers.add_parser("paths", help="Show resolved helper paths.")
    subparsers.add_parser("check", help="Check whether helper paths exist.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    adapter = G1Om1Adapter()

    if args.command == "direct":
        result = adapter.execute_direct_text(args.text)
    elif args.command == "speak":
        result = adapter.speak(
            args.text,
            speaker_id=args.speaker_id,
            volume=args.volume,
        )
    elif args.command == "led":
        result = adapter.set_led(args.color)
    elif args.command == "breathe":
        result = adapter.breathe_led(args.color, period=args.period)
    elif args.command == "navigate":
        result = adapter.navigate_to_location(args.location)
    elif args.command == "remember":
        result = adapter.remember_location(args.location, description=args.description)
    elif args.command == "list-locations":
        result = adapter.list_saved_locations()
    elif args.command == "start-nav-bridge":
        result = adapter.start_navigation_bridge()
    elif args.command == "paths":
        print(json.dumps(adapter.script_paths(), ensure_ascii=False, indent=2))
        return 0
    elif args.command == "check":
        print(json.dumps(adapter.validate_paths(), ensure_ascii=False, indent=2))
        return 0
    else:
        raise AssertionError(f"Unhandled command: {args.command}")

    print(
        json.dumps(
            {
                "ok": result.ok,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "command": list(result.command),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.ok else result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
