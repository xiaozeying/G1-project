#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.settings import load_environment, load_settings
from src.vision_chat import VisionChatConfig, ask_camera_question


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Single-shot camera + Gemini VLM smoke test for interrupt."
    )
    parser.add_argument(
        "question",
        nargs="?",
        default="你前面有什么？",
        help="Visual question to ask.",
    )
    parser.add_argument(
        "--language",
        default="zh-CN",
        choices=["zh-CN", "zh-YUE", "en"],
        help="Reply language hint passed to the VLM prompt.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_environment()
    settings = load_settings(ROOT_DIR / "config.yaml")
    config = VisionChatConfig(
        enabled=settings.vision.enabled,
        api_key=settings.gemini_api_key,
        base_url=settings.vision.base_url,
        model=settings.vision.model,
        preferred_device=settings.vision.preferred_device,
        width=settings.vision.width,
        height=settings.vision.height,
        jpeg_quality=settings.vision.jpeg_quality,
        max_tokens=settings.vision.max_tokens,
        capture_warmup_frames=settings.vision.capture_warmup_frames,
        capture_timeout_s=settings.vision.capture_timeout_s,
    )
    result = ask_camera_question(
        config,
        question=args.question,
        reply_language=args.language,
    )
    if not result.ok:
        print("status: FAIL")
        print(f"error: {result.error}")
        print(f"camera_device: {result.camera_device or '<none>'}")
        return 1
    print("status: OK")
    print(f"camera_device: {result.camera_device}")
    print(f"answer: {result.answer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
