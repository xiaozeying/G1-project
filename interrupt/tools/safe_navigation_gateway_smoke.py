#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.safe_action_gateway import evaluate_navigation_safety
from src.settings import load_environment, load_settings
from src.vision_chat import VisionChatConfig, ask_camera_question


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a structured camera observation and evaluate whether it is safe to start navigation."
    )
    parser.add_argument(
        "--question",
        default="请检查前方空间是否通畅、是否有人离得太近，以及当前画面是否足够清晰。",
    )
    parser.add_argument(
        "--language",
        default="zh-CN",
        choices=["zh-CN", "zh-YUE", "en"],
    )
    parser.add_argument("--provider", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--image", default="")
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
        structured=True,
    )
    if not result.ok:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": result.error,
                    "camera_device": result.camera_device,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    decision = evaluate_navigation_safety(result.observation)
    print(
        json.dumps(
            {
                "ok": True,
                "allowed": decision.allowed,
                "reason_code": decision.reason_code,
                "reason_text": decision.reason_text,
                "camera_device": result.camera_device,
                "observation": result.observation,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
