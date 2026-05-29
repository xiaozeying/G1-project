#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.local_text_brain import run_local_text_brain
from src.settings import load_settings


CASES = [
    {
        "name": "mandarin_open_chat",
        "language": "zh-CN",
        "prompt": "我们随便聊聊人工智能。",
        "expect_tool": False,
    },
    {
        "name": "cantonese_open_chat",
        "language": "zh-YUE",
        "prompt": "我哋隨便聊下人工智能。",
        "expect_tool": False,
    },
    {
        "name": "english_open_chat",
        "language": "en",
        "prompt": "Let's casually chat about artificial intelligence.",
        "expect_tool": False,
    },
    {
        "name": "mandarin_led",
        "language": "zh-CN",
        "prompt": "把灯变成蓝色。",
        "expect_tool": True,
        "expected_tool_name": "set_led_color",
    },
    {
        "name": "cantonese_led",
        "language": "zh-YUE",
        "prompt": "幫我將盞燈轉做藍色。",
        "expect_tool": True,
        "expected_tool_name": "set_led_color",
    },
    {
        "name": "english_led",
        "language": "en",
        "prompt": "Please turn the light blue.",
        "expect_tool": True,
        "expected_tool_name": "set_led_color",
    },
]


def _looks_english(text: str) -> bool:
    letters = sum(1 for ch in text if "a" <= ch.lower() <= "z")
    return letters >= 4


def _looks_cantonese(text: str) -> bool:
    markers = ("我哋", "而家", "依家", "咩", "乜", "唔", "喺", "嘅")
    return any(marker in text for marker in markers)


def _language_ok(language: str, text_reply: str) -> bool:
    normalized = (text_reply or "").strip()
    if not normalized:
        return True
    if language == "en":
        return _looks_english(normalized) and not any("\u3400" <= ch <= "\u9fff" for ch in normalized)
    if language == "zh-YUE":
        return _looks_cantonese(normalized)
    if language == "zh-CN":
        return any("\u3400" <= ch <= "\u9fff" for ch in normalized) and not _looks_cantonese(normalized)
    return True


def main() -> int:
    settings = load_settings()
    agent_config = settings.agent
    results: list[dict[str, object]] = []
    failures = 0

    for case in CASES:
        result = run_local_text_brain(
            agent_config,
            user_text=str(case["prompt"]),
            language=str(case["language"]),
        )
        tool_names = [call.name for call in result.tool_calls]
        payload: dict[str, object] = {
            "name": case["name"],
            "language": case["language"],
            "prompt": case["prompt"],
            "ok": result.ok,
            "error": result.error,
            "text_reply": result.text_reply,
            "tool_calls": [
                {"name": call.name, "arguments": call.arguments} for call in result.tool_calls
            ],
        }
        case_ok = bool(result.ok)
        if case.get("expect_tool"):
            expected_tool_name = str(case["expected_tool_name"])
            case_ok = case_ok and expected_tool_name in tool_names
        else:
            case_ok = case_ok and not tool_names and _language_ok(str(case["language"]), result.text_reply)
        payload["case_ok"] = case_ok
        results.append(payload)
        if not case_ok:
            failures += 1

    json.dump(
        {
            "ok": failures == 0,
            "summary": {"total": len(results), "failed": failures, "passed": len(results) - failures},
            "results": results,
        },
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    sys.stdout.write("\n")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
