from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse

from google.genai import types as google_types
from livekit.agents.llm import function_tool
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, JobRequest, cli
from livekit.api import AccessToken, TokenVerifier, VideoGrants
from livekit.plugins import google

from src.console_audio_compat import apply_console_audio_compat_patch
from src.g1_om1_adapter import G1Om1Adapter
from src.integrations import build_mcp_servers, log_integration_summary
from src.news import query_news
from src.speech_feedback import SpeechFeedbackRouter
from src.settings import load_settings
from src.weather import query_weather


LOGGER = logging.getLogger("interrupt.agent")


def _should_apply_console_audio_patch(argv: list[str] | None = None) -> bool:
    args = list(argv if argv is not None else sys.argv[1:])
    if os.getenv("INTERRUPT_DISABLE_CONSOLE_AUDIO_COMPAT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return False
    if "--help" in args or "--show-completion" in args or "--install-completion" in args:
        return False
    if "console" not in args:
        return False
    if "--text" in args:
        return False
    if os.getenv("INTERRUPT_TEXT_MODE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    return True


if _should_apply_console_audio_patch():
    apply_console_audio_compat_patch()

SETTINGS = load_settings()
G1_ADAPTER = G1Om1Adapter()
SPEECH_FEEDBACK = SpeechFeedbackRouter(SETTINGS.feedback, G1_ADAPTER)
REALTIME_PREFIX_PADDING_MS = int(
    os.getenv("INTERRUPT_REALTIME_PREFIX_PADDING_MS", "500").strip() or "500"
)
USER_AWAY_TIMEOUT_S = max(1.0, SETTINGS.agent.user_away_timeout_ms / 1000.0)
FRONTGATE_SESSION_EXIT_SIGNAL_FILE = (
    os.getenv("INTERRUPT_FRONTGATE_SESSION_EXIT_SIGNAL_FILE", "").strip()
)
ACTIVE_LISTEN_LED_COLOR = os.getenv(
    "INTERRUPT_ACTIVE_LISTEN_LED_COLOR",
    "green",
).strip() or "green"
ACTIVE_LISTEN_LED_PERIOD_S = float(
    os.getenv("INTERRUPT_ACTIVE_LISTEN_LED_PERIOD_S", "2.0").strip() or "2.0"
)
ACTIVE_LISTEN_LED_RESTORE_DELAY_S = float(
    os.getenv("INTERRUPT_ACTIVE_LISTEN_LED_RESTORE_DELAY_S", "1.5").strip() or "1.5"
)
ENABLE_ACTIVE_LISTEN_LED_RESTORE = os.getenv(
    "INTERRUPT_ENABLE_ACTIVE_LISTEN_LED_RESTORE",
    "1",
).strip().lower() not in {"0", "false", "no", "off"}
ENABLE_LOCAL_TOOL_PRE_ACK = os.getenv(
    "INTERRUPT_ENABLE_LOCAL_TOOL_PRE_ACK",
    "1",
).strip().lower() not in {"0", "false", "no", "off"}
ENABLE_LOCAL_QUERY_PRE_ACK = os.getenv(
    "INTERRUPT_ENABLE_LOCAL_QUERY_PRE_ACK",
    "0",
).strip().lower() not in {"0", "false", "no", "off"}
ENABLE_PATCHED_JOB_TOKEN = os.getenv(
    "INTERRUPT_AGENT_PATCH_JOB_TOKEN",
    "1",
).strip().lower() not in {"0", "false", "no", "off"}
LOCAL_TOOL_PRE_ACK_SUPPRESS_WINDOW_S = float(
    os.getenv("INTERRUPT_LOCAL_TOOL_PRE_ACK_SUPPRESS_WINDOW_S", "8.0").strip() or "8.0"
)
LOCAL_COMMAND_ACK_SUPPRESS_WINDOW_S = float(
    os.getenv("INTERRUPT_LOCAL_COMMAND_ACK_SUPPRESS_WINDOW_S", "8.0").strip() or "8.0"
)
LOCAL_COMMAND_FAILURE_SUPPRESS_WINDOW_S = float(
    os.getenv("INTERRUPT_LOCAL_COMMAND_FAILURE_SUPPRESS_WINDOW_S", "12.0").strip() or "12.0"
)
ACTION_BUSY_LED_COLOR = os.getenv(
    "INTERRUPT_ACTION_BUSY_LED_COLOR",
    "purple",
).strip() or "purple"
IDLE_LED_COLOR = os.getenv(
    "INTERRUPT_FRONTGATE_IDLE_LED",
    "blue",
).strip() or "blue"
ACTION_BUSY_HOLD_S = float(
    os.getenv("INTERRUPT_ACTION_BUSY_HOLD_S", "0.0").strip() or "0.0"
)
_ACTIVE_SESSION_ACCEPTING_COMMANDS = threading.Event()
_ACTION_EXECUTING = threading.Event()
_SESSION_STATE_LOCK = threading.Lock()
_LAST_AGENT_STATE = "initializing"
_LAST_USER_STATE = ""
_RECENT_LOCAL_TOOL_ACKS: dict[str, float] = {}
_RECENT_LOCAL_TOOL_ACKS_LOCK = threading.Lock()
_RECENT_LOCAL_COMMAND_ACKS: dict[str, float] = {}
_RECENT_LOCAL_COMMAND_ACKS_LOCK = threading.Lock()
_RECENT_LOCAL_COMMAND_SUCCESSES: dict[str, float] = {}
_RECENT_LOCAL_COMMAND_SUCCESSES_LOCK = threading.Lock()
_RECENT_FASTPATH_COMMANDS: dict[str, float] = {}
_RECENT_FASTPATH_COMMANDS_LOCK = threading.Lock()
FASTPATH_DUPLICATE_WINDOW_S = float(
    os.getenv("INTERRUPT_FASTPATH_DUPLICATE_WINDOW_S", "8.0").strip() or "8.0"
)
TOOL_INTENT_GUARD_WINDOW_S = float(
    os.getenv("INTERRUPT_TOOL_INTENT_GUARD_WINDOW_S", "20.0").strip() or "20.0"
)
PARTIAL_FASTPATH_MIN_CHARS = int(
    os.getenv("INTERRUPT_PARTIAL_FASTPATH_MIN_CHARS", "2").strip() or "2"
)
_LAST_USER_TEXT_LOCK = threading.Lock()
_LAST_USER_TEXT = ""
_LAST_USER_TEXT_AT = 0.0
_LAST_EFFECTIVE_USER_INPUT_AT_LOCK = threading.Lock()
_LAST_EFFECTIVE_USER_INPUT_AT = time.monotonic()
_LANGUAGE_STATE_LOCK = threading.Lock()
_LAST_DETECTED_USER_LANGUAGE = "zh-CN"
_FORCED_REPLY_LANGUAGE = ""
_RECENT_INTENT_LOCK = threading.Lock()
_RECENT_INTENTS: dict[str, dict[str, float]] = {}

REPLY_LANGUAGE_MANDARIN = "zh-CN"
REPLY_LANGUAGE_CANTONESE = "zh-YUE"
REPLY_LANGUAGE_ENGLISH = "en"


def _livekit_proxy() -> str | None:
    parsed = urlparse(SETTINGS.livekit.url)
    host = parsed.hostname or ""
    netloc = parsed.netloc or host
    if host in {"127.0.0.1", "localhost", "::1"}:
        return None
    try:
        if ipaddress.ip_address(host).is_private:
            return None
    except ValueError:
        pass
    # Respect NO_PROXY/no_proxy so LAN LiveKit can stay direct while Gemini
    # still uses the outbound proxy configured in the environment.
    if urllib.request.proxy_bypass(host) or urllib.request.proxy_bypass(netloc):
        return None
    return os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")


def _env_float(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        LOGGER.warning("invalid float env ignored: %s=%r", name, raw)
        return None


def _worker_load_override() -> float | None:
    forced = _env_float("INTERRUPT_AGENT_FORCE_LOAD")
    if forced is None:
        return None
    return max(0.0, min(forced, 0.99))


def _normalize_led_color(color: str) -> str:
    normalized = (color or "").strip().lower()
    color_map = {
        "red": "red",
        "红": "red",
        "紅": "red",
        "green": "green",
        "绿": "green",
        "綠": "green",
        "blue": "blue",
        "蓝": "blue",
        "藍": "blue",
        "yellow": "yellow",
        "黄": "yellow",
        "黃": "yellow",
        "purple": "purple",
        "紫": "purple",
        "cyan": "cyan",
        "青": "cyan",
        "white": "white",
        "白": "white",
        "orange": "orange",
        "橙": "orange",
        "off": "off",
        "关闭": "off",
        "关灯": "off",
        "熄灯": "off",
    }
    return color_map.get(normalized, normalized)


def _normalize_body_action(action: str) -> str:
    normalized = (action or "").strip().lower()
    action_map = {
        "挥手": "high wave",
        "挥个手": "high wave",
        "揮個手": "high wave",
        "揮个手": "high wave",
        "wave": "high wave",
        "high wave": "high wave",
        "招手": "high wave",
        "回个手": "high wave",
        "回個手": "high wave",
        "回个手啦": "high wave",
        "回個手拉": "high wave",
        "回個手啦": "high wave",
        "握手": "shake hand",
        "握个手": "shake hand",
        "握個手": "shake hand",
        "握個手啦": "shake hand",
        "握个手啦": "shake hand",
        "我个手": "shake hand",
        "我個手": "shake hand",
        "我個手拉": "shake hand",
        "我個手啦": "shake hand",
        "回手": "high wave",
        "會手": "high wave",
        "会手": "high wave",
        "汇手": "high wave",
        "匯手": "high wave",
        "喔手": "high wave",
        "我手": "high wave",
        "shake hand": "shake hand",
        "handshake": "shake hand",
        "鼓掌": "clap",
        "拍手": "clap",
        "clap": "clap",
        "击掌": "high five",
        "擊掌": "high five",
        "high five": "high five",
        "比心": "heart",
        "heart": "heart",
    }
    return action_map.get(normalized, normalized)


_CJK_CHAR_RE = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_CJK_LATIN_DIGIT_RE = re.compile(rf"(?<=[{_CJK_CHAR_RE}A-Za-z0-9])\s+(?=[{_CJK_CHAR_RE}A-Za-z0-9])")
_PUNCT_SPACING_RE = re.compile(r"\s+([，。！？；：,.!?;:])")
_TTS_BREAK_PUNCT_RE = re.compile(r"[，,、；;：:]")
_TTS_DROP_PUNCT_RE = re.compile(r"[“”\"'`()\[\]{}<>《》【】]")


def _normalize_assistant_text(text: str) -> str:
    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return ""
    normalized = _CJK_LATIN_DIGIT_RE.sub("", normalized)
    normalized = _PUNCT_SPACING_RE.sub(r"\1", normalized)
    return normalized.strip()


def _normalize_tts_text(text: str) -> str:
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return ""
    normalized = _TTS_BREAK_PUNCT_RE.sub(" ", normalized)
    normalized = _TTS_DROP_PUNCT_RE.sub("", normalized)
    normalized = normalized.replace("...", "。").replace("…", "。")
    normalized = re.sub(r"[。]{2,}", "。", normalized)
    normalized = re.sub(r"[！？]{2,}", lambda m: m.group(0)[0], normalized)
    normalized = " ".join(normalized.split()).strip()
    return normalized


def _is_noise_only_transcript(text: str) -> bool:
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return True
    folded = re.sub(r"[^\w\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff<>]+", "", normalized).lower()
    if not folded:
        return True
    return folded in {
        "<noise>",
        "noise",
        "noises",
        "backgroundnoise",
        "static",
        "<unk>",
        "unk",
        "silence",
        "empty",
    }


def _contains_cantonese_markers(text: str) -> bool:
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return False
    markers = (
        "咩",
        "乜",
        "冇",
        "唔",
        "喺",
        "佢",
        "哋",
        "嘅",
        "咗",
        "嚟",
        "啱",
        "咁",
        "噉",
        "呢",
        "呀",
        "喎",
        "㗎",
        "咯",
        "有冇",
        "有咩",
        "可唔可以",
        "幫我",
        "边个",
        "邊個",
        "而家",
        "依家",
    )
    return any(marker in normalized for marker in markers)


def _looks_like_english_text(text: str) -> bool:
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return False
    ascii_letters = sum(1 for ch in normalized if "a" <= ch.lower() <= "z")
    cjk_chars = sum(1 for ch in normalized if "\u3400" <= ch <= "\u9fff")
    common_tokens = (
        "the",
        "and",
        "is",
        "are",
        "you",
        "can",
        "please",
        "what",
        "where",
        "how",
        "why",
        "hello",
        "thanks",
    )
    lowered = normalized.lower()
    if any(token in lowered for token in common_tokens):
        return True
    return ascii_letters >= 4 and ascii_letters >= cjk_chars * 2


def _extract_explicit_language_tag(text: str) -> str | None:
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return None
    lowered = normalized.lower()
    tag_aliases = {
        "<|zh|>": REPLY_LANGUAGE_MANDARIN,
        "<|cmn|>": REPLY_LANGUAGE_MANDARIN,
        "<|zh-cn|>": REPLY_LANGUAGE_MANDARIN,
        "<|yue|>": REPLY_LANGUAGE_CANTONESE,
        "<|zh-yue|>": REPLY_LANGUAGE_CANTONESE,
        "<|en|>": REPLY_LANGUAGE_ENGLISH,
        "<|en-us|>": REPLY_LANGUAGE_ENGLISH,
        "<|en-gb|>": REPLY_LANGUAGE_ENGLISH,
    }
    for tag, language in tag_aliases.items():
        if tag in lowered:
            return language
    return None


def _detect_reply_language(text: str) -> str:
    tagged = _extract_explicit_language_tag(text)
    if tagged:
        return tagged
    if _contains_cantonese_markers(text):
        return REPLY_LANGUAGE_CANTONESE
    if _looks_like_english_text(text):
        return REPLY_LANGUAGE_ENGLISH
    normalized = _normalize_assistant_text(text)
    if any("\u3400" <= ch <= "\u9fff" for ch in normalized):
        return REPLY_LANGUAGE_MANDARIN
    return REPLY_LANGUAGE_MANDARIN


def _detect_forced_reply_language(text: str) -> str | None:
    normalized = _normalize_assistant_text(text)
    lowered = normalized.lower()
    compact = lowered.replace(" ", "")
    if not normalized:
        return None

    def _matches_any(phrases: tuple[str, ...]) -> bool:
        for phrase in phrases:
            lowered_phrase = phrase.lower()
            if lowered_phrase in lowered:
                return True
            if " " in lowered_phrase and lowered_phrase.replace(" ", "") in compact:
                return True
        return False

    auto_phrases = (
        "自动切换语言",
        "自适应语言",
        "自动识别语言",
        "跟着我说的话回答",
        "按我说的语言回答",
        "恢复自动",
        "切回自动",
        "auto reply",
        "auto language",
        "use my language",
        "follow my language",
        "reply in my language",
    )
    if _matches_any(auto_phrases):
        return ""

    cantonese_phrases = (
        "用粤语回答",
        "用廣東話回答",
        "用广东话回答",
        "讲粤语",
        "講粵語",
        "讲广东话",
        "講廣東話",
        "用白话回答",
        "用廣東話覆",
        "reply in cantonese",
        "answer in cantonese",
        "speak cantonese",
    )
    if _matches_any(cantonese_phrases):
        return REPLY_LANGUAGE_CANTONESE

    english_phrases = (
        "用英语回答",
        "用英文回答",
        "讲英语",
        "講英語",
        "说英语",
        "說英語",
        "英文回答",
        "英语回答",
        "reply in english",
        "answer in english",
        "speak english",
        "english please",
    )
    if _matches_any(english_phrases):
        return REPLY_LANGUAGE_ENGLISH

    mandarin_phrases = (
        "用普通话回答",
        "用普通話回答",
        "用中文回答",
        "讲普通话",
        "講普通話",
        "说普通话",
        "說普通話",
        "讲中文",
        "講中文",
        "说中文",
        "說中文",
        "reply in chinese",
        "answer in chinese",
        "speak chinese",
        "mandarin please",
    )
    if _matches_any(mandarin_phrases):
        return REPLY_LANGUAGE_MANDARIN
    return None


def _localized_text(
    mandarin: str,
    cantonese: str | None = None,
    english: str | None = None,
    *,
    language: str | None = None,
) -> str:
    target = language or _preferred_reply_language()
    localized = {
        REPLY_LANGUAGE_MANDARIN: mandarin,
        REPLY_LANGUAGE_CANTONESE: cantonese or mandarin,
        REPLY_LANGUAGE_ENGLISH: english or mandarin,
    }
    return localized.get(target, mandarin)


def _remember_reply_language_preference(text: str) -> None:
    forced = _detect_forced_reply_language(text)
    detected = _detect_reply_language(text)
    with _LANGUAGE_STATE_LOCK:
        global _FORCED_REPLY_LANGUAGE, _LAST_DETECTED_USER_LANGUAGE
        if forced is not None:
            _FORCED_REPLY_LANGUAGE = forced
            LOGGER.info("reply language mode updated: forced=%r by text=%r", forced or "auto", text)
        _LAST_DETECTED_USER_LANGUAGE = detected
    LOGGER.info(
        "reply language detected: detected=%s effective=%s text=%r",
        detected,
        _preferred_reply_language(),
        text,
    )


def _preferred_reply_language() -> str:
    with _LANGUAGE_STATE_LOCK:
        if _FORCED_REPLY_LANGUAGE:
            return _FORCED_REPLY_LANGUAGE
        return _LAST_DETECTED_USER_LANGUAGE or REPLY_LANGUAGE_MANDARIN


def _record_local_tool_ack(text: str) -> None:
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return
    now = time.monotonic()
    with _RECENT_LOCAL_TOOL_ACKS_LOCK:
        expired = [
            key
            for key, ts in _RECENT_LOCAL_TOOL_ACKS.items()
            if now - ts > LOCAL_TOOL_PRE_ACK_SUPPRESS_WINDOW_S
        ]
        for key in expired:
            _RECENT_LOCAL_TOOL_ACKS.pop(key, None)
        _RECENT_LOCAL_TOOL_ACKS[normalized] = now


def _was_recently_pre_acked(text: str) -> bool:
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return False
    now = time.monotonic()
    with _RECENT_LOCAL_TOOL_ACKS_LOCK:
        ts = _RECENT_LOCAL_TOOL_ACKS.get(normalized)
        if ts is None:
            return False
        if now - ts > LOCAL_TOOL_PRE_ACK_SUPPRESS_WINDOW_S:
            _RECENT_LOCAL_TOOL_ACKS.pop(normalized, None)
            return False
        return True


def _speak_local_tool_ack(text: str) -> None:
    normalized = _normalize_tts_text(text)
    if not ENABLE_LOCAL_TOOL_PRE_ACK or not normalized:
        return
    if SPEECH_FEEDBACK.speak_local_tool_ack(
        normalized,
        normalize_tts_text=_normalize_tts_text,
    ):
        _record_local_tool_ack(normalized)
    return


def _record_local_command_ack(kind: str, payload: str) -> None:
    normalized_payload = _normalize_assistant_text(payload)
    if not kind or not normalized_payload:
        return
    now = time.monotonic()
    key = f"{kind}:{normalized_payload}"
    with _RECENT_LOCAL_COMMAND_ACKS_LOCK:
        expired = [
            item
            for item, ts in _RECENT_LOCAL_COMMAND_ACKS.items()
            if now - ts > LOCAL_COMMAND_ACK_SUPPRESS_WINDOW_S
        ]
        for item in expired:
            _RECENT_LOCAL_COMMAND_ACKS.pop(item, None)
        _RECENT_LOCAL_COMMAND_ACKS[key] = now


def _was_recent_local_command_acked(text: str) -> bool:
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return False
    candidates: list[str] = []
    action = _extract_body_action(normalized)
    if action:
        candidates.append(f"action:{_normalize_assistant_text(action)}")
    if _looks_like_led_command(normalized):
        color = _extract_led_color(normalized)
        if color:
            candidates.append(f"led:{_normalize_assistant_text(color)}")
    if not candidates:
        return False
    now = time.monotonic()
    with _RECENT_LOCAL_COMMAND_ACKS_LOCK:
        expired = [
            item
            for item, ts in _RECENT_LOCAL_COMMAND_ACKS.items()
            if now - ts > LOCAL_COMMAND_ACK_SUPPRESS_WINDOW_S
        ]
        for item in expired:
            _RECENT_LOCAL_COMMAND_ACKS.pop(item, None)
        return any(item in _RECENT_LOCAL_COMMAND_ACKS for item in candidates)


def _record_local_command_success(kind: str, payload: str) -> None:
    normalized_payload = _normalize_assistant_text(payload)
    if not kind or not normalized_payload:
        return
    now = time.monotonic()
    key = f"{kind}:{normalized_payload}"
    with _RECENT_LOCAL_COMMAND_SUCCESSES_LOCK:
        expired = [
            item
            for item, ts in _RECENT_LOCAL_COMMAND_SUCCESSES.items()
            if now - ts > LOCAL_COMMAND_FAILURE_SUPPRESS_WINDOW_S
        ]
        for item in expired:
            _RECENT_LOCAL_COMMAND_SUCCESSES.pop(item, None)
        _RECENT_LOCAL_COMMAND_SUCCESSES[key] = now


def _recent_local_command_successes() -> list[str]:
    now = time.monotonic()
    with _RECENT_LOCAL_COMMAND_SUCCESSES_LOCK:
        expired = [
            item
            for item, ts in _RECENT_LOCAL_COMMAND_SUCCESSES.items()
            if now - ts > LOCAL_COMMAND_FAILURE_SUPPRESS_WINDOW_S
        ]
        for item in expired:
            _RECENT_LOCAL_COMMAND_SUCCESSES.pop(item, None)
        return list(_RECENT_LOCAL_COMMAND_SUCCESSES.keys())


def _looks_like_failure_reply(text: str) -> bool:
    normalized = _normalize_assistant_text(text).lower()
    if not normalized:
        return False
    failure_tokens = (
        "抱歉",
        "无法",
        "不能",
        "没法",
        "未能",
        "失败",
        "系统限制",
        "请您谅解",
    )
    return any(token in normalized for token in failure_tokens)


def _should_suppress_conflicting_failure_reply(text: str) -> bool:
    normalized = _normalize_assistant_text(text)
    if not normalized or not _looks_like_failure_reply(normalized):
        return False
    successes = _recent_local_command_successes()
    if not successes:
        return False
    action = _extract_body_action(normalized)
    if action and f"action:{_normalize_assistant_text(action)}" in successes:
        return True
    if _looks_like_led_command(normalized):
        color = _extract_led_color(normalized)
        if color and f"led:{_normalize_assistant_text(color)}" in successes:
            return True
    if len(successes) == 1 and action is None and not _looks_like_led_command(normalized):
        return True
    return False


def _remember_fastpath_command(key: str) -> bool:
    now = time.monotonic()
    with _RECENT_FASTPATH_COMMANDS_LOCK:
        expired = [
            item
            for item, ts in _RECENT_FASTPATH_COMMANDS.items()
            if now - ts > FASTPATH_DUPLICATE_WINDOW_S
        ]
        for item in expired:
            _RECENT_FASTPATH_COMMANDS.pop(item, None)
        if key in _RECENT_FASTPATH_COMMANDS:
            return False
        _RECENT_FASTPATH_COMMANDS[key] = now
        return True


def _remember_latest_user_text(text: str) -> None:
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return
    with _LAST_USER_TEXT_LOCK:
        global _LAST_USER_TEXT, _LAST_USER_TEXT_AT
        _LAST_USER_TEXT = normalized
        _LAST_USER_TEXT_AT = time.monotonic()
    _remember_recent_user_intents(normalized)


def _mark_effective_user_input(text: str) -> None:
    normalized = _normalize_assistant_text(text)
    if not normalized or _is_noise_only_transcript(normalized):
        return
    with _LAST_EFFECTIVE_USER_INPUT_AT_LOCK:
        global _LAST_EFFECTIVE_USER_INPUT_AT
        _LAST_EFFECTIVE_USER_INPUT_AT = time.monotonic()


def _reset_effective_user_input_timer() -> None:
    with _LAST_EFFECTIVE_USER_INPUT_AT_LOCK:
        global _LAST_EFFECTIVE_USER_INPUT_AT
        _LAST_EFFECTIVE_USER_INPUT_AT = time.monotonic()


def _seconds_since_last_effective_user_input() -> float:
    with _LAST_EFFECTIVE_USER_INPUT_AT_LOCK:
        return max(0.0, time.monotonic() - _LAST_EFFECTIVE_USER_INPUT_AT)


def _latest_user_text() -> tuple[str, float]:
    with _LAST_USER_TEXT_LOCK:
        return _LAST_USER_TEXT, _LAST_USER_TEXT_AT


def _remember_recent_user_intents(text: str) -> None:
    now = time.monotonic()
    with _RECENT_INTENT_LOCK:
        for kind, payloads in list(_RECENT_INTENTS.items()):
            expired = [
                payload
                for payload, ts in payloads.items()
                if now - ts > TOOL_INTENT_GUARD_WINDOW_S
            ]
            for payload in expired:
                payloads.pop(payload, None)
            if not payloads:
                _RECENT_INTENTS.pop(kind, None)
        action = _extract_body_action(text)
        if action:
            _RECENT_INTENTS.setdefault("action", {})[action] = now
            _RECENT_INTENTS.setdefault("direct", {})[action] = now
        if _looks_like_led_command(text):
            color = _extract_led_color(text)
            if color:
                _RECENT_INTENTS.setdefault("led", {})[color] = now
                _RECENT_INTENTS.setdefault("direct", {})[color] = now
        direct = _classify_fastpath_command(text)
        if direct is not None:
            _RECENT_INTENTS.setdefault("direct", {})[direct[1]] = now


def _recent_intents(kind: str) -> dict[str, float]:
    with _RECENT_INTENT_LOCK:
        return dict(_RECENT_INTENTS.get(kind, {}))


def _is_recent_user_intent_valid(kind: str, payload: str) -> bool:
    latest_text, latest_at = _latest_user_text()
    now = time.monotonic()
    if latest_text and now - latest_at <= TOOL_INTENT_GUARD_WINDOW_S:
        if kind == "action":
            matched = _extract_body_action(latest_text)
            if matched == payload:
                return True
        elif kind == "led":
            if _looks_like_led_command(latest_text):
                matched = _extract_led_color(latest_text)
                if matched == payload:
                    return True
        elif kind == "direct" and _classify_fastpath_command(latest_text) is not None:
            return True
    remembered_payloads = _recent_intents(kind)
    if not remembered_payloads:
        return False
    if kind == "action":
        remembered_at = remembered_payloads.get(payload, 0.0)
        return bool(remembered_at and now - remembered_at <= TOOL_INTENT_GUARD_WINDOW_S)
    if kind == "led":
        remembered_at = remembered_payloads.get(payload, 0.0)
        return bool(remembered_at and now - remembered_at <= TOOL_INTENT_GUARD_WINDOW_S)
    if kind == "direct":
        remembered_at = remembered_payloads.get(payload, 0.0)
        if remembered_at and now - remembered_at <= TOOL_INTENT_GUARD_WINDOW_S:
            return True
        action = _extract_body_action(payload)
        action_at = remembered_payloads.get(action or "", 0.0)
        if action and action_at and now - action_at <= TOOL_INTENT_GUARD_WINDOW_S:
            return True
        color = _extract_led_color(payload)
        color_at = remembered_payloads.get(color or "", 0.0)
        if color and color_at and now - color_at <= TOOL_INTENT_GUARD_WINDOW_S:
            return True
        return False
    return False


def _pop_recent_fastpath_command(key: str) -> bool:
    now = time.monotonic()
    with _RECENT_FASTPATH_COMMANDS_LOCK:
        ts = _RECENT_FASTPATH_COMMANDS.get(key)
        if ts is None:
            return False
        if now - ts > FASTPATH_DUPLICATE_WINDOW_S:
            _RECENT_FASTPATH_COMMANDS.pop(key, None)
            return False
        _RECENT_FASTPATH_COMMANDS.pop(key, None)
        return True


def _action_ack_text(action: str) -> str:
    language = _preferred_reply_language()
    ack_map = {
        REPLY_LANGUAGE_MANDARIN: {
            "high wave": "好的，正在挥手。",
            "shake hand": "好的，正在握手。",
            "clap": "好的，正在鼓掌。",
            "high five": "好的，正在击掌。",
            "heart": "好的，正在比心。",
            "__default__": "好的，正在执行动作。",
        },
        REPLY_LANGUAGE_CANTONESE: {
            "high wave": "好啊，依家同你挥手。",
            "shake hand": "好啊，依家同你握手。",
            "clap": "好啊，依家同你鼓掌。",
            "high five": "好啊，依家同你擊掌。",
            "heart": "好啊，依家同你比心。",
            "__default__": "好啊，依家幫你做動作。",
        },
        REPLY_LANGUAGE_ENGLISH: {
            "high wave": "Okay, waving now.",
            "shake hand": "Okay, shaking hands now.",
            "clap": "Okay, clapping now.",
            "high five": "Okay, high five now.",
            "heart": "Okay, making a heart now.",
            "__default__": "Okay, doing that action now.",
        },
    }
    localized = ack_map.get(language, ack_map[REPLY_LANGUAGE_MANDARIN])
    return localized.get(action, localized["__default__"])


def _led_ack_text(color: str) -> str:
    language = _preferred_reply_language()
    ack_map = {
        REPLY_LANGUAGE_MANDARIN: {
            "red": "好的，正在切换为红灯。",
            "green": "好的，正在切换为绿灯。",
            "blue": "好的，正在切换为蓝灯。",
            "yellow": "好的，正在切换为黄灯。",
            "purple": "好的，正在切换为紫灯。",
            "cyan": "好的，正在切换为青灯。",
            "white": "好的，正在切换为白灯。",
            "orange": "好的，正在切换为橙灯。",
            "off": "好的，正在关闭灯光。",
            "__default__": "好的，正在切换灯光。",
        },
        REPLY_LANGUAGE_CANTONESE: {
            "red": "好啊，依家轉做紅燈。",
            "green": "好啊，依家轉做綠燈。",
            "blue": "好啊，依家轉做藍燈。",
            "yellow": "好啊，依家轉做黃燈。",
            "purple": "好啊，依家轉做紫燈。",
            "cyan": "好啊，依家轉做青燈。",
            "white": "好啊，依家轉做白燈。",
            "orange": "好啊，依家轉做橙燈。",
            "off": "好啊，依家熄燈。",
            "__default__": "好啊，依家幫你轉燈。",
        },
        REPLY_LANGUAGE_ENGLISH: {
            "red": "Okay, switching to red.",
            "green": "Okay, switching to green.",
            "blue": "Okay, switching to blue.",
            "yellow": "Okay, switching to yellow.",
            "purple": "Okay, switching to purple.",
            "cyan": "Okay, switching to cyan.",
            "white": "Okay, switching to white.",
            "orange": "Okay, switching to orange.",
            "off": "Okay, turning the lights off.",
            "__default__": "Okay, switching the lights now.",
        },
    }
    localized = ack_map.get(language, ack_map[REPLY_LANGUAGE_MANDARIN])
    return localized.get(color, localized["__default__"])


def _query_ack_text(text: str) -> str | None:
    normalized = (text or "").strip().lower()
    if not normalized:
        return None
    language = _preferred_reply_language()
    if _looks_like_weather_query(normalized):
        if language == REPLY_LANGUAGE_CANTONESE:
            return "好啊，我而家講天氣。"
        if language == REPLY_LANGUAGE_ENGLISH:
            return "Okay, I'll give you the weather."
        return "好的，我来播报天气。"
    if _looks_like_news_query(normalized):
        if language == REPLY_LANGUAGE_CANTONESE:
            return "好啊，我而家講新聞。"
        if language == REPLY_LANGUAGE_ENGLISH:
            return "Okay, I'll give you the news."
        return "好的，我来播报新闻。"
    if any(
        token in normalized
        for token in (
            "自我介绍",
            "自我介紹",
            "介绍一下你自己",
            "介紹一下你自己",
            "介绍你自己",
            "介紹你自己",
            "你是谁",
            "你是誰",
            "who are you",
        )
    ):
        if language == REPLY_LANGUAGE_CANTONESE:
            return "好啊，我先介紹下自己。"
        if language == REPLY_LANGUAGE_ENGLISH:
            return "Okay, let me introduce myself first."
        return "好的，我先介绍一下自己。"
    return None


def _looks_like_weather_query(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return any(token in normalized for token in ("天气", "天氣", "weather"))


def _looks_like_news_query(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return any(token in normalized for token in ("新闻", "新聞", "news", "热点", "熱點", "时事", "時事"))


def _is_recent_query_intent_valid(kind: str) -> bool:
    latest_text, latest_at = _latest_user_text()
    now = time.monotonic()
    if not latest_text or now - latest_at > TOOL_INTENT_GUARD_WINDOW_S:
        return False
    if kind == "weather":
        return _looks_like_weather_query(latest_text)
    if kind == "news":
        return _looks_like_news_query(latest_text)
    return False


def _looks_like_action_command(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    keywords = (
        "挥手",
        "招手",
        "握手",
        "回手",
        "會手",
        "会手",
        "汇手",
        "匯手",
        "喔手",
        "我手",
        "鼓掌",
        "拍手",
        "击掌",
        "擊掌",
        "比心",
        "wave",
        "high wave",
        "shake hand",
        "clap",
        "high five",
        "heart",
    )
    return any(keyword in normalized for keyword in keywords)


def _extract_body_action(text: str) -> str | None:
    normalized = (text or "").strip().lower()
    if not normalized:
        return None
    ordered_keywords = (
        ("high wave", "high wave"),
        ("wave", "high wave"),
        ("挥个手", "high wave"),
        ("揮個手", "high wave"),
        ("揮个手", "high wave"),
        ("挥手", "high wave"),
        ("揮手", "high wave"),
        ("招手", "high wave"),
        ("回个手", "high wave"),
        ("回個手", "high wave"),
        ("回個手拉", "high wave"),
        ("回個手啦", "high wave"),
        ("shake hand", "shake hand"),
        ("handshake", "shake hand"),
        ("握個手", "shake hand"),
        ("握个手", "shake hand"),
        ("握個手啦", "shake hand"),
        ("握个手啦", "shake hand"),
        ("握手", "shake hand"),
        ("我個手", "shake hand"),
        ("我个手", "shake hand"),
        ("我個手拉", "shake hand"),
        ("我個手啦", "shake hand"),
        ("回手", "high wave"),
        ("會手", "high wave"),
        ("会手", "high wave"),
        ("汇手", "high wave"),
        ("匯手", "high wave"),
        ("喔手", "high wave"),
        ("我手", "high wave"),
        ("clap", "clap"),
        ("鼓掌", "clap"),
        ("拍手", "clap"),
        ("high five", "high five"),
        ("机长", "high five"),
        ("機長", "high five"),
        ("击掌", "high five"),
        ("擊掌", "high five"),
        ("heart", "heart"),
        ("比心", "heart"),
    )
    for keyword, action in ordered_keywords:
        if keyword in normalized:
            return action
    return None


def _extract_led_color(text: str) -> str | None:
    normalized = (text or "").strip().lower()
    if not normalized:
        return None
    ordered_colors = (
        ("深蓝", "blue"),
        ("深藍", "blue"),
        ("蓝色", "blue"),
        ("藍色", "blue"),
        ("蓝灯", "blue"),
        ("藍燈", "blue"),
        ("蓝", "blue"),
        ("藍", "blue"),
        ("红色", "red"),
        ("紅色", "red"),
        ("红灯", "red"),
        ("紅燈", "red"),
        ("红", "red"),
        ("紅", "red"),
        ("绿色", "green"),
        ("綠色", "green"),
        ("绿灯", "green"),
        ("綠燈", "green"),
        ("绿", "green"),
        ("綠", "green"),
        ("紫色", "purple"),
        ("紫灯", "purple"),
        ("紫", "purple"),
        ("黄色", "yellow"),
        ("黃色", "yellow"),
        ("黄灯", "yellow"),
        ("黃燈", "yellow"),
        ("黄", "yellow"),
        ("黃", "yellow"),
        ("橙色", "orange"),
        ("橙灯", "orange"),
        ("橙", "orange"),
        ("白色", "white"),
        ("白灯", "white"),
        ("白", "white"),
        ("青色", "cyan"),
        ("青灯", "cyan"),
        ("青", "cyan"),
        ("关闭", "off"),
        ("关灯", "off"),
        ("熄灯", "off"),
        ("off", "off"),
    )
    for keyword, color in ordered_colors:
        if keyword in normalized:
            return color
    return None


def _looks_like_led_followup(text: str) -> bool:
    normalized = _normalize_assistant_text(text).lower()
    if not normalized:
        return False
    color = _extract_led_color(normalized)
    if color is None:
        return False
    residue = normalized
    removable_tokens = (
        "深蓝", "深藍", "蓝色", "藍色", "蓝灯", "藍燈", "蓝", "藍",
        "红色", "紅色", "红灯", "紅燈", "红", "紅",
        "绿色", "綠色", "绿灯", "綠燈", "绿", "綠",
        "紫色", "紫灯", "紫",
        "黄色", "黃色", "黄灯", "黃燈", "黄", "黃",
        "橙色", "橙灯", "橙",
        "白色", "白灯", "白",
        "青色", "青灯", "青",
        "关闭", "关灯", "熄灯", "off",
        "再", "再来", "再來", "一次", "一下", "一遍", "一變", "一变",
        "變", "变", "成", "為", "为", "吧", "呀", "啊", "呢", "啦", "喇",
        "請", "请", "幫我", "帮我", "把", "給我", "给我",
        "燈", "灯", "led", "颜色", "顏色",
    )
    for token in removable_tokens:
        residue = residue.replace(token, "")
    residue = re.sub(r"[\s，。！？；：,.!?;:、]+", "", residue)
    return not residue


def _looks_like_led_command(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    color = _extract_led_color(normalized)
    if color is None:
        return False
    command_cues = (
        "灯",
        "燈",
        "led",
        "颜色",
        "顏色",
        "变成",
        "變成",
        "变为",
        "變為",
        "调成",
        "調成",
        "改成",
        "換成",
        "换成",
        "设成",
        "設成",
        "变",
        "變",
    )
    if any(cue in normalized for cue in command_cues):
        return True
    return _looks_like_led_followup(normalized)


def _classify_fastpath_command(text: str) -> tuple[str, str, str] | None:
    action = _extract_body_action(text)
    if action is not None:
        return ("action", action, f"action:{action}")
    if _looks_like_led_command(text):
        color = _extract_led_color(text)
        if color is not None:
            return ("led", color, f"led:{color}")
    return None


def _set_active_session_accepting_commands(enabled: bool) -> None:
    if enabled:
        _ACTIVE_SESSION_ACCEPTING_COMMANDS.set()
        return
    _ACTIVE_SESSION_ACCEPTING_COMMANDS.clear()


def _can_accept_commands() -> bool:
    with _SESSION_STATE_LOCK:
        return (
            not _ACTION_EXECUTING.is_set()
            and _LAST_AGENT_STATE == "listening"
            and _LAST_USER_STATE == "listening"
        )


def _refresh_accepting_commands() -> None:
    _set_active_session_accepting_commands(_can_accept_commands())


def _set_action_executing(enabled: bool) -> None:
    if enabled:
        _ACTION_EXECUTING.set()
    else:
        _ACTION_EXECUTING.clear()
    _refresh_accepting_commands()


def _update_session_states(*, user_state: str | None = None, agent_state: str | None = None) -> None:
    global _LAST_AGENT_STATE, _LAST_USER_STATE
    with _SESSION_STATE_LOCK:
        if user_state is not None:
            _LAST_USER_STATE = user_state
        if agent_state is not None:
            _LAST_AGENT_STATE = agent_state
    _refresh_accepting_commands()


def _set_action_busy_led() -> None:
    if not G1_ADAPTER.available:
        return
    result = G1_ADAPTER.set_led(ACTION_BUSY_LED_COLOR)
    LOGGER.info(
        "action busy LED set: color=%s ok=%s stdout=%r stderr=%r",
        ACTION_BUSY_LED_COLOR,
        result.ok,
        result.stdout,
        result.stderr,
    )


def _set_idle_led(reason: str) -> None:
    if not G1_ADAPTER.available:
        return
    result = G1_ADAPTER.set_led(IDLE_LED_COLOR)
    LOGGER.info(
        "idle LED set: reason=%s color=%s ok=%s stdout=%r stderr=%r",
        reason,
        IDLE_LED_COLOR,
        result.ok,
        result.stdout,
        result.stderr,
    )


def _signal_frontgate_session_exit(reason: str) -> None:
    path = FRONTGATE_SESSION_EXIT_SIGNAL_FILE
    if not path:
        return
    try:
        Path(path).write_text(reason)
        LOGGER.info("frontgate session exit signal written: path=%s reason=%s", path, reason)
    except Exception:
        LOGGER.exception("failed to write frontgate session exit signal: path=%s reason=%s", path, reason)


async def _execute_led_color_local(color: str, *, source: str) -> str:
    if not G1_ADAPTER.available:
        return "G1 LED tool unavailable"
    _record_local_command_ack("led", color)
    await asyncio.to_thread(_speak_local_tool_ack, _led_ack_text(color))
    result = await asyncio.to_thread(G1_ADAPTER.set_led, color)
    LOGGER.info(
        "local LED command executed: source=%s color=%s ok=%s rc=%s stdout=%r stderr=%r",
        source,
        color,
        result.ok,
        result.returncode,
        result.stdout,
        result.stderr,
    )
    if result.ok:
        _record_local_command_success("led", color)
        _resume_active_listen_led_delayed(f"{source}_set_led_color")
        return result.stdout or f"led color set to {color}"
    return f"LED command failed: {result.stderr or result.stdout or result.returncode}"


async def _execute_action_local(action: str, *, source: str) -> str:
    if not G1_ADAPTER.available:
        return "G1 action tool unavailable"
    _set_action_executing(True)
    try:
        _record_local_command_ack("action", action)
        await asyncio.to_thread(_set_action_busy_led)
        await asyncio.to_thread(_speak_local_tool_ack, _action_ack_text(action))
        result = await asyncio.to_thread(G1_ADAPTER.execute_direct_text, action)
        LOGGER.info(
            "local action command executed: source=%s action=%s ok=%s rc=%s stdout=%r stderr=%r",
            source,
            action,
            result.ok,
            result.returncode,
            result.stdout,
            result.stderr,
        )
        if result.ok:
            _record_local_command_success("action", action)
            await _complete_action_window(f"{source}_perform_body_action")
            return result.stdout or f"action executed: {action}"
        return f"Action command failed: {result.stderr or result.stdout or result.returncode}"
    finally:
        if _ACTION_EXECUTING.is_set():
            _set_action_executing(False)


async def _execute_direct_text_local(text: str, *, source: str) -> str:
    if not G1_ADAPTER.available:
        return "G1 direct command tool unavailable"
    if _looks_like_action_command(text):
        action = _extract_body_action(text) or _normalize_body_action(text)
        return await _execute_action_local(action, source=source)
    result = await asyncio.to_thread(G1_ADAPTER.execute_direct_text, text)
    LOGGER.info(
        "local direct text command executed: source=%s text=%r ok=%s rc=%s stdout=%r stderr=%r",
        source,
        text,
        result.ok,
        result.returncode,
        result.stdout,
        result.stderr,
    )
    if result.ok:
        _resume_active_listen_led_delayed(f"{source}_execute_robot_command_text")
        return result.stdout or "direct command executed"
    return f"Direct command failed: {result.stderr or result.stdout or result.returncode}"


async def _complete_action_window(reason: str) -> None:
    if ACTION_BUSY_HOLD_S > 0:
        await asyncio.sleep(ACTION_BUSY_HOLD_S)
    _set_action_executing(False)
    _resume_active_listen_led_delayed(reason)


def _resume_active_listen_led_delayed(reason: str) -> None:
    if not ENABLE_ACTIVE_LISTEN_LED_RESTORE or not G1_ADAPTER.available:
        return

    def _worker() -> None:
        if ACTIVE_LISTEN_LED_RESTORE_DELAY_S > 0:
            time.sleep(ACTIVE_LISTEN_LED_RESTORE_DELAY_S)
        deadline = time.monotonic() + float(
            os.getenv("INTERRUPT_ACTIVE_LISTEN_LED_RESTORE_TIMEOUT_S", "15.0").strip() or "15.0"
        )
        poll_s = float(os.getenv("INTERRUPT_ACTIVE_LISTEN_LED_RESTORE_POLL_S", "0.2").strip() or "0.2")
        while time.monotonic() < deadline:
            if _ACTIVE_SESSION_ACCEPTING_COMMANDS.is_set():
                break
            time.sleep(max(0.05, poll_s))
        if not _ACTIVE_SESSION_ACCEPTING_COMMANDS.is_set():
            LOGGER.info(
                "skip active listen LED restore: session not accepting commands before timeout, reason=%s agent_state=%s user_state=%s",
                reason,
                _LAST_AGENT_STATE,
                _LAST_USER_STATE,
            )
            return
        result = G1_ADAPTER.breathe_led(
            ACTIVE_LISTEN_LED_COLOR,
            period=ACTIVE_LISTEN_LED_PERIOD_S,
        )
        LOGGER.info(
            "active listen LED restore: reason=%s ok=%s rc=%s stdout=%r stderr=%r",
            reason,
            result.ok,
            result.returncode,
            result.stdout,
            result.stderr,
        )
        if result.ok:
            return
        fallback = G1_ADAPTER.set_led(ACTIVE_LISTEN_LED_COLOR)
        LOGGER.warning(
            "active listen LED breathe failed, fallback static LED: reason=%s ok=%s rc=%s stdout=%r stderr=%r",
            reason,
            fallback.ok,
            fallback.returncode,
            fallback.stdout,
            fallback.stderr,
        )

    threading.Thread(
        target=_worker,
        name=f"interrupt-active-led-{reason}",
        daemon=True,
    ).start()


class InterruptAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=_effective_instructions())

    @function_tool(
        name="set_led_color",
        description="Set the robot LED to a static color for an explicit user request.",
    )
    async def set_led_color(self, color: str) -> str:
        """
        Set the robot LED to a static color.

        Args:
            color: One of red, green, blue, yellow, purple, cyan, white, orange, off.
        """
        normalized_color = _normalize_led_color(color)
        if _pop_recent_fastpath_command(f"led:{normalized_color}"):
            LOGGER.info("skip duplicate LED tool execution after fastpath: color=%s", normalized_color)
            return f"led color already handled locally: {normalized_color}"
        if not _is_recent_user_intent_valid("led", normalized_color):
            latest_text, _ = _latest_user_text()
            LOGGER.warning(
                "reject LED tool execution due to mismatched latest user intent: color=%s latest_user_text=%r",
                normalized_color,
                latest_text,
            )
            return f"ignored mismatched led intent for {normalized_color}"
        return await _execute_led_color_local(normalized_color, source="tool")

    @function_tool(
        name="perform_body_action",
        description="Trigger a predefined G1 upper-body action when the user asks the robot to gesture.",
    )
    async def perform_body_action(self, action: str) -> str:
        """
        Trigger a predefined upper-body action.

        Args:
            action: One of high wave, shake hand, clap, high five, heart.
        """
        normalized_action = _normalize_body_action(action)
        if _pop_recent_fastpath_command(f"action:{normalized_action}"):
            LOGGER.info("skip duplicate action tool execution after fastpath: action=%s", normalized_action)
            return f"action already handled locally: {normalized_action}"
        if not _is_recent_user_intent_valid("action", normalized_action):
            latest_text, _ = _latest_user_text()
            LOGGER.warning(
                "reject action tool execution due to mismatched latest user intent: action=%s latest_user_text=%r",
                normalized_action,
                latest_text,
            )
            return f"ignored mismatched action intent for {normalized_action}"
        return await _execute_action_local(normalized_action, source="tool")

    @function_tool(
        name="execute_robot_command_text",
        description="Execute a simple robot LED or arm command from normalized text when structured tools are not sufficient.",
    )
    async def execute_robot_command_text(self, text: str) -> str:
        """
        Execute a normalized direct robot command.

        Args:
            text: A concise normalized command such as 把LED灯变为红色 or 向我挥手.
        """
        classification = _classify_fastpath_command(text)
        if classification is not None and _pop_recent_fastpath_command(classification[2]):
            LOGGER.info("skip duplicate direct command tool execution after fastpath: key=%s", classification[2])
            return f"direct command already handled locally: {classification[1]}"
        if classification is not None and not _is_recent_user_intent_valid(classification[0], classification[1]):
            latest_text, _ = _latest_user_text()
            LOGGER.warning(
                "reject direct robot command tool execution due to mismatched latest user intent: text=%r classification=%s latest_user_text=%r",
                text,
                classification,
                latest_text,
            )
            return f"ignored mismatched direct command intent for {classification[1]}"
        return await _execute_direct_text_local(text, source="tool")

    @function_tool(
        name="get_weather",
        description="Get the current weather for a city or region in Chinese.",
    )
    async def get_weather(self, location: str) -> str:
        """
        Get current weather summary.

        Args:
            location: City or region name, such as 广州, 深圳, Shanghai.
        """
        if not _is_recent_query_intent_valid("weather"):
            latest_text, _ = _latest_user_text()
            LOGGER.warning(
                "reject weather tool execution due to mismatched latest user intent: location=%r latest_user_text=%r",
                location,
                latest_text,
            )
            return _localized_text(
                "刚才没有听到明确的天气请求，我先不查询天气。",
                "啱啱未聽到明確嘅天氣要求，我而家先唔查天氣。",
                "I didn't hear a clear weather request just now, so I won't check the weather yet.",
            )
        try:
            result = await asyncio.to_thread(
                query_weather,
                location,
                language=_preferred_reply_language(),
            )
        except (URLError, OSError) as exc:
            LOGGER.warning("local weather query failed: location=%r error=%s", location, exc)
            return _localized_text(
                "抱歉，当前天气查询暂时不可用。",
                "唔好意思，而家天氣查詢暫時用唔到。",
                "Sorry, the weather service is temporarily unavailable right now.",
            )
        if not result.ok:
            LOGGER.warning(
                "local weather query failed: location=%r error=%s",
                location,
                result.error,
            )
            return _localized_text(
                "抱歉，当前天气查询暂时不可用。",
                "唔好意思，而家天氣查詢暫時用唔到。",
                "Sorry, the weather service is temporarily unavailable right now.",
            )
        LOGGER.info("local weather query succeeded: location=%r summary=%r", location, result.summary)
        return result.summary

    @function_tool(
        name="get_news",
        description="Get current Chinese news headlines for a topic or top headlines.",
    )
    async def get_news(self, topic: str = "") -> str:
        """
        Get current news headlines.

        Args:
            topic: Optional topic such as 热点新闻, 科技新闻, 深圳新闻.
        """
        if not _is_recent_query_intent_valid("news"):
            latest_text, _ = _latest_user_text()
            LOGGER.warning(
                "reject news tool execution due to mismatched latest user intent: topic=%r latest_user_text=%r",
                topic,
                latest_text,
            )
            return _localized_text(
                "刚才没有听到明确的新闻请求，我先不查询新闻。",
                "啱啱未聽到明確嘅新聞要求，我而家先唔查新聞。",
                "I didn't hear a clear news request just now, so I won't check the news yet.",
            )
        try:
            result = await asyncio.to_thread(
                query_news,
                topic,
                language=_preferred_reply_language(),
            )
        except (URLError, OSError) as exc:
            LOGGER.warning("news query failed: topic=%r error=%s", topic, exc)
            return _localized_text(
                "抱歉，当前新闻查询暂时不可用。",
                "唔好意思，而家新聞查詢暫時用唔到。",
                "Sorry, the news service is temporarily unavailable right now.",
            )
        except Exception as exc:
            LOGGER.warning("news query failed: topic=%r error=%s", topic, exc)
            return _localized_text(
                "抱歉，当前新闻查询暂时不可用。",
                "唔好意思，而家新聞查詢暫時用唔到。",
                "Sorry, the news service is temporarily unavailable right now.",
            )
        if not result.ok:
            LOGGER.warning("news query failed: topic=%r error=%s", topic, result.error)
            return _localized_text(
                "抱歉，当前新闻查询暂时不可用。",
                "唔好意思，而家新聞查詢暫時用唔到。",
                "Sorry, the news service is temporarily unavailable right now.",
            )
        LOGGER.info("news query succeeded: topic=%r summary=%r", topic, result.summary)
        return result.summary

def _effective_instructions() -> str:
    ack = SETTINGS.agent.interruption_acknowledgement.strip()
    extra = (
        "\n\n语言与打断交互规则：\n"
        "1. 默认跟随用户最近一轮输入所使用的语言回答；用户说普通话就用普通话，用户说粤语/广东话就用粤语，用户说英语就用英语。\n"
        "2. 只有当用户明确要求切换回复语言时，才暂时固定使用该语言；当用户要求恢复自动或按他说的语言回答时，恢复自动跟随。\n"
        "3. 当用户在你说话时插话，立即停止当前回答，优先听用户新的话。\n"
        f"4. 如果用户的打断意图是让你停下、暂停、闭嘴、等一下、先别说了，请只做一句很短的确认回复：普通话可用“{ack}”；粤语和英语也要用对应语言表达同样意思。\n"
        "5. 不要为这类打断重复解释，也不要继续之前那段回答。\n"
    )
    tool_extra = ""
    if G1_ADAPTER.available:
        tool_extra = (
            "\n\n机器人控制规则：\n"
            "1. 当用户明确要求变灯色、关灯、挥手、握手、鼓掌、击掌、比心等动作时，优先调用工具执行，不要只停留在口头回答。\n"
            "2. 对 LED 优先使用 set_led_color；对明确动作优先使用 perform_body_action。\n"
            "3. 如果用户命令不够标准，但仍明显是在控制灯或上身动作，可使用 execute_robot_command_text。\n"
            "4. 用户询问天气时，优先调用 get_weather 获取实时天气，不要假装已经联网成功。\n"
            "5. 用户询问新闻、热点新闻、科技新闻等时，优先调用 get_news 获取最新新闻，不要直接说拿不到。\n"
            "6. 工具执行成功后，用一句简短确认告知用户已经开始执行或已经完成，并保持和用户当前语言一致。\n"
        )
    return SETTINGS.agent.instructions.rstrip() + extra + tool_extra


def _build_realtime_input_config() -> google_types.RealtimeInputConfig:
    start_sensitivity = os.getenv(
        "INTERRUPT_REALTIME_START_SENSITIVITY",
        "HIGH",
    ).strip().upper()
    end_sensitivity = os.getenv(
        "INTERRUPT_REALTIME_END_SENSITIVITY",
        "HIGH",
    ).strip().upper()
    activity_handling = os.getenv(
        "INTERRUPT_REALTIME_ACTIVITY_HANDLING",
        "START_OF_ACTIVITY_INTERRUPTS",
    ).strip().upper()
    start_map = {
        "HIGH": google_types.StartSensitivity.START_SENSITIVITY_HIGH,
        "LOW": google_types.StartSensitivity.START_SENSITIVITY_LOW,
        "UNSPECIFIED": google_types.StartSensitivity.START_SENSITIVITY_UNSPECIFIED,
    }
    end_map = {
        "HIGH": google_types.EndSensitivity.END_SENSITIVITY_HIGH,
        "LOW": google_types.EndSensitivity.END_SENSITIVITY_LOW,
        "UNSPECIFIED": google_types.EndSensitivity.END_SENSITIVITY_UNSPECIFIED,
    }
    activity_map = {
        "START_OF_ACTIVITY_INTERRUPTS": google_types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
        "NO_INTERRUPTION": google_types.ActivityHandling.NO_INTERRUPTION,
        "UNSPECIFIED": google_types.ActivityHandling.ACTIVITY_HANDLING_UNSPECIFIED,
    }
    return google_types.RealtimeInputConfig(
        automatic_activity_detection=google_types.AutomaticActivityDetection(
            disabled=False,
            start_of_speech_sensitivity=start_map.get(
                start_sensitivity,
                google_types.StartSensitivity.START_SENSITIVITY_HIGH,
            ),
            end_of_speech_sensitivity=end_map.get(
                end_sensitivity,
                google_types.EndSensitivity.END_SENSITIVITY_HIGH,
            ),
            prefix_padding_ms=REALTIME_PREFIX_PADDING_MS,
            silence_duration_ms=SETTINGS.agent.max_endpointing_delay_ms,
        ),
        activity_handling=activity_map.get(
            activity_handling,
            google_types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
        ),
        turn_coverage=google_types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY,
    )


def _build_session() -> AgentSession:
    mcp_servers = build_mcp_servers(SETTINGS)
    if not mcp_servers:
        LOGGER.warning("未配置可用 MCP/HTTP 实时工具；天气走本地接口，新闻走 RSS 直连，其他外部实时数据能力有限。")
    effective_instructions = _effective_instructions()
    model_kwargs = {
        "api_key": SETTINGS.gemini_api_key,
        "model": SETTINGS.agent.model,
        "voice": SETTINGS.agent.voice,
        "instructions": effective_instructions,
        "input_audio_transcription": google_types.AudioTranscriptionConfig()
        if SETTINGS.agent.enable_input_transcription
        else None,
        "output_audio_transcription": google_types.AudioTranscriptionConfig()
        if SETTINGS.agent.enable_output_transcription
        else None,
        "realtime_input_config": _build_realtime_input_config(),
    }
    if SETTINGS.agent.language and SETTINGS.agent.language not in {"zh-CN"}:
        model_kwargs["language"] = SETTINGS.agent.language

    realtime_model = google.realtime.RealtimeModel(**model_kwargs)
    turn_handling = {
        "endpointing": {
            "min_delay": SETTINGS.agent.min_endpointing_delay_ms / 1000,
            "max_delay": SETTINGS.agent.max_endpointing_delay_ms / 1000,
        },
        "interruption": {
            "enabled": SETTINGS.agent.allow_interruptions,
            "mode": SETTINGS.agent.interruption_mode,
            "min_duration": SETTINGS.agent.min_interruption_duration_ms / 1000,
            "min_words": 0,
            "resume_false_interruption": False,
            "false_interruption_timeout": SETTINGS.agent.false_interruption_timeout_ms / 1000,
            "discard_audio_if_uninterruptible": True,
        },
    }
    return AgentSession(
        llm=realtime_model,
        mcp_servers=mcp_servers,
        turn_handling=turn_handling,
        aec_warmup_duration=SETTINGS.agent.aec_warmup_duration_ms / 1000,
        user_away_timeout=USER_AWAY_TIMEOUT_S,
    )


def _mirror_assistant_text_to_om1(text: str) -> None:
    SPEECH_FEEDBACK.speak_assistant_reply(
        text,
        normalize_tts_text=_normalize_tts_text,
    )


def _mirror_assistant_text_to_om1_async(text: str) -> None:
    SPEECH_FEEDBACK.speak_assistant_reply_async(
        text,
        normalize_tts_text=_normalize_tts_text,
    )


def _wire_debug_events(session: AgentSession) -> None:
    interrupted_while_speaking = {"value": False}
    mirrored_texts: set[str] = set()
    rt_hooks_bound = {"value": False}
    loop = asyncio.get_running_loop()
    idle_shutdown_started = {"value": False}
    _reset_effective_user_input_timer()

    async def _monitor_user_input_idle() -> None:
        while True:
            await asyncio.sleep(1.0)
            if idle_shutdown_started["value"]:
                return
            idle_s = _seconds_since_last_effective_user_input()
            if idle_s < USER_AWAY_TIMEOUT_S:
                continue
            if session.agent_state not in {"listening", "initializing"}:
                continue
            if _LAST_USER_STATE == "speaking":
                continue
            idle_shutdown_started["value"] = True
            threading.Thread(
                target=_set_idle_led,
                args=("user_input_idle",),
                name="interrupt-idle-led-input-idle",
                daemon=True,
            ).start()
            _signal_frontgate_session_exit("user_input_idle")
            LOGGER.info(
                "no effective user input for %.1fs, shutting down session to return frontgate to wake mode",
                idle_s,
            )
            session.shutdown(drain=False)
            return

    loop.create_task(_monitor_user_input_idle())

    async def _try_handle_robot_fastpath(text: str) -> None:
        classification = _classify_fastpath_command(text)
        if classification is None:
            return
        kind, payload, dedupe_key = classification
        if not _remember_fastpath_command(dedupe_key):
            LOGGER.info("skip duplicate local robot fastpath: key=%s text=%r", dedupe_key, text)
            return
        LOGGER.info(
            "matched local robot fastpath: kind=%s payload=%s key=%s text=%r",
            kind,
            payload,
            dedupe_key,
            text,
        )
        try:
            if session.agent_state != "listening":
                await session.interrupt(force=True)
        except Exception:
            LOGGER.exception("failed to interrupt session before local fastpath execution")
        if kind == "action":
            asyncio.create_task(_execute_action_local(payload, source="fastpath"))
            return
        if kind == "led":
            asyncio.create_task(_execute_led_color_local(payload, source="fastpath"))
            return

    async def _try_handle_local_query_ack(text: str) -> None:
        if not ENABLE_LOCAL_QUERY_PRE_ACK:
            return
        ack_text = _query_ack_text(text)
        if not ack_text:
            return
        await asyncio.to_thread(_speak_local_tool_ack, ack_text)

    def _mirror_once(text: str) -> None:
        normalized = _normalize_assistant_text(text)
        if not normalized or normalized in mirrored_texts:
            return
        if _should_suppress_conflicting_failure_reply(normalized):
            LOGGER.info("跳过 assistant 冲突失败播报: 最近本地命令已成功 text=%r", normalized)
            mirrored_texts.add(normalized)
            return
        if _was_recent_local_command_acked(normalized):
            LOGGER.info("跳过 assistant 镜像播报: 本地动作/灯光前置播报已处理 text=%r", normalized)
            mirrored_texts.add(normalized)
            return
        if _was_recently_pre_acked(normalized):
            LOGGER.info("跳过 assistant 镜像播报: 已做前置播报 text=%r", normalized)
            mirrored_texts.add(normalized)
            return
        mirrored_texts.add(normalized)
        LOGGER.info("准备异步镜像 assistant 回复到 OM1: text=%r", normalized)
        _mirror_assistant_text_to_om1_async(normalized)

    def _bind_rt_session_hooks() -> None:
        if rt_hooks_bound["value"]:
            return

        activity = getattr(session, "_activity", None)
        rt_session = getattr(activity, "_rt_session", None) if activity is not None else None
        if rt_session is None:
            return

        @rt_session.on("remote_item_added")
        def _on_remote_item_added(ev: object) -> None:
            item = getattr(ev, "item", None)
            role = getattr(item, "role", "")
            text = getattr(item, "text_content", None)
            LOGGER.info("realtime remote_item_added: role=%s text=%r", role, text)
            if role == "assistant" and text:
                _mirror_once(text)

        rt_hooks_bound["value"] = True
        LOGGER.info("已绑定 realtime session 调试钩子。")

    @session.on("user_state_changed")
    def _on_user_state(ev: object) -> None:
        _bind_rt_session_hooks()
        old_state = getattr(ev, "old_state", "")
        new_state = getattr(ev, "new_state", "")
        _update_session_states(user_state=new_state)
        LOGGER.info(
            "user_state_changed: %s -> %s agent_state=%s",
            old_state,
            new_state,
            session.agent_state,
        )
        if new_state == "away":
            LOGGER.info(
                "user became away, waiting for effective user-input idle timeout before shutting down session"
            )
        if new_state == "speaking" and session.agent_state == "speaking":
            interrupted_while_speaking["value"] = True
            LOGGER.info("检测到用户在 agent 播报期间开口，已标记为打断候选。")

    @session.on("agent_state_changed")
    def _on_agent_state(ev: object) -> None:
        _bind_rt_session_hooks()
        new_state = getattr(ev, "new_state", "")
        _update_session_states(agent_state=new_state)
        LOGGER.info(
            "agent_state_changed: %s -> %s",
            getattr(ev, "old_state", ""),
            new_state,
        )

    @session.on("overlapping_speech")
    def _on_overlapping_speech(ev: object) -> None:
        _bind_rt_session_hooks()
        LOGGER.info("overlapping_speech: %s", ev)

    @session.on("user_input_transcribed")
    def _on_transcribed(ev: object) -> None:
        _bind_rt_session_hooks()
        transcript = getattr(ev, "transcript", "")
        is_final = bool(getattr(ev, "is_final", False))
        noise_only = _is_noise_only_transcript(transcript)
        LOGGER.info(
            "user_input_transcribed: final=%s interrupted=%s noise_only=%s text=%r",
            is_final,
            interrupted_while_speaking["value"],
            noise_only,
            transcript,
        )
        if noise_only:
            if is_final:
                interrupted_while_speaking["value"] = False
            return
        if transcript:
            _mark_effective_user_input(transcript)
            _remember_reply_language_preference(transcript)
            _remember_recent_user_intents(transcript)
            if not is_final and len(_normalize_assistant_text(transcript)) >= PARTIAL_FASTPATH_MIN_CHARS:
                loop.create_task(_try_handle_robot_fastpath(transcript))
        if is_final:
            interrupted_while_speaking["value"] = False

    @session.on("function_tools_executed")
    def _on_function_tools(ev: object) -> None:
        LOGGER.info("function_tools_executed: %s", ev)

    @session.on("conversation_item_added")
    def _on_conversation_item_added(ev: object) -> None:
        item = getattr(ev, "item", None)
        role = getattr(item, "role", "")
        interrupted = bool(getattr(item, "interrupted", False))
        text = getattr(item, "text_content", None)
        LOGGER.info(
            "conversation_item_added: role=%s interrupted=%s text=%r",
            role,
            interrupted,
            text,
        )
        if role == "user" and not interrupted and text:
            if _is_noise_only_transcript(text):
                LOGGER.info("conversation_item_added ignored noise-only user text=%r", text)
                return
            _mark_effective_user_input(text)
            _remember_reply_language_preference(text)
            _remember_latest_user_text(text)
            loop.create_task(_try_handle_local_query_ack(text))
            loop.create_task(_try_handle_robot_fastpath(text))
            return
        if role != "assistant" or interrupted or not text:
            return
        _mirror_once(text)

    @session.on("speech_created")
    def _on_speech_created(ev: object) -> None:
        speech_handle = getattr(ev, "speech_handle", None)
        LOGGER.info(
            "speech_created: user_initiated=%s source=%s speech_id=%s",
            getattr(ev, "user_initiated", None),
            getattr(ev, "source", None),
            getattr(speech_handle, "id", None),
        )
        if speech_handle is None:
            return

        def _on_item(item: object) -> None:
            role = getattr(item, "role", "")
            text = getattr(item, "text_content", None)
            interrupted = bool(getattr(item, "interrupted", False))
            LOGGER.info(
                "speech_handle item_added: role=%s interrupted=%s text=%r",
                role,
                interrupted,
                text,
            )
            if role == "assistant" and not interrupted and text:
                _mirror_once(text)

        speech_handle._add_item_added_callback(_on_item)


def _patched_agent_token(ctx: JobContext) -> str:
    claims = ctx.token_claims()
    video = getattr(claims, "video", None)
    identity = getattr(claims, "identity", "") or f"agent-{ctx.job.id}"
    room_name = getattr(video, "room", "") if video else ""
    room_name = room_name or ctx.room.name

    token = (
        AccessToken(SETTINGS.livekit.api_key, SETTINGS.livekit.api_secret)
        .with_identity(identity)
        .with_kind("agent")
        .with_grants(
            VideoGrants(
                room_join=True,
                room=room_name,
                agent=True,
                can_publish=getattr(video, "can_publish", True) if video else True,
                can_subscribe=getattr(video, "can_subscribe", True) if video else True,
                can_publish_data=getattr(video, "can_publish_data", True) if video else True,
            )
        )
    )

    if getattr(claims, "name", ""):
        token = token.with_name(claims.name)
    if getattr(claims, "metadata", ""):
        token = token.with_metadata(claims.metadata)
    if getattr(claims, "attributes", None):
        token = token.with_attributes(claims.attributes)

    return token.to_jwt()


async def entrypoint(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name}
    claims = ctx.token_claims()
    video = getattr(claims, "video", None)
    print(
        "job token claims:",
        {
            "identity": getattr(claims, "identity", ""),
            "kind": getattr(claims, "kind", ""),
            "room": getattr(video, "room", "") if video else "",
            "room_join": getattr(video, "room_join", None) if video else None,
            "room_admin": getattr(video, "room_admin", None) if video else None,
            "can_publish": getattr(video, "can_publish", None) if video else None,
            "can_subscribe": getattr(video, "can_subscribe", None) if video else None,
            "agent": getattr(video, "agent", None) if video else None,
        },
        flush=True,
    )
    if ENABLE_PATCHED_JOB_TOKEN and getattr(claims, "kind", "") != "agent":
        patched_token = _patched_agent_token(ctx)
        ctx._info.token = patched_token
        verified = TokenVerifier(
            api_key=SETTINGS.livekit.api_key,
            api_secret=SETTINGS.livekit.api_secret,
        ).verify(patched_token, verify_signature=False)
        print(
            "patched job token claims:",
            {
                "identity": getattr(verified, "identity", ""),
                "kind": getattr(verified, "kind", ""),
                "room": getattr(getattr(verified, "video", None), "room", ""),
                "room_join": getattr(getattr(verified, "video", None), "room_join", None),
                "agent": getattr(getattr(verified, "video", None), "agent", None),
            },
            flush=True,
        )
    LOGGER.info("收到新房间任务，room=%s", ctx.room.name)

    session = _build_session()
    _wire_debug_events(session)
    await session.start(
        room=ctx.room,
        agent=InterruptAssistant(),
    )
    room_io = getattr(session, "_room_io", None)
    if room_io is not None:
        room_io.set_participant(SETTINGS.rtc_endpoint.identity)
        LOGGER.info("room input participant pinned: %s", SETTINGS.rtc_endpoint.identity)


async def on_request(req: JobRequest) -> None:
    room_name = getattr(req.room, "name", "room")
    LOGGER.info(
        "接受 job request: room=%s job_id=%s",
        room_name,
        req.id,
    )
    await req.accept()


_server_kwargs = {
    "ws_url": SETTINGS.livekit.url,
    "api_key": SETTINGS.livekit.api_key,
    "api_secret": SETTINGS.livekit.api_secret,
    "http_proxy": _livekit_proxy(),
}

_load_threshold_override = _env_float("INTERRUPT_AGENT_LOAD_THRESHOLD")
if _load_threshold_override is not None:
    _server_kwargs["load_threshold"] = _load_threshold_override

_forced_worker_load = _worker_load_override()
if _forced_worker_load is not None:
    _server_kwargs["load_fnc"] = lambda: _forced_worker_load

server = AgentServer(**_server_kwargs)

server.rtc_session(entrypoint, agent_name=SETTINGS.agent.name, on_request=on_request)


if __name__ == "__main__":
    logging.basicConfig(
        level=getattr(logging, SETTINGS.logging.level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log_integration_summary(SETTINGS)
    cli.run_app(server)
