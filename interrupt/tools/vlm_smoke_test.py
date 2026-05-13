#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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
    parser.add_argument(
        "--provider",
        default="",
        help="Optional provider override, e.g. gemini_openai_compat or openai_compatible.",
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="Optional OpenAI-compatible base URL override.",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Optional model override.",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="Optional API key override. Leave empty for local no-auth servers.",
    )
    parser.add_argument(
        "--image",
        default="",
        help="Optional static image path override for local validation without a live camera.",
    )
    parser.add_argument(
        "--structured",
        action="store_true",
        help="Request structured observation JSON in addition to the natural-language answer.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_environment()
    settings = load_settings(ROOT_DIR / "config.yaml")
    config = VisionChatConfig(
        enabled=settings.vision.enabled,
        provider=args.provider.strip() or settings.vision.provider,
        api_key=args.api_key.strip() or settings.vision.api_key,
        base_url=args.base_url.strip() or settings.vision.base_url,
        model=args.model.strip() or settings.vision.model,
        image_path=args.image.strip() or settings.vision.image_path,
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
        structured=args.structured,
    )
    if not result.ok:
        print("status: FAIL")
        print(f"provider: {config.provider}")
        print(f"base_url: {config.base_url}")
        print(f"model: {config.model}")
        print(f"image_path: {config.image_path or '<camera>'}")
        print(f"error: {result.error}")
        print(f"camera_device: {result.camera_device or '<none>'}")
        return 1
    print("status: OK")
    print(f"provider: {config.provider}")
    print(f"base_url: {config.base_url}")
    print(f"model: {config.model}")
    print(f"image_path: {config.image_path or '<camera>'}")
    print(f"camera_device: {result.camera_device}")
    print(f"answer: {result.answer}")
    if result.observation is not None:
        print("observation_json:")
        print(json.dumps(result.observation, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
