#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.cantonese_tts import EdgeCantoneseTts, load_cantonese_tts_config
from src.settings import load_environment


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Speak one Cantonese utterance via interrupt/src/cantonese_tts.py.",
    )
    parser.add_argument("text", help="Cantonese text to synthesize and play.")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    load_environment()
    provider = EdgeCantoneseTts(load_cantonese_tts_config())
    if not provider.enabled:
        print("[cantonese-tts] disabled", file=sys.stderr)
        return 2
    if not provider.is_available():
        print("[cantonese-tts] unavailable", file=sys.stderr)
        return 3
    if not provider.synthesize_and_play(args.text):
        print("[cantonese-tts] synthesize_and_play returned false", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
