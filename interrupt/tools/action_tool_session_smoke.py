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
    _normalize_body_action,
    _remember_latest_user_text,
    _remember_reply_language_preference,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test perform_body_action through the same recent-intent guard path as the agent session."
    )
    parser.add_argument("action", nargs="?", default="high wave")
    parser.add_argument(
        "--prime-text",
        default="请挥手",
        help="User utterance used to prime recent-intent guards.",
    )
    parser.add_argument(
        "--language",
        default="zh-CN",
        help="Optional language tag for the primed utterance.",
    )
    return parser


async def _run(action: str, prime_text: str, language: str) -> int:
    effective_prime = prime_text.strip() or "请挥手"
    if language.strip():
        effective_prime = f"<|{language.strip()}|> {effective_prime}"
    _remember_reply_language_preference(effective_prime)
    _remember_latest_user_text(effective_prime)
    assistant = InterruptAssistant()
    normalized_action = _normalize_body_action(action)
    result = await assistant.perform_body_action(normalized_action)
    print(
        json.dumps(
            {
                "action": normalized_action,
                "prime_text": effective_prime,
                "result": result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    return asyncio.run(_run(args.action, args.prime_text, args.language))


if __name__ == "__main__":
    raise SystemExit(main())
