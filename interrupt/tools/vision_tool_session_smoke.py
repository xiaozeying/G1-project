#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.agent import (
    InterruptAssistant,
    VISION_CHAT_CONFIG,
    _preferred_reply_language,
    _remember_latest_user_text,
    _remember_reply_language_preference,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test the ask_camera_vision tool using the same guard path as the agent session."
    )
    parser.add_argument("question", nargs="?", default="你前面有什么？")
    parser.add_argument(
        "--prime-text",
        default="",
        help="Optional user utterance used to prime recent-intent and reply-language guards.",
    )
    parser.add_argument(
        "--language",
        default="",
        help="Optional explicit language hint. Example: zh-CN, zh-YUE, en.",
    )
    parser.add_argument(
        "--structured",
        action="store_true",
        help="Call the camera tool directly through vision_chat with structured observation enabled.",
    )
    return parser


async def _run(question: str, prime_text: str, language: str, structured: bool) -> int:
    effective_prime = prime_text.strip() or question.strip() or "你前面有什么？"
    if language.strip():
        effective_prime = f"<|{language.strip()}|> {effective_prime}"
    _remember_reply_language_preference(effective_prime)
    _remember_latest_user_text(effective_prime)

    assistant = InterruptAssistant()
    if structured:
        from src.vision_chat import ask_camera_question

        result = await asyncio.to_thread(
            ask_camera_question,
            VISION_CHAT_CONFIG,
            question=question,
            reply_language=_preferred_reply_language(),
            structured=True,
        )
        payload = {
            "question": question,
            "prime_text": effective_prime,
            "preferred_reply_language": _preferred_reply_language(),
            "provider": VISION_CHAT_CONFIG.provider,
            "base_url": VISION_CHAT_CONFIG.base_url,
            "model": VISION_CHAT_CONFIG.model,
            "image_path": VISION_CHAT_CONFIG.image_path or "<camera>",
            "answer": result.answer,
            "observation": result.observation,
            "ok": result.ok,
            "error": result.error,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if result.ok else 1
    answer = await assistant.ask_camera_vision(question=question)
    payload = {
        "question": question,
        "prime_text": effective_prime,
        "preferred_reply_language": _preferred_reply_language(),
        "provider": VISION_CHAT_CONFIG.provider,
        "base_url": VISION_CHAT_CONFIG.base_url,
        "model": VISION_CHAT_CONFIG.model,
        "image_path": VISION_CHAT_CONFIG.image_path or "<camera>",
        "answer": answer,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return asyncio.run(_run(args.question, args.prime_text, args.language, args.structured))


if __name__ == "__main__":
    raise SystemExit(main())
