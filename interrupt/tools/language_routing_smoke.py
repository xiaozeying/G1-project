#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.agent import (
    _detect_forced_reply_language,
    _detect_reply_language,
    _preferred_reply_language,
    _remember_reply_language_preference,
)


def _assert_equal(label: str, actual: str | None, expected: str | None) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")
    print(f"OK   {label}: {actual!r}")


def main() -> None:
    print("Language routing smoke test")

    _assert_equal("detect mandarin", _detect_reply_language("今天天气怎么样"), "zh-CN")
    _assert_equal("detect cantonese", _detect_reply_language("你而家识唔识讲广东话"), "zh-YUE")
    _assert_equal("detect english", _detect_reply_language("What can you do for me?"), "en")

    _assert_equal("force cantonese", _detect_forced_reply_language("之后用粤语回答我"), "zh-YUE")
    _assert_equal(
        "force english",
        _detect_forced_reply_language("Please reply in English from now on."),
        "en",
    )
    _assert_equal(
        "return auto",
        _detect_forced_reply_language("恢复自动，跟着我说的话回答"),
        "",
    )

    _remember_reply_language_preference("之后用粤语回答我")
    _assert_equal("preferred after force yue", _preferred_reply_language(), "zh-YUE")
    _remember_reply_language_preference("What can you do for me?")
    _assert_equal("preferred stays forced yue", _preferred_reply_language(), "zh-YUE")
    _remember_reply_language_preference("恢复自动，跟着我说的话回答")
    _remember_reply_language_preference("What can you do for me?")
    _assert_equal("preferred after auto reset", _preferred_reply_language(), "en")

    print("PASS language routing smoke test")


if __name__ == "__main__":
    main()
