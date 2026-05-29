#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.local_text_brain import run_local_text_brain
from src.settings import load_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-test the local text decision brain against the configured Ollama backend."
    )
    parser.add_argument("prompt", help="User text to send to the local text brain.")
    parser.add_argument("--language", default="zh-CN", help="Reply language hint.")
    parser.add_argument(
        "--backend",
        default="",
        help="Optional override for INTERRUPT_AGENT_BACKEND, e.g. local_text_ollama.",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Optional override for INTERRUPT_AGENT_LOCAL_TEXT_MODEL.",
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="Optional override for INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings()
    agent_config = settings.agent
    if args.backend.strip():
        agent_config.backend = args.backend.strip()
    if args.model.strip():
        agent_config.local_text_model = args.model.strip()
    if args.base_url.strip():
        agent_config.local_text_base_url = args.base_url.strip()

    result = run_local_text_brain(
        agent_config,
        user_text=args.prompt,
        language=args.language.strip() or "zh-CN",
    )
    payload = {
        "ok": result.ok,
        "backend": result.backend,
        "model": result.model,
        "text_reply": result.text_reply,
        "tool_calls": [
            {"name": call.name, "arguments": call.arguments} for call in result.tool_calls
        ],
        "error": result.error,
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
