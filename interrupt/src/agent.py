from __future__ import annotations

import asyncio
import dataclasses
import ipaddress
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse

from google.genai import types as google_types
from livekit.agents.llm import function_tool
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobExecutorType,
    JobRequest,
    cli,
)
from livekit.api import AccessToken, TokenVerifier, VideoGrants
from livekit.plugins import google

from src.console_audio_compat import apply_console_audio_compat_patch
from src.g1_om1_adapter import G1Om1Adapter
from src.integrations import build_mcp_servers, log_integration_summary
from src.navigation_intents import (
    extract_navigation_destination,
    extract_remember_location_name,
    looks_like_relative_motion_command,
    looks_like_saved_locations_query,
)
from src.safe_action_gateway import evaluate_action_safety, evaluate_navigation_safety
from src.safe_action_middleware import precheck_body_action, precheck_navigation
from src.news import query_news
from src.local_text_brain import LocalTextToolCall, run_local_text_brain
from src.speech_feedback import SpeechFeedbackRouter
from src.speech_loop_guard import (
    local_playback_guard_active,
    note_local_playback,
    should_ignore_transcript,
)
from src.settings import load_settings
from src.vision_chat import VisionChatConfig, ask_camera_question
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
VISION_CHAT_CONFIG = VisionChatConfig(
    enabled=SETTINGS.vision.enabled,
    provider=SETTINGS.vision.provider,
    api_key=SETTINGS.vision.api_key,
    base_url=SETTINGS.vision.base_url,
    model=SETTINGS.vision.model,
    image_path=SETTINGS.vision.image_path,
    preferred_device=SETTINGS.vision.preferred_device,
    width=SETTINGS.vision.width,
    height=SETTINGS.vision.height,
    jpeg_quality=SETTINGS.vision.jpeg_quality,
    max_tokens=SETTINGS.vision.max_tokens,
    capture_warmup_frames=SETTINGS.vision.capture_warmup_frames,
    capture_timeout_s=SETTINGS.vision.capture_timeout_s,
)
REALTIME_PREFIX_PADDING_MS = int(
    os.getenv("INTERRUPT_REALTIME_PREFIX_PADDING_MS", "500").strip() or "500"
)
USER_AWAY_TIMEOUT_S = max(1.0, SETTINGS.agent.user_away_timeout_ms / 1000.0)
ENABLE_FRONTGATE_IDLE_SESSION_EXIT = os.getenv(
    "INTERRUPT_ENABLE_FRONTGATE_IDLE_SESSION_EXIT",
    "0",
).strip().lower() in {"1", "true", "yes", "on"}
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
FRONTGATE_TEXT_INPUT_ONLY = os.getenv(
    "INTERRUPT_RTC_TEXT_INPUT_ONLY",
    "0",
).strip().lower() in {"1", "true", "yes", "on"}
LOCAL_TEXT_DECISION_MODE = SETTINGS.agent.local_text_decision_mode
AGENT_RUNTIME_MODE = SETTINGS.agent.runtime_mode
ENABLE_SAFE_ACTION_GATEWAY = os.getenv(
    "INTERRUPT_ENABLE_SAFE_ACTION_GATEWAY",
    "0",
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
POST_SPEECH_GIBBERISH_GUARD_S = float(
    os.getenv("INTERRUPT_POST_SPEECH_GIBBERISH_GUARD_S", "4.0").strip() or "4.0"
)
POST_SPEECH_GIBBERISH_MAX_ALPHA = int(
    os.getenv("INTERRUPT_POST_SPEECH_GIBBERISH_MAX_ALPHA", "10").strip() or "10"
)
RECENT_ASSISTANT_REPLY_SUPPRESS_WINDOW_S = float(
    os.getenv("INTERRUPT_RECENT_ASSISTANT_REPLY_SUPPRESS_WINDOW_S", "30.0").strip() or "30.0"
)
RECENT_ASSISTANT_REPLY_SIMILARITY = float(
    os.getenv("INTERRUPT_RECENT_ASSISTANT_REPLY_SIMILARITY", "0.88").strip() or "0.88"
)
_LAST_USER_TEXT_LOCK = threading.Lock()
_LAST_USER_TEXT = ""
_LAST_USER_TEXT_AT = 0.0
_LAST_EFFECTIVE_USER_INPUT_AT_LOCK = threading.Lock()
_LAST_EFFECTIVE_USER_INPUT_AT = time.monotonic()
_LAST_AGENT_SPEECH_ENDED_AT_LOCK = threading.Lock()
_LAST_AGENT_SPEECH_ENDED_AT = 0.0
_RECENT_ASSISTANT_REPLIES_LOCK = threading.Lock()
_RECENT_ASSISTANT_REPLIES: list[tuple[str, float]] = []
_LANGUAGE_STATE_LOCK = threading.Lock()
_LAST_DETECTED_USER_LANGUAGE = "zh-CN"
_FORCED_REPLY_LANGUAGE = ""
_LAST_HINTED_USER_TEXT = ""
_LAST_HINTED_USER_LANGUAGE = ""
_LAST_HINTED_USER_AT = 0.0
_RECENT_INTENT_LOCK = threading.Lock()
_RECENT_INTENTS: dict[str, dict[str, float]] = {}
OFFLINE_SINGLEBOX_ALLOWED_LOCAL_TOOLS = frozenset(
    {
        "perform_body_action",
        "set_led_color",
        "ask_camera_vision",
        "list_saved_locations",
        "navigate_to_saved_location",
        "remember_current_location",
    }
)

REPLY_LANGUAGE_MANDARIN = "zh-CN"
REPLY_LANGUAGE_CANTONESE = "zh-YUE"
REPLY_LANGUAGE_ENGLISH = "en"
FRONTGATE_HINT_REUSE_WINDOW_S = float(
    os.getenv("INTERRUPT_FRONTGATE_HINT_REUSE_WINDOW_S", "8.0").strip() or "8.0"
)
DEFAULT_NAVIGATION_ALIAS_MAP = {
    "门口": "entrance",
    "門口": "entrance",
    "door": "entrance",
    "front door": "entrance",
}
DEFAULT_NAVIGATION_ARRIVAL_INTRO_LOCATIONS = frozenset({"门口", "門口", "entrance"})


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
    dedicated = os.getenv("INTERRUPT_LIVEKIT_PROXY", "").strip()
    if dedicated:
        return dedicated
    return os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")


def _gemini_realtime_proxy() -> str | None:
    for key in (
        "INTERRUPT_GEMINI_PROXY",
        "GEMINI_WSS_PROXY",
        "WSS_PROXY",
        "HTTPS_PROXY",
        "HTTP_PROXY",
    ):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return None


def _gemini_realtime_http_options() -> google_types.HttpOptions | None:
    proxy = _gemini_realtime_proxy()
    client_args: dict[str, object] = {"trust_env": False}
    async_client_args: dict[str, object] = {"trust_env": False}
    if proxy:
        client_args["proxy"] = proxy
        async_client_args["proxy"] = proxy
    if not proxy and not client_args and not async_client_args:
        return None
    return google_types.HttpOptions(
        client_args=client_args,
        async_client_args=async_client_args,
    )


def _env_float(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        LOGGER.warning("invalid float env ignored: %s=%r", name, raw)
        return None


def _env_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        LOGGER.warning("invalid int env ignored: %s=%r", name, raw)
        return None


def _worker_load_override() -> float | None:
    forced = _env_float("INTERRUPT_AGENT_FORCE_LOAD")
    if forced is None:
        return None
    return max(0.0, min(forced, 0.99))


def _job_executor_type() -> JobExecutorType:
    raw = os.getenv("INTERRUPT_AGENT_JOB_EXECUTOR_TYPE", "thread").strip().lower()
    if raw == "process":
        return JobExecutorType.PROCESS
    if raw in {"thread", "threaded"}:
        return JobExecutorType.THREAD
    LOGGER.warning(
        "invalid INTERRUPT_AGENT_JOB_EXECUTOR_TYPE=%r, fallback to thread",
        raw,
    )
    return JobExecutorType.THREAD


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
_CJK_LATIN_DIGIT_RE = re.compile(
    rf"(?:(?<=[{_CJK_CHAR_RE}])\s+(?=[A-Za-z0-9])|(?<=[A-Za-z0-9])\s+(?=[{_CJK_CHAR_RE}])|(?<=[{_CJK_CHAR_RE}])\s+(?=[{_CJK_CHAR_RE}]))"
)
_PUNCT_SPACING_RE = re.compile(r"\s+([，。！？；：,.!?;:])")
_TTS_BREAK_PUNCT_RE = re.compile(r"[，,、；;：:]")
_TTS_DROP_PUNCT_RE = re.compile(r"[“”\"'`()\[\]{}<>《》【】]")
_ASCII_WORD_SPACE_RE = re.compile(r"(?<=[A-Za-z])\s+(?=[A-Za-z])")
_META_REPLY_LINE_RE = re.compile(
    r"(根据(规则|您的要求)[^。！？!?\n]*[。！？!?]?|"
    r"下面是一个简短的自然语言回复[:：]?\s*|"
    r"请优先返回工具调用[^。！？!?\n]*[。！？!?]?|"
    r"由于用户[^。！？!?\n]*[。！？!?]?)"
)


def _normalize_assistant_text(text: str) -> str:
    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return ""
    normalized = re.sub(r"(?i)\s*<(?:noise|unk)>\s*", " ", normalized)
    normalized = re.sub(r"(?i)\b(?:noise|noises|background\s*noise|static|silence|empty|unk)\b", " ", normalized)
    normalized = _CJK_LATIN_DIGIT_RE.sub("", normalized)
    normalized = _PUNCT_SPACING_RE.sub(r"\1", normalized)
    normalized = " ".join(normalized.split()).strip()
    return normalized


def _normalize_tts_text(text: str) -> str:
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return ""
    normalized = _META_REPLY_LINE_RE.sub("", normalized)
    normalized = re.sub(r"\s*\n+\s*", "。", normalized)
    normalized = _TTS_BREAK_PUNCT_RE.sub("，", normalized)
    normalized = _TTS_DROP_PUNCT_RE.sub("", normalized)
    normalized = normalized.replace("...", "。").replace("…", "。")
    normalized = re.sub(r"[。]{2,}", "。", normalized)
    normalized = re.sub(r"[！？]{2,}", lambda m: m.group(0)[0], normalized)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[A-Za-z])", "", normalized)
    normalized = re.sub(r"(?<=[A-Za-z])\s+(?=[\u4e00-\u9fff])", "", normalized)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", normalized)
    normalized = " ".join(normalized.split()).strip()
    normalized = _ASCII_WORD_SPACE_RE.sub(" ", normalized)
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


def _mark_agent_speech_ended() -> None:
    with _LAST_AGENT_SPEECH_ENDED_AT_LOCK:
        global _LAST_AGENT_SPEECH_ENDED_AT
        _LAST_AGENT_SPEECH_ENDED_AT = time.monotonic()


def _seconds_since_agent_speech_ended() -> float:
    with _LAST_AGENT_SPEECH_ENDED_AT_LOCK:
        if _LAST_AGENT_SPEECH_ENDED_AT <= 0:
            return float("inf")
        return max(0.0, time.monotonic() - _LAST_AGENT_SPEECH_ENDED_AT)


def _looks_like_short_post_speech_gibberish(text: str) -> bool:
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return True
    if re.search(rf"[{_CJK_CHAR_RE}]", normalized):
        return False
    folded = re.sub(r"[^A-Za-z]+", "", normalized).lower()
    if not folded:
        return True
    if len(folded) > POST_SPEECH_GIBBERISH_MAX_ALPHA:
        return False
    valid_short_words = {
        "yes",
        "no",
        "ok",
        "okay",
        "stop",
        "cancel",
        "hello",
        "hi",
        "help",
    }
    if folded in valid_short_words:
        return False
    return True


def _should_ignore_post_speech_gibberish(text: str) -> bool:
    if POST_SPEECH_GIBBERISH_GUARD_S <= 0:
        return False
    if _seconds_since_agent_speech_ended() > POST_SPEECH_GIBBERISH_GUARD_S:
        return False
    return _looks_like_short_post_speech_gibberish(text)


def _should_ignore_low_information_transcript(text: str) -> bool:
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return True
    if re.search(rf"[{_CJK_CHAR_RE}]", normalized):
        return False
    english_words = re.findall(r"[A-Za-z]+", normalized)
    if english_words:
        lowered_words = [word.lower() for word in english_words]
        if len(lowered_words) == 1 and len(lowered_words[0]) <= 2:
            return True
        if len(lowered_words) <= 2 and all(len(word) <= 2 for word in lowered_words):
            return True
    if re.search(r"[A-Za-z]{2,}", normalized):
        return False
    if re.search(r"\d{2,}", normalized):
        return False
    folded_ascii = re.sub(r"[^A-Za-z]+", "", normalized)
    if len(folded_ascii) <= 1:
        return True
    # Filter out single-symbol / single-codepoint junk such as stray Thai,
    # punctuation, or one-character Latin fragments that often come from
    # echo/AEC residue after playback.
    compact = re.sub(r"\s+", "", normalized)
    return len(compact) <= 1


def _should_ignore_user_backchannel(text: str) -> bool:
    normalized_text = _normalize_assistant_text(text)
    normalized = normalized_text.lower()
    if not normalized:
        return True
    if _looks_like_user_question(normalized_text):
        return False
    compact = re.sub(r"\s+", "", normalized)
    folded_ascii = re.sub(r"[^a-z]+", "", compact)
    if re.search(rf"[{_CJK_CHAR_RE}]", compact):
        if "?" in compact or "？" in compact:
            return False
        short_cjk_backchannels = {
            "嗯",
            "恩",
            "哦",
            "喔",
            "啊",
            "哎",
            "好",
            "好的",
            "係",
            "系",
        }
        if compact in short_cjk_backchannels:
            return True
        return len(compact) <= 1
    if compact in {
        "yes",
        "yeah",
        "yep",
        "so",
        "uh",
        "um",
        "hmm",
        "mm",
        "mhm",
        "ah",
        "oh",
        "ok",
        "okay",
        "sure",
        "alright",
        "hello",
        "hi",
    }:
        return True
    if len(folded_ascii) <= 1:
        return True
    if re.fullmatch(r"[.。!！?？,，~～]+", compact):
        return True
    return False


def _fold_text_for_echo_match(text: str) -> str:
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return ""
    normalized = re.sub(r"\b[A-Za-z]\b", " ", normalized)
    normalized = normalized.replace("Centre", "Center").replace("centre", "center")
    normalized = normalized.replace("Centres", "Centers").replace("centres", "centers")
    return re.sub(rf"[^\w{_CJK_CHAR_RE}]+", "", normalized).lower()


def _remember_recent_assistant_reply(text: str) -> None:
    folded = _fold_text_for_echo_match(text)
    if not folded or RECENT_ASSISTANT_REPLY_SUPPRESS_WINDOW_S <= 0:
        return
    now = time.monotonic()
    with _RECENT_ASSISTANT_REPLIES_LOCK:
        global _RECENT_ASSISTANT_REPLIES
        _RECENT_ASSISTANT_REPLIES = [
            (candidate, ts)
            for candidate, ts in _RECENT_ASSISTANT_REPLIES
            if now - ts <= RECENT_ASSISTANT_REPLY_SUPPRESS_WINDOW_S
        ]
        _RECENT_ASSISTANT_REPLIES.append((folded, now))


def _looks_like_recent_assistant_reply_echo(text: str) -> bool:
    folded = _fold_text_for_echo_match(text)
    if not folded or RECENT_ASSISTANT_REPLY_SUPPRESS_WINDOW_S <= 0:
        return False
    now = time.monotonic()
    with _RECENT_ASSISTANT_REPLIES_LOCK:
        global _RECENT_ASSISTANT_REPLIES
        _RECENT_ASSISTANT_REPLIES = [
            (candidate, ts)
            for candidate, ts in _RECENT_ASSISTANT_REPLIES
            if now - ts <= RECENT_ASSISTANT_REPLY_SUPPRESS_WINDOW_S
        ]
        candidates = list(_RECENT_ASSISTANT_REPLIES)
    for candidate, _ts in candidates:
        if folded == candidate:
            return True
        if len(folded) >= 8 and (folded in candidate or candidate in folded):
            return True
        if len(folded) >= 10 and len(candidate) >= 10:
            if SequenceMatcher(None, folded, candidate).ratio() >= RECENT_ASSISTANT_REPLY_SIMILARITY:
                return True
    return False


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


def _normalize_reply_language_hint(language: str) -> str:
    normalized = (language or "").strip().lower()
    alias_map = {
        "zh": REPLY_LANGUAGE_MANDARIN,
        "zh-cn": REPLY_LANGUAGE_MANDARIN,
        "cmn": REPLY_LANGUAGE_MANDARIN,
        "mandarin": REPLY_LANGUAGE_MANDARIN,
        "yue": REPLY_LANGUAGE_CANTONESE,
        "zh-yue": REPLY_LANGUAGE_CANTONESE,
        "cantonese": REPLY_LANGUAGE_CANTONESE,
        "en": REPLY_LANGUAGE_ENGLISH,
        "en-us": REPLY_LANGUAGE_ENGLISH,
        "en-gb": REPLY_LANGUAGE_ENGLISH,
        "english": REPLY_LANGUAGE_ENGLISH,
    }
    return alias_map.get(normalized, "")


def _reply_language_instruction(language: str) -> str:
    normalized = _normalize_reply_language_hint(language) or language
    if normalized == REPLY_LANGUAGE_CANTONESE:
        return "This turn, reply only in natural Cantonese. Do not use Mandarin or English."
    if normalized == REPLY_LANGUAGE_ENGLISH:
        return "This turn, reply only in natural English. Do not use Mandarin or Cantonese."
    return "This turn, reply only in natural Mandarin Chinese. Do not use Cantonese or English."


def _resolve_reply_language_detection(text: str, language_hint: str = "") -> tuple[str, str]:
    normalized_text = _normalize_assistant_text(text)
    hinted = _normalize_reply_language_hint(language_hint)
    if hinted:
        return hinted, "hint"
    if normalized_text:
        with _LANGUAGE_STATE_LOCK:
            if (
                _LAST_HINTED_USER_TEXT
                and normalized_text == _LAST_HINTED_USER_TEXT
                and (time.monotonic() - _LAST_HINTED_USER_AT) <= FRONTGATE_HINT_REUSE_WINDOW_S
                and _LAST_HINTED_USER_LANGUAGE
            ):
                return _LAST_HINTED_USER_LANGUAGE, "cached_hint"
    return _detect_reply_language(text), "text"


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


def _is_offline_singlebox_mode() -> bool:
    return AGENT_RUNTIME_MODE == "offline_singlebox"


def _offline_singlebox_limit_reply() -> str:
    return _localized_text(
        "当前是单机离线模式，这个请求超出了离线能力范围。请打开在线增强模式后再试。",
        "而家係單機離線模式，呢個請求超出咗離線能力範圍。請打開在線增強模式之後再試。",
        "The robot is in single-box offline mode. This request is outside the offline capability set. Please enable online mode and try again.",
    )


def _looks_like_self_echo_transcript(text: str) -> bool:
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return False
    markers = (
        "我是笨笨同学",
        "我可以用粤语",
        "我可以用粵語",
        "今天很高兴在这里为您服务",
        "今日好高興喺呢度為您服務",
        "如果您想了解数据中心",
        "如果您想了解數據中心",
        "随时告诉我哦",
        "隨時同我講哦",
        "现在可以了",
        "當前是單機離線模式",
        "当前是单机离线模式",
        "请打开在线增强模式后再试",
        "請打開在線增強模式之後再試",
        "好的正在执行动作",
        "actioncommandfailed",
        "execute_robot_command_text",
        "perform_body_action",
        "好的正在执行",
        "好啊依家執行",
        "当前处于离线模式",
        "已为您切换到在线模式",
        "刚才我没有听到明确的视觉问",
        "啱啱我未聽到明確要我睇畫面",
        "所以先不看相机画面",
        "所以而家先唔開相機",
        "i didn't hear a clear visual question",
    )
    return any(marker in normalized for marker in markers)


def _looks_like_tool_payload_text(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    compact = normalized.lower()
    if compact.startswith("{") and ("\"name\"" in compact or "\"arguments\"" in compact):
        return True
    return any(
        token in compact
        for token in (
            "execute_robot_command_text",
            "perform_body_action",
            "\"arguments\"",
            "\"name\"",
            "actioncommandfailed",
        )
    )


def _extract_spoken_reply_text(text: str) -> str:
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return ""
    if _looks_like_tool_payload_text(normalized):
        return ""
    return normalized


def _looks_like_user_question(text: str) -> bool:
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return False
    lowered = normalized.lower()
    compact = re.sub(r"\s+", "", normalized)
    if "?" in normalized or "？" in normalized:
        return True
    markers = (
        "你会做什么",
        "你可以做什么",
        "你可以做些什么",
        "你能做什么",
        "你可以做到啲咩",
        "你可以做到咩",
        "你可以做啲咩",
        "你可以做咩",
        "你係邊個",
        "你系边个",
        "依家幾點",
        "依家几点",
        "而家幾點",
        "而家几点",
        "而家係咩模式",
        "你會講咩語言",
        "你會做咩",
        "可以介绍一下",
        "介绍一下",
        "而家几点",
        "现在几点",
        "几点了",
        "what can you do",
        "who are you",
        "what time is it",
        "can you introduce yourself",
        "tell me",
    )
    return any(
        marker in normalized
        or marker in lowered
        or marker.replace(" ", "") in compact.lower()
        for marker in markers
    )


def _looks_like_recent_assistant_reprompt(text: str) -> bool:
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return False
    compact = re.sub(r"\s+", "", normalized)
    if len(compact) < 12:
        return False
    markers = (
        "请告诉我您需要什么帮助",
        "请告诉我您需要什么帮助或询问的问题",
        "请提供具体需求或问题",
        "请告诉我您需要什么帮助或者想要了解的信息",
        "如果您有任何问题或需要帮助",
        "如果没有其他具体需求",
        "whatwouldyouliketoknow",
        "whatcanihelpyouwith",
        "helloimherewhatwouldyouliketoknow",
    )
    compact_lower = compact.lower()
    return any(marker in normalized or marker in compact_lower for marker in markers)


def _offline_singlebox_unavailable_reply() -> str:
    return _localized_text(
        "当前是单机离线模式，但本地能力暂时不可用。请稍后重试，或切回在线增强模式。",
        "而家係單機離線模式，但本地能力暫時不可用。請稍後再試，或者切回在線增強模式。",
        "The robot is in single-box offline mode, but the local capability path is temporarily unavailable. Please try again later or switch back to online mode.",
    )


def _offline_persona_reply_for_category(category: str, *, language: str | None = None) -> str:
    if category == "intro":
        return _localized_text(
            "你好，我是笨笨同学，中国移动环球智算中心的智能导览机器人。",
            "你好，我係笨笨同學，係中國移動環球智算中心嘅智能導覽機器人。",
            "Hello, I'm BenBen, the smart tour guide robot of China Mobile's Global Intelligent Computing Centre.",
            language=language,
        )
    if category == "capabilities":
        return _localized_text(
            "我可以回答问题，介绍园区和数据中心信息，也可以帮您控制灯光、执行动作、查询天气新闻和回答画面内容。",
            "我可以答問題，介紹園區同數據中心資訊，亦可以幫您控制燈光、做動作、查天氣新聞同回答畫面內容。",
            "I can answer questions, introduce the campus and data center, control lights, perform actions, check weather and news, and answer vision questions.",
            language=language,
        )
    if category == "languages":
        return _localized_text(
            "我可以用普通话、粤语和英文交流。",
            "我可以用普通話、粵語同英文交流。",
            "I can speak Mandarin, Cantonese, and English.",
            language=language,
        )
    if category == "mode":
        return _localized_text(
            "我现在运行在单机离线模式，可以进行本地对话和本地能力调用。",
            "我而家運行緊單機離線模式，可以進行本地對話同本地能力調用。",
            "I am currently running in single-box offline mode with local dialogue and local skills.",
            language=language,
        )
    return ""


def _offline_persona_query_category(text: str) -> str | None:
    normalized = _normalize_assistant_text(text).lower()
    if not normalized:
        return None
    squashed = normalized.replace(" ", "")
    if any(
        (token in normalized) or (token.replace(" ", "") in squashed)
        for token in (
            "你是谁",
            "你是誰",
            "介绍一下你自己",
            "介紹一下你自己",
            "介绍你自己",
            "介紹你自己",
            "自我介绍",
            "自我介紹",
            "what's your name",
            "what is your name",
            "whatsyourname",
            "who are you",
            "introduce yourself",
            "can you introduce yourself",
        )
    ):
        return "intro"
    if any(
        (token in normalized) or (token.replace(" ", "") in squashed)
        for token in (
            "你会什么",
            "你會什麼",
            "你能做什么",
            "你能做些什么",
            "你可以做什么",
            "你可以做些什么",
            "what can you do",
            "your capabilities",
        )
    ):
        return "capabilities"
    if any(
        (token in normalized) or (token.replace(" ", "") in squashed)
        for token in (
            "你会说什么语言",
            "你支持什么语言",
            "你会说英文吗",
            "你會說英文嗎",
            "what languages do you speak",
            "which languages can you speak",
            "do you speak english",
            "can you speak english",
        )
    ):
        return "languages"
    if any(
        (token in normalized) or (token.replace(" ", "") in squashed)
        for token in (
            "你现在是什么模式",
            "你现在是在线还是离线",
            "are you offline",
            "are you online",
            "what mode are you in",
        )
    ):
        return "mode"
    return None


def _offline_singlebox_builtin_reply(text: str) -> str:
    normalized = _normalize_assistant_text(text).lower()
    if not normalized:
        return ""
    squashed = normalized.replace(" ", "")
    if _looks_like_recent_assistant_reprompt(normalized):
        return ""
    if any(
        (token in normalized) or (token.replace(" ", "") in squashed)
        for token in (
            "你好",
            "您好",
            "hello",
            "hi",
            "hey",
            "你在吗",
            "are you there",
        )
    ):
        return _localized_text(
            "你好，我在。请问您想了解什么？",
            "你好，我喺度。請問您想了解咩？",
            "Hello, I'm here. What would you like to know?",
        )
    category = _offline_persona_query_category(normalized)
    if category:
        return _offline_persona_reply_for_category(category)
    if any(
        (token in normalized) or (token.replace(" ", "") in squashed)
        for token in (
            "谢谢",
            "多谢",
            "thank you",
            "thanks",
        )
    ):
        return _localized_text(
            "不客气。",
            "唔使客氣。",
            "You're welcome.",
        )
    if any(
        (token in normalized) or (token in squashed)
        for token in (
            "请告诉我您需要什么帮助",
            "请提问您的问题",
            "如果您有任何问题或需要帮助",
            "whatwouldyouliketoknow",
            "whatcanihelpyouwith",
        )
    ):
        return ""
    return ""


def _tool_call_allowed_in_offline_singlebox(tool_call: LocalTextToolCall) -> bool:
    return tool_call.name in OFFLINE_SINGLEBOX_ALLOWED_LOCAL_TOOLS


def _remember_reply_language_preference(text: str, language_hint: str = "") -> None:
    forced = _detect_forced_reply_language(text)
    detected, detection_source = _resolve_reply_language_detection(text, language_hint)
    normalized_text = _normalize_assistant_text(text)
    with _LANGUAGE_STATE_LOCK:
        global _FORCED_REPLY_LANGUAGE, _LAST_DETECTED_USER_LANGUAGE
        global _LAST_HINTED_USER_TEXT, _LAST_HINTED_USER_LANGUAGE, _LAST_HINTED_USER_AT
        if forced is not None:
            _FORCED_REPLY_LANGUAGE = forced
            LOGGER.info("reply language mode updated: forced=%r by text=%r", forced or "auto", text)
        _LAST_DETECTED_USER_LANGUAGE = detected
        if detection_source == "hint" and normalized_text:
            _LAST_HINTED_USER_TEXT = normalized_text
            _LAST_HINTED_USER_LANGUAGE = detected
            _LAST_HINTED_USER_AT = time.monotonic()
    LOGGER.info(
        "reply language detected: detected=%s effective=%s hint=%s source=%s text=%r",
        detected,
        _preferred_reply_language(),
        language_hint,
        detection_source,
        text,
    )


def _preferred_reply_language() -> str:
    with _LANGUAGE_STATE_LOCK:
        if _FORCED_REPLY_LANGUAGE:
            return _FORCED_REPLY_LANGUAGE
        return _LAST_DETECTED_USER_LANGUAGE or REPLY_LANGUAGE_MANDARIN


def _log_assistant_language_alignment(text: str) -> None:
    expected = _preferred_reply_language()
    actual = _detect_reply_language(text)
    if actual == expected:
        LOGGER.info(
            "assistant reply language aligned: expected=%s actual=%s text=%r",
            expected,
            actual,
            text,
        )
        return
    LOGGER.warning(
        "assistant reply language mismatch: expected=%s actual=%s text=%r",
        expected,
        actual,
        text,
    )


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
        language=_preferred_reply_language(),
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
        destination = extract_navigation_destination(text)
        if destination:
            _RECENT_INTENTS.setdefault("navigate", {})[destination] = now
        remembered_name = extract_remember_location_name(text)
        if remembered_name:
            _RECENT_INTENTS.setdefault("remember_location", {})[remembered_name] = now


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
        elif kind == "navigate":
            matched = extract_navigation_destination(latest_text)
            if matched == payload:
                return True
        elif kind == "remember_location":
            matched = extract_remember_location_name(latest_text)
            if matched == payload:
                return True
    remembered_payloads = _recent_intents(kind)
    if not remembered_payloads:
        return False
    if kind in {"action", "led", "navigate", "remember_location"}:
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
    if _looks_like_vision_query(normalized):
        if language == REPLY_LANGUAGE_CANTONESE:
            return "好啊，我而家幫你睇下前面。"
        if language == REPLY_LANGUAGE_ENGLISH:
            return "Okay, I'll take a quick look."
        return "好的，我来帮你看看前面。"
    if looks_like_saved_locations_query(normalized):
        if language == REPLY_LANGUAGE_CANTONESE:
            return "好啊，我而家睇下有咩已儲存地點。"
        if language == REPLY_LANGUAGE_ENGLISH:
            return "Okay, I'll check the saved locations."
        return "好的，我来看看有哪些已保存地点。"
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


def _looks_like_intro_query(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    return any(
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
            "introduce yourself",
        )
    )


def _builtin_intro_reply() -> str:
    return _localized_text(
        "你好！我是笨笨同学，中国移动环球智算中心的专属智能导览机器人。我可以用粤语、普通话和英文与您交流。今天很高兴在这里为您服务！如果您想了解数据中心的任何信息，随时告诉我哦。",
        "你好！我係笨笨同學，中國移動環球智算中心嘅專屬智能導覽機械人。我可以用粵語、普通話同英文同您交流。今日好高興喺呢度為您服務！如果您想了解數據中心嘅任何資訊，隨時同我講哦。",
        "Hello! I am Benben, the dedicated intelligent guide robot for China Mobile Global Intelligent Computing Center. I can talk with you in Cantonese, Mandarin, and English. I am very happy to serve you here today. If you would like to know anything about the data center, just let me know.",
    )


def _navigation_alias_map() -> dict[str, str]:
    alias_map = dict(DEFAULT_NAVIGATION_ALIAS_MAP)
    raw = os.getenv("INTERRUPT_NAV_LOCATION_ALIASES", "").strip()
    if not raw:
        return alias_map
    for item in raw.split(","):
        chunk = item.strip()
        if not chunk or "=" not in chunk:
            continue
        source, target = chunk.split("=", 1)
        source = source.strip()
        target = target.strip()
        if source and target:
            alias_map[source] = target
    return alias_map


def _resolve_navigation_location_label(location: str) -> str:
    normalized = (location or "").strip()
    if not normalized:
        return ""
    return _navigation_alias_map().get(normalized, normalized)


def _arrival_intro_locations() -> set[str]:
    configured = os.getenv("INTERRUPT_NAV_ARRIVAL_INTRO_LOCATIONS", "").strip()
    if not configured:
        return set(DEFAULT_NAVIGATION_ARRIVAL_INTRO_LOCATIONS)
    return {item.strip() for item in configured.split(",") if item.strip()}


def _should_announce_intro_on_navigation_arrival(requested_location: str, resolved_location: str) -> bool:
    candidates = _arrival_intro_locations()
    return requested_location in candidates or resolved_location in candidates


def _looks_like_local_tool_failure(text: str) -> bool:
    normalized = _normalize_assistant_text(text).lower()
    if not normalized:
        return True
    failure_tokens = (
        "failed",
        "unavailable",
        "ignored mismatched",
        "暂时没法",
        "当前不可用",
        "拿不到",
        "未能",
        "失败",
        "抱歉",
    )
    return any(token in normalized for token in failure_tokens)


def _navigation_ack_text(location: str) -> str:
    return _localized_text(
        f"好的，带你去{location}。",
        f"好啊，依家帶你去{location}。",
        f"Okay, taking you to {location}.",
    )


def _remember_location_ack_text(location: str) -> str:
    return _localized_text(
        f"好的，我记住这里是{location}。",
        f"好啊，我記住呢度係{location}。",
        f"Okay, I will remember this place as {location}.",
    )


def _relative_motion_not_supported_text() -> str:
    return _localized_text(
        "现在这条语音导航链路只支持去已保存地点，暂不支持前进几步、转圈这类相对移动指令。",
        "而家呢条語音導航鏈路只支援去已儲存地點，暫時未支援前進幾步、轉圈呢類相對移動指令。",
        "This voice navigation flow currently supports only saved destinations, not relative motion commands like stepping forward or spinning.",
    )


def _parse_command_json(stdout: str) -> dict[str, object] | None:
    normalized = (stdout or "").strip()
    if not normalized:
        return None
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _format_locations_reply(payload: dict[str, object]) -> str:
    locations = payload.get("locations")
    if not isinstance(locations, list):
        return _localized_text(
            "我暂时没有拿到可导航地点列表。",
            "我暫時未拎到可導航地點列表。",
            "I could not get the saved navigation locations right now.",
        )
    names = [str(item).strip() for item in locations if str(item).strip()]
    if not names:
        return _localized_text(
            "当前还没有已保存的导航地点。",
            "而家仲未有已儲存嘅導航地點。",
            "There are no saved navigation locations yet.",
        )
    return _localized_text(
        f"目前可以去这些地点：{'，'.join(names)}。",
        f"目前可以去呢啲地點：{'，'.join(names)}。",
        f"I can go to these saved locations: {', '.join(names)}.",
    )


def _navigation_backend_unavailable_text() -> str:
    return _localized_text(
        "导航后端当前没有启动，我暂时还不能带你去已保存地点。",
        "導航後端而家未啟動，我暫時未可以帶你去已儲存地點。",
        "The navigation backend is not running right now, so I can't take you to a saved place yet.",
    )


def _navigation_request_failed_text(payload: dict[str, object] | None) -> str | None:
    if not payload:
        return None
    if str(payload.get("error") or "").strip().lower() != "request_failed":
        return None
    detail = str(payload.get("detail") or "").strip().lower()
    if not detail:
        return _navigation_backend_unavailable_text()
    if "localhost:5000" in detail or "127.0.0.1:5000" in detail or "connection refused" in detail:
        return _navigation_backend_unavailable_text()
    return _localized_text(
        "导航请求这次没有成功发到机器人导航后端。",
        "今次未能成功將導航請求發到機械人導航後端。",
        "This navigation request did not reach the robot navigation backend successfully.",
    )


def _looks_like_weather_query(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return any(token in normalized for token in ("天气", "天氣", "weather"))


def _looks_like_news_query(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return any(token in normalized for token in ("新闻", "新聞", "news", "热点", "熱點", "时事", "時事"))


def _vision_failure_text(error: str, *, device: str = "") -> str:
    language = _preferred_reply_language()
    if error == "vision_disabled":
        return _localized_text(
            "我当前还没有开启视觉模式，所以现在看不到前面的画面。",
            "我而家未開啟視覺模式，所以暫時睇唔到前面畫面。",
            "Vision mode is not enabled right now, so I can't see the camera view yet.",
        )
    if error == "missing_api_key":
        return _localized_text(
            "视觉功能还没配置好 Gemini API key，所以现在暂时不能看图。",
            "視覺功能未配置好 Gemini API key，所以而家暫時未能睇圖。",
            "The vision feature is missing the Gemini API key, so it can't inspect images yet.",
        )
    if error == "opencv_unavailable":
        return _localized_text(
            "当前环境缺少相机依赖，所以我暂时没法调用视觉功能。",
            "而家環境缺少相機依賴，所以我暫時未能調用視覺功能。",
            "The current environment is missing camera dependencies, so vision is unavailable right now.",
        )
    if error == "camera_not_found":
        return _localized_text(
            "我暂时没有找到可用的前置相机设备。",
            "我暫時未搵到可用嘅前置相機設備。",
            "I couldn't find an available front camera device right now.",
        )
    if error == "capture_failed":
        if device:
            return _localized_text(
                f"我找到相机了，但暂时没能从 {device} 抓到画面。",
                f"我搵到相機，但暫時未能由 {device} 擷取畫面。",
                f"I found the camera, but I couldn't capture a frame from {device} yet.",
            )
        return _localized_text(
            "我找到相机了，但暂时没能抓到画面。",
            "我搵到相機，但暫時未能擷取畫面。",
            "I found the camera, but I couldn't capture a frame yet.",
        )
    if error == "capture_timeout":
        if device:
            return _localized_text(
                f"我找到相机了，但这次从 {device} 抓图超时了。",
                f"我搵到相機，但今次由 {device} 擷取畫面超時。",
                f"I found the camera, but capturing a frame from {device} timed out this time.",
            )
        return _localized_text(
            "我找到相机了，但这次抓图超时了。",
            "我搵到相機，但今次擷取畫面超時。",
            "I found the camera, but capturing a frame timed out this time.",
        )
    if error == "http_429":
        return _localized_text(
            "我已经拍到画面了，但视觉服务现在有点忙，请你稍后再让我看一次。",
            "我已經影到畫面，但視覺服務而家有啲忙，遲啲再叫我睇一次啦。",
            "I captured the frame, but the vision service is busy right now. Please ask me again in a moment.",
        )
    if error == "http_503":
        return _localized_text(
            "我已经拍到画面了，但视觉服务现在比较繁忙，请稍后再问我一次。",
            "我已經影到畫面，但視覺服務而家比較繁忙，等陣再問我一次啦。",
            "I captured the frame, but the vision service is under heavy load right now. Please try again in a moment.",
        )
    if error.startswith("http_"):
        return _localized_text(
            "我已经拍到画面了，但视觉请求服务暂时失败了。",
            "我已經影到畫面，但視覺請求服務暫時失敗。",
            "I captured a frame, but the vision request to the service failed.",
        )
    return _localized_text(
        "抱歉，我这次没有成功看清前面的画面，你可以再让我看一次。",
        "唔好意思，我今次未成功睇清前面畫面，你可以再叫我睇一次。",
        "Sorry, I couldn't get a clear camera view that time. Please ask me to look again.",
    )


def _looks_like_vision_query(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    if any(
        token in normalized
        for token in (
            "你前面有什么",
            "你前面有什麼",
            "你前面有什么东西",
            "你前面有什麼東西",
            "你前面有咩",
            "你面前有什么",
            "你面前有什麼",
            "你面前有什么东西",
            "你面前有什麼東西",
            "你面前是什么",
            "你面前是什麼",
            "你面前是什么东西",
            "你面前是什麼東西",
            "你面前有咩",
            "现在面前有什么",
            "現在面前有什麼",
            "现在面前有什么东西",
            "現在面前有什麼東西",
            "现在面前是什么",
            "現在面前是什麼",
            "现在面前是什么东西",
            "現在面前是什麼東西",
            "现在前面有什么",
            "現在前面有什麼",
            "現在前面有什麼東西",
            "现在前面是什么",
            "現在前面是什麼",
            "现在前面是什么东西",
            "現在前面是什麼東西",
            "那你现在面前有什么",
            "那你現在面前有什麼",
            "那你現在面前有什麼東西",
            "那你现在面前是什么",
            "那你現在面前是什麼",
            "那你現在面前是什麼東西",
            "帮我看看",
            "幫我睇下",
            "幫我看看",
            "睇下",
            "看一下",
            "看一看",
            "看看前面",
            "看到什么",
            "看到什麼",
            "看到什么东西",
            "看到什麼東西",
            "睇到咩",
            "睇到啲咩",
            "睇到啲乜",
            "見到啲咩",
            "見到啲乜",
            "你看到什么",
            "你看到什麼",
            "你睇到咩",
            "你睇到啲咩",
            "你睇到啲乜",
            "你见到什么",
            "你見到什麼",
            "你見到咩",
            "你見到啲咩",
            "你見到啲乜",
            "你而家睇到啲咩",
            "你而家睇到啲乜",
            "你而家見到啲咩",
            "你而家見到啲乜",
            "你依家睇到啲咩",
            "你依家睇到啲乜",
            "你依家見到啲咩",
            "你依家見到啲乜",
            "前面是什么",
            "前面是什麼",
            "前面是什么东西",
            "前面是什麼東西",
            "前面有谁",
            "前面有誰",
            "前面有人吗",
            "前面有人嗎",
            "桌上有什么",
            "桌上有什麼",
            "画面里有什么",
            "畫面里有什麼",
            "畫面入面有咩",
            "what do you see",
            "can you see",
            "look in front",
            "look at the camera",
            "what is in front of you",
            "who do you see",
            "what's on the table",
        )
    ):
        return True
    compact_ascii = re.sub(r"[^a-z0-9]+", "", normalized)
    if not compact_ascii:
        return False
    return any(
        token in compact_ascii
        for token in (
            "whatdoyousee",
            "canyousee",
            "lookinfront",
            "lookatthecamera",
            "whatisinfrontofyou",
            "whodoyousee",
            "whatisonthetable",
            "whatsonthetable",
        )
    )


def _is_vision_query_valid(question: str) -> bool:
    if _looks_like_vision_query(question):
        return True
    return _is_recent_query_intent_valid("vision")


def _is_recent_query_intent_valid(kind: str) -> bool:
    latest_text, latest_at = _latest_user_text()
    now = time.monotonic()
    if not latest_text or now - latest_at > TOOL_INTENT_GUARD_WINDOW_S:
        return False
    if kind == "weather":
        return _looks_like_weather_query(latest_text)
    if kind == "news":
        return _looks_like_news_query(latest_text)
    if kind == "vision":
        return _looks_like_vision_query(latest_text)
    if kind == "locations":
        return looks_like_saved_locations_query(latest_text)
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
    if _looks_like_vision_query(text):
        question = _normalize_assistant_text(text)
        if question:
            return ("vision", question, f"vision:{question}")
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
            and _LAST_USER_STATE in {"", "listening"}
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


async def _evaluate_action_safety_local(action: str) -> tuple[bool, str]:
    decision = await precheck_body_action(
        VISION_CHAT_CONFIG,
        action=action,
        reply_language=REPLY_LANGUAGE_MANDARIN,
        unavailable_message=_localized_text(
            "我现在拿不到可靠的前方安全观察结果，所以先不执行这个动作。",
            "我而家攞唔到可靠嘅前方安全觀察結果，所以先唔做呢個動作。",
            "I can't get a reliable safety observation right now, so I won't execute that action yet.",
        ),
        denied_message=_localized_text(
            "基于当前前方安全观察，我先不执行这个动作。",
            "基于而家嘅前方安全观察，我先唔执行呢个动作。",
            "Based on the current safety observation, I won't execute that motion yet.",
        ),
    )
    if decision.allowed:
        return True, ""
    return False, decision.user_message


async def _evaluate_navigation_safety_local() -> tuple[bool, str]:
    decision = await precheck_navigation(
        VISION_CHAT_CONFIG,
        reply_language=REPLY_LANGUAGE_MANDARIN,
        unavailable_message=_localized_text(
            "我现在拿不到可靠的前方导航安全观察结果，所以先不启动导航。",
            "我而家攞唔到可靠嘅前方導航安全觀察結果，所以先唔啟動導航。",
            "I can't get a reliable front navigation safety observation right now, so I won't start navigation yet.",
        ),
        denied_message=_localized_text(
            "基于当前前方安全观察，我先不启动导航。",
            "基于而家嘅前方安全观察，我先唔启动导航。",
            "Based on the current safety observation, I won't start navigation yet.",
        ),
    )
    if decision.allowed:
        return True, ""
    return False, decision.user_message


async def _execute_action_local(action: str, *, source: str) -> str:
    if not G1_ADAPTER.available:
        return "G1 action tool unavailable"
    if ENABLE_SAFE_ACTION_GATEWAY:
        allowed, denial_text = await _evaluate_action_safety_local(action)
        if not allowed:
            return denial_text
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


async def _execute_vision_local(question: str, *, source: str) -> str:
    normalized_question = _normalize_assistant_text(question)
    if not normalized_question:
        return _localized_text(
            "我刚才没有听清你的视觉问题。",
            "我啱啱未聽清你個視覺問題。",
            "I didn't catch your visual question just now.",
        )
    _remember_latest_user_text(normalized_question)
    await asyncio.to_thread(_speak_local_tool_ack, _query_ack_text(normalized_question) or normalized_question)
    reply = await InterruptAssistant().ask_camera_vision(normalized_question)
    return _normalize_assistant_text(reply)


async def _list_saved_locations_local() -> str:
    if not G1_ADAPTER.navigation_available:
        return _localized_text(
            "导航工具当前不可用。",
            "導航工具而家未可用。",
            "Navigation tools are unavailable right now.",
        )
    result = await asyncio.to_thread(G1_ADAPTER.list_saved_locations, True)
    LOGGER.info(
        "list saved locations executed: ok=%s rc=%s stdout=%r stderr=%r",
        result.ok,
        result.returncode,
        result.stdout,
        result.stderr,
    )
    payload = _parse_command_json(result.stdout)
    if result.ok and payload is not None:
        return _format_locations_reply(payload)
    request_failed_text = _navigation_request_failed_text(payload)
    if request_failed_text is not None:
        return request_failed_text
    return _localized_text(
        "我暂时拿不到地点列表。",
        "我暫時拎唔到地點列表。",
        "I couldn't fetch the saved locations right now.",
    )


async def _navigate_to_saved_location_local(location: str, *, source: str) -> str:
    if looks_like_relative_motion_command(location):
        return _relative_motion_not_supported_text()
    if not G1_ADAPTER.navigation_available:
        return _localized_text(
            "导航工具当前不可用。",
            "導航工具而家未可用。",
            "Navigation tools are unavailable right now.",
        )
    if ENABLE_SAFE_ACTION_GATEWAY:
        allowed, denial_text = await _evaluate_navigation_safety_local()
        if not allowed:
            return denial_text
    await asyncio.to_thread(_speak_local_tool_ack, _navigation_ack_text(location))
    resolved_location = _resolve_navigation_location_label(location)
    wait_for_arrival_intro = _should_announce_intro_on_navigation_arrival(location, resolved_location)
    wait_timeout_s = float(
        os.getenv("INTERRUPT_NAV_ARRIVAL_WAIT_TIMEOUT_S", "180").strip() or "180"
    )
    result = await asyncio.to_thread(
        G1_ADAPTER.navigate_to_location,
        resolved_location,
        wait=wait_for_arrival_intro,
        wait_timeout_s=wait_timeout_s if wait_for_arrival_intro else 0.0,
    )
    LOGGER.info(
        "navigate to location executed: source=%s requested=%s resolved=%s wait_for_arrival_intro=%s ok=%s rc=%s stdout=%r stderr=%r",
        source,
        location,
        resolved_location,
        wait_for_arrival_intro,
        result.ok,
        result.returncode,
        result.stdout,
        result.stderr,
    )
    payload = _parse_command_json(result.stdout)
    if result.ok:
        if wait_for_arrival_intro:
            return _builtin_intro_reply()
        return _localized_text(
            f"正在前往{location}。",
            f"而家前往{location}。",
            f"Heading to {location} now.",
        )
    request_failed_text = _navigation_request_failed_text(payload)
    if request_failed_text is not None:
        return request_failed_text
    if payload and payload.get("error") == "location_not_found":
        return _format_locations_reply(payload)
    return _localized_text(
        f"暂时没法导航到{location}。",
        f"暫時未能導航去{location}。",
        f"I couldn't start navigation to {location} right now.",
    )


async def _remember_current_location_local(
    location: str,
    *,
    description: str = "",
    source: str,
) -> str:
    if not G1_ADAPTER.navigation_available:
        return _localized_text(
            "地点记忆工具当前不可用。",
            "地點記憶工具而家未可用。",
            "Location memory tools are unavailable right now.",
        )
    await asyncio.to_thread(_speak_local_tool_ack, _remember_location_ack_text(location))
    result = await asyncio.to_thread(
        G1_ADAPTER.remember_location,
        location,
        description=description,
    )
    LOGGER.info(
        "remember location executed: source=%s location=%s ok=%s rc=%s stdout=%r stderr=%r",
        source,
        location,
        result.ok,
        result.returncode,
        result.stdout,
        result.stderr,
    )
    if result.ok:
        return _localized_text(
            f"已经记住这里是{location}。",
            f"已經記住呢度係{location}。",
            f"I have remembered this place as {location}.",
        )
    return _localized_text(
        f"暂时没法记住{location}这个地点。",
        f"暫時未能記住{location}呢個地點。",
        f"I couldn't save {location} as a location right now.",
    )


async def _execute_local_text_tool_call(tool_call: LocalTextToolCall) -> str:
    name = tool_call.name
    arguments = tool_call.arguments
    if name == "perform_body_action":
        action = _normalize_body_action(str(arguments.get("action", "") or ""))
        if not action:
            return _localized_text(
                "我没有识别到明确动作，所以这次不执行任何动作。",
                "我未識別到明確動作，所以今次唔會執行任何動作。",
                "I did not detect a clear action, so I will not execute anything this time.",
            )
        result = await _execute_action_local(action, source="local_text_brain")
        if _looks_like_local_tool_failure(result):
            return result
        return _action_ack_text(action)
    if name == "set_led_color":
        color = _normalize_led_color(str(arguments.get("color", "") or ""))
        result = await _execute_led_color_local(color, source="local_text_brain")
        if _looks_like_local_tool_failure(result):
            return result
        return _led_ack_text(color)
    if name == "execute_robot_command_text":
        text = str(arguments.get("text", "") or "").strip()
        if not text:
            return _localized_text(
                "我没有拿到可执行的机器人命令文本。",
                "我冇收到可執行嘅機械人命令文本。",
                "I did not receive an executable robot command text.",
            )
        result = await _execute_direct_text_local(text, source="local_text_brain")
        if _looks_like_local_tool_failure(result):
            return result
        return _localized_text(
            "好的，正在执行。",
            "好啊，依家執行。",
            "Okay, executing now.",
        )
    if name == "ask_camera_vision":
        question = str(arguments.get("question", "") or "").strip()
        return await InterruptAssistant().ask_camera_vision(question)
    if name == "get_weather":
        location = str(arguments.get("location", "") or "").strip()
        return await InterruptAssistant().get_weather(location)
    if name == "get_news":
        topic = str(arguments.get("topic", "") or "").strip()
        return await InterruptAssistant().get_news(topic)
    if name == "list_saved_locations":
        return await _list_saved_locations_local()
    if name == "navigate_to_saved_location":
        location = str(arguments.get("location", "") or "").strip()
        return await _navigate_to_saved_location_local(location, source="local_text_brain")
    if name == "remember_current_location":
        location = str(arguments.get("location", "") or "").strip()
        description = str(arguments.get("description", "") or "").strip()
        return await _remember_current_location_local(
            location,
            description=description,
            source="local_text_brain",
        )
    return _localized_text(
        f"本地文本脑返回了暂未接入的工具：{name}",
        f"本地文本腦返回咗暫未接入嘅工具：{name}",
        f"The local text brain returned an unsupported tool: {name}.",
    )


async def _try_handle_local_text_decision(session: AgentSession, text: str) -> bool:
    offline_singlebox = _is_offline_singlebox_mode()
    if LOCAL_TEXT_DECISION_MODE == "disabled" and not offline_singlebox:
        return False
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return False
    if _should_ignore_user_backchannel(normalized):
        LOGGER.info("local_text_decision skipped for brief backchannel text=%r", normalized)
        return True
    if offline_singlebox:
        builtin_reply = _offline_singlebox_builtin_reply(normalized)
        if builtin_reply:
            _remember_latest_user_text(normalized)
            try:
                await session.interrupt(force=True)
            except Exception:
                LOGGER.debug("offline_singlebox interrupt skipped before builtin fast reply", exc_info=True)
            _speak_local_text_reply_fallback(builtin_reply)
            return True
    decision = await asyncio.to_thread(
        run_local_text_brain,
        dataclasses.replace(
            SETTINGS.agent,
            backend=(
                "local_text_openai_compatible"
                if SETTINGS.agent.local_text_provider == "openai_compatible"
                else "local_text_ollama"
            ),
        ),
        user_text=normalized,
        language=_preferred_reply_language(),
    )
    LOGGER.info(
        "local_text_decision: mode=%s ok=%s tool_calls=%s text_reply=%r error=%s user_text=%r",
        LOCAL_TEXT_DECISION_MODE,
        decision.ok,
        [tool.name for tool in decision.tool_calls],
        decision.text_reply,
        decision.error,
        normalized,
    )
    if LOCAL_TEXT_DECISION_MODE == "shadow" and not offline_singlebox:
        return False
    if not decision.ok:
        if offline_singlebox:
            if _looks_like_vision_query(normalized):
                _remember_latest_user_text(normalized)
                try:
                    await session.interrupt(force=True)
                except Exception:
                    LOGGER.debug("offline_singlebox interrupt skipped before direct vision fallback", exc_info=True)
                reply = await InterruptAssistant().ask_camera_vision(normalized)
                _speak_local_text_reply_fallback(reply)
                return True
            LOGGER.info(
                "offline_singlebox local_text unavailable, responding with local unavailable reply: user_text=%r error=%s",
                normalized,
                decision.error,
            )
            try:
                await session.interrupt(force=True)
            except Exception:
                LOGGER.debug("offline_singlebox interrupt skipped before unavailable reply", exc_info=True)
            _speak_local_text_reply_fallback(_offline_singlebox_unavailable_reply())
            return True
        return False
    if not decision.tool_calls and LOCAL_TEXT_DECISION_MODE != "prefer_all" and not offline_singlebox:
        return False
    if offline_singlebox:
        allowed_tool_calls = [
            tool_call for tool_call in decision.tool_calls if _tool_call_allowed_in_offline_singlebox(tool_call)
        ]
        blocked_tool_names = [
            tool_call.name for tool_call in decision.tool_calls if not _tool_call_allowed_in_offline_singlebox(tool_call)
        ]
        if blocked_tool_names:
            LOGGER.info(
                "offline_singlebox rejected local tool calls: blocked=%s user_text=%r",
                blocked_tool_names,
                normalized,
            )
        direct_reply = _extract_spoken_reply_text(decision.text_reply)
        if direct_reply:
            try:
                await session.interrupt(force=True)
            except Exception:
                LOGGER.debug("offline_singlebox interrupt skipped before direct local text reply", exc_info=True)
            _speak_local_text_reply_fallback(direct_reply)
            return True
        if not allowed_tool_calls:
            try:
                await session.interrupt(force=True)
            except Exception:
                LOGGER.debug("offline_singlebox interrupt skipped after out-of-scope request", exc_info=True)
            _speak_local_text_reply_fallback(_offline_singlebox_limit_reply())
            return True
        else:
            decision = dataclasses.replace(
                decision,
                tool_calls=allowed_tool_calls[:2],
                text_reply="",
            )

    _remember_latest_user_text(normalized)
    try:
        await session.interrupt(force=True)
    except Exception:
        LOGGER.debug("local_text_decision interrupt skipped or failed", exc_info=True)

    replies: list[str] = []
    for tool_call in decision.tool_calls[:2]:
        reply = await _execute_local_text_tool_call(tool_call)
        reply = _normalize_assistant_text(reply)
        if reply:
            replies.append(reply)
    final_reply = next((reply for reply in replies if reply), "")
    if not final_reply and decision.text_reply:
        final_reply = _normalize_assistant_text(decision.text_reply)
    if not final_reply and not decision.tool_calls and LOCAL_TEXT_DECISION_MODE == "prefer_all":
        final_reply = _localized_text(
            "我先切到本地对话链了，不过这句暂时还没有生成稳定回复。",
            "我而家已經切到本地對話鏈，不過呢句暫時未生成穩定回覆。",
            "I switched to the local dialogue path, but I do not have a stable reply for that yet.",
        )
    if _looks_like_tool_payload_text(final_reply):
        LOGGER.warning("local_text_decision final reply looked like tool payload; replacing text=%r", final_reply)
        final_reply = _localized_text(
            "我刚才没有稳定组织好回答，请再问我一次。",
            "我頭先未穩定組織好回覆，請再問我一次。",
            "I did not form that reply cleanly just now. Please ask me again.",
        )
    if final_reply:
        try:
            session.say(
                final_reply,
                allow_interruptions=SETTINGS.agent.allow_interruptions,
                add_to_chat_ctx=True,
            )
        except RuntimeError as exc:
            if _should_skip_local_tts_fallback():
                LOGGER.warning(
                    "local_text_decision session.say unavailable, suppress local speak in transport_only mode: error=%s text=%r",
                    exc,
                    final_reply,
                )
            else:
                LOGGER.warning(
                    "local_text_decision session.say unavailable, fallback to local speak: error=%s text=%r",
                    exc,
                    final_reply,
                )
                _speak_local_text_reply_fallback(final_reply)
    return True


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
        agent_kwargs = {
            "instructions": _effective_instructions(),
        }
        if _is_local_text_room_backend():
            agent_kwargs.update(
                llm=None,
                stt=None,
                tts=None,
                turn_detection="manual",
            )
        super().__init__(**agent_kwargs)

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
        name="check_action_safety",
        description="Check whether a body action is currently safe using the front-camera observation.",
    )
    async def check_action_safety(self, action: str) -> str:
        normalized_action = _normalize_body_action(action)
        result = await asyncio.to_thread(
            ask_camera_question,
            VISION_CHAT_CONFIG,
            question="请检查前方空间、人体接近情况，以及手臂活动范围附近是否有遮挡物。",
            reply_language=REPLY_LANGUAGE_MANDARIN,
            structured=True,
        )
        if not result.ok:
            return json.dumps(
                {
                    "ok": False,
                    "error": result.error,
                    "camera_device": result.camera_device,
                },
                ensure_ascii=False,
            )
        decision = evaluate_action_safety(normalized_action, result.observation)
        return json.dumps(
            {
                "ok": True,
                "action": normalized_action,
                "allowed": decision.allowed,
                "reason_code": decision.reason_code,
                "reason_text": decision.reason_text,
                "observation": result.observation,
                "camera_device": result.camera_device,
            },
            ensure_ascii=False,
        )

    @function_tool(
        name="check_navigation_safety",
        description="Check whether it is currently safe to start navigation using the front-camera observation.",
    )
    async def check_navigation_safety(self) -> str:
        result = await asyncio.to_thread(
            ask_camera_question,
            VISION_CHAT_CONFIG,
            question="请检查前方空间是否通畅、是否有人离得太近，以及当前画面是否足够清晰。",
            reply_language=REPLY_LANGUAGE_MANDARIN,
            structured=True,
        )
        if not result.ok:
            return json.dumps(
                {
                    "ok": False,
                    "error": result.error,
                    "camera_device": result.camera_device,
                },
                ensure_ascii=False,
            )
        decision = evaluate_navigation_safety(result.observation)
        return json.dumps(
            {
                "ok": True,
                "allowed": decision.allowed,
                "reason_code": decision.reason_code,
                "reason_text": decision.reason_text,
                "observation": result.observation,
                "camera_device": result.camera_device,
            },
            ensure_ascii=False,
        )

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
        name="list_saved_locations",
        description="List the saved navigation locations currently available on the robot.",
    )
    async def list_saved_locations(self) -> str:
        if not _is_recent_query_intent_valid("locations"):
            latest_text, _ = _latest_user_text()
            LOGGER.warning(
                "reject saved locations tool execution due to mismatched latest user intent: latest_user_text=%r",
                latest_text,
            )
            return _localized_text(
                "刚才没有听到明确的地点列表请求，我先不查询地点。",
                "啱啱未聽到明確嘅地點列表要求，我而家先唔查。",
                "I didn't hear a clear request for the saved locations just now, so I won't list them yet.",
            )
        return await _list_saved_locations_local()

    @function_tool(
        name="navigate_to_saved_location",
        description="Navigate to one saved destination by exact location label only.",
    )
    async def navigate_to_saved_location(self, location: str) -> str:
        normalized_location = location.strip()
        if looks_like_relative_motion_command(normalized_location):
            return _relative_motion_not_supported_text()
        if not _is_recent_user_intent_valid("navigate", normalized_location):
            latest_text, _ = _latest_user_text()
            LOGGER.warning(
                "reject navigate tool execution due to mismatched latest user intent: location=%r latest_user_text=%r",
                normalized_location,
                latest_text,
            )
            return _localized_text(
                "刚才没有听到明确的目标地点导航请求，我先不启动导航。",
                "啱啱未聽到明確嘅目標地點導航要求，我而家先唔啟動導航。",
                "I didn't hear a clear destination navigation request just now, so I won't start navigation yet.",
            )
        return await _navigate_to_saved_location_local(normalized_location, source="tool")

    @function_tool(
        name="remember_current_location",
        description="Save the robot's current position as a named location.",
    )
    async def remember_current_location(self, location: str, description: str = "") -> str:
        normalized_location = location.strip()
        if not _is_recent_user_intent_valid("remember_location", normalized_location):
            latest_text, _ = _latest_user_text()
            LOGGER.warning(
                "reject remember location tool execution due to mismatched latest user intent: location=%r latest_user_text=%r",
                normalized_location,
                latest_text,
            )
            return _localized_text(
                "刚才没有听到明确的记地点请求，我先不保存。",
                "啱啱未聽到明確嘅記地點要求，我而家先唔保存。",
                "I didn't hear a clear request to save this location just now, so I won't save it yet.",
            )
        return await _remember_current_location_local(
            normalized_location,
            description=description.strip(),
            source="tool",
        )

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

    @function_tool(
        name="ask_camera_vision",
        description=(
            "Look at the robot's current front camera view and answer a visual question "
            "about what is directly visible right now."
        ),
    )
    async def ask_camera_vision(self, question: str = "") -> str:
        """
        Ask a visual question using the current front camera snapshot.

        Args:
            question: Visual question such as 你前面有什么, 你看到谁, 桌上有什么.
        """
        if not SETTINGS.vision.enabled:
            return _vision_failure_text("vision_disabled")
        if not _is_vision_query_valid(question):
            latest_text, _ = _latest_user_text()
            LOGGER.warning(
                "reject vision tool execution due to mismatched vision intent: question=%r latest_user_text=%r",
                question,
                latest_text,
            )
            return _localized_text(
                "刚才我没有听到明确的视觉问题，所以先不看相机画面。",
                "啱啱我未聽到明確要我睇畫面，所以而家先唔開相機。",
                "I didn't hear a clear visual question just now, so I won't inspect the camera yet.",
            )
        result = await asyncio.to_thread(
            ask_camera_question,
            VISION_CHAT_CONFIG,
            question=question,
            reply_language=_preferred_reply_language(),
        )
        if not result.ok:
            LOGGER.warning(
                "camera vision query failed: question=%r error=%s device=%s",
                question,
                result.error,
                result.camera_device,
            )
            return _vision_failure_text(result.error, device=result.camera_device)
        LOGGER.info(
            "camera vision query succeeded: question=%r device=%s answer=%r",
            question,
            result.camera_device,
            result.answer,
        )
        return result.answer

    @function_tool(
        name="observe_camera_scene",
        description=(
            "Inspect the robot's current front camera view and return a structured JSON observation "
            "for safety-aware reasoning."
        ),
    )
    async def observe_camera_scene(self, question: str = "") -> str:
        if not SETTINGS.vision.enabled:
            return json.dumps(
                {
                    "ok": False,
                    "error": "vision_disabled",
                },
                ensure_ascii=False,
            )
        if not _is_vision_query_valid(question):
            latest_text, _ = _latest_user_text()
            LOGGER.warning(
                "reject structured vision tool execution due to mismatched vision intent: question=%r latest_user_text=%r",
                question,
                latest_text,
            )
            return json.dumps(
                {
                    "ok": False,
                    "error": "vision_intent_mismatch",
                },
                ensure_ascii=False,
            )
        result = await asyncio.to_thread(
            ask_camera_question,
            VISION_CHAT_CONFIG,
            question=question,
            reply_language=_preferred_reply_language(),
            structured=True,
        )
        if not result.ok:
            LOGGER.warning(
                "structured camera observation failed: question=%r error=%s device=%s",
                question,
                result.error,
                result.camera_device,
            )
            return json.dumps(
                {
                    "ok": False,
                    "error": result.error,
                    "camera_device": result.camera_device,
                },
                ensure_ascii=False,
            )
        payload = {
            "ok": True,
            "camera_device": result.camera_device,
            "observation": result.observation or {},
        }
        LOGGER.info(
            "structured camera observation succeeded: question=%r device=%s observation=%r",
            question,
            result.camera_device,
            payload["observation"],
        )
        return json.dumps(payload, ensure_ascii=False)

def _effective_instructions() -> str:
    ack = SETTINGS.agent.interruption_acknowledgement.strip()
    extra = (
        "\n\n语言与打断交互规则：\n"
        "1. 默认跟随用户最近一轮输入所使用的语言回答；用户说普通话就用普通话，用户说粤语/广东话就用粤语，用户说英语就用英语。\n"
        "2. 只有当用户明确要求切换回复语言时，才暂时固定使用该语言；当用户要求恢复自动或按他说的语言回答时，恢复自动跟随。\n"
        "3. 一旦当前轮次的目标回复语言已经确定，你整段回复都必须只使用该语言，不要混用，不要因为用户说得短、含糊、重复或夹杂语气词就默认切回中文。\n"
        "4. 如果目标语言是英语，就只用自然英语完整回答；如果目标语言是粤语，就只用自然粤语完整回答；如果目标语言是普通话，就只用普通话完整回答。\n"
        "5. 当用户在你说话时插话，立即停止当前回答，优先听用户新的话。\n"
        f"6. 如果用户的打断意图是让你停下、暂停、闭嘴、等一下、先别说了，请只做一句很短的确认回复：普通话可用“{ack}”；粤语和英语也要用对应语言表达同样意思。\n"
        "7. 不要为这类打断重复解释，也不要继续之前那段回答。\n"
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
            "6. 当用户明确询问你看到了什么、前面有什么、某个物体/人是否在画面里、帮他看看眼前场景时，优先调用 ask_camera_vision。\n"
            "7. 当你需要为安全判断、空间判断、障碍判断提供结构化结果时，优先调用 observe_camera_scene。\n"
            "8. 视觉工具只回答画面中能直接看到的内容；如果当前没有视觉能力或画面不清楚，要诚实说明。\n"
            "9. 当用户问有哪些已保存地点、可以去哪里时，优先调用 list_saved_locations。\n"
            "10. 当用户明确说“带我去某地 / 去某地 / navigate to 某地”时，优先调用 navigate_to_saved_location，参数只填地点名。\n"
            "11. 当用户明确说“记住这里是某地 / save this location as ...”时，优先调用 remember_current_location。\n"
            "12. 不要把“往前走几步、后退一点、转个圈、左转右转”这类相对运动命令错误映射成地点导航；当前这类命令只能如实说明暂不支持。\n"
            "13. 工具执行成功后，用一句简短确认告知用户已经开始执行或已经完成，并保持和用户当前语言一致。\n"
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


def _require_supported_room_agent_backend() -> None:
    backend = SETTINGS.agent.backend
    if backend == "gemini_realtime":
        if not SETTINGS.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY 未设置，无法启动 LiveKit Gemini Agent。")
        return
    if backend in {"local_text_ollama", "local_text_openai_compatible"}:
        LOGGER.info(
            "room agent backend enabled: backend=%s runtime_mode=%s local_text_mode=%s",
            backend,
            SETTINGS.agent.runtime_mode,
            SETTINGS.agent.local_text_decision_mode,
        )
        return
    raise RuntimeError(f"unsupported agent backend: {backend}")


def _is_local_text_room_backend() -> bool:
    return SETTINGS.agent.backend in {"local_text_ollama", "local_text_openai_compatible"}


def _build_session() -> AgentSession:
    _require_supported_room_agent_backend()
    mcp_servers = build_mcp_servers(SETTINGS)
    if not mcp_servers:
        LOGGER.warning("未配置可用 MCP/HTTP 实时工具；天气走本地接口，新闻走 RSS 直连，其他外部实时数据能力有限。")
    if _is_local_text_room_backend():
        return AgentSession(
            llm=None,
            stt=None,
            tts=None,
            turn_detection="manual",
            mcp_servers=mcp_servers,
            allow_interruptions=SETTINGS.agent.allow_interruptions,
            min_endpointing_delay=SETTINGS.agent.min_endpointing_delay_ms / 1000,
            max_endpointing_delay=SETTINGS.agent.max_endpointing_delay_ms / 1000,
            min_interruption_duration=SETTINGS.agent.min_interruption_duration_ms / 1000,
            false_interruption_timeout=SETTINGS.agent.false_interruption_timeout_ms / 1000,
            discard_audio_if_uninterruptible=True,
            aec_warmup_duration=SETTINGS.agent.aec_warmup_duration_ms / 1000,
            user_away_timeout=USER_AWAY_TIMEOUT_S,
        )
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
        "http_options": _gemini_realtime_http_options(),
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
        language=_preferred_reply_language(),
        normalize_tts_text=_normalize_tts_text,
    )


def _mirror_assistant_text_to_om1_async(text: str) -> None:
    SPEECH_FEEDBACK.speak_assistant_reply_async(
        text,
        language=_preferred_reply_language(),
        normalize_tts_text=_normalize_tts_text,
    )


def _speak_local_text_reply_fallback(text: str) -> bool:
    normalized = _normalize_tts_text(text)
    if not normalized:
        return False
    language = _preferred_reply_language()
    if SPEECH_FEEDBACK.speak_forced_local_reply(
        normalized,
        language=language,
        normalize_tts_text=_normalize_tts_text,
    ):
        _remember_recent_assistant_reply(normalized)
        _mark_agent_speech_ended()
        LOGGER.info("local text reply fallback spoke via local TTS: language=%s text=%r", language, normalized)
        return True
    return False


def _should_skip_local_tts_fallback() -> bool:
    assistant_mode = str(getattr(SETTINGS.feedback, "assistant_audio_mode", "") or "").strip().lower()
    tool_ack_mode = str(getattr(SETTINGS.feedback, "local_tool_ack_audio_mode", "") or "").strip().lower()
    return assistant_mode == "transport_only" and tool_ack_mode == "transport_only"


def _transport_only_assistant_audio() -> bool:
    assistant_mode = str(getattr(SETTINGS.feedback, "assistant_audio_mode", "") or "").strip().lower()
    return assistant_mode == "transport_only"


def _frontgate_ready_prompt_instructions(text: str) -> str:
    normalized = _normalize_assistant_text(text) or "现在可以了"
    return (
        "这是一次前门进入房间成功后的就绪提示。"
        f"请立刻只说这一句，不要改写，不要补充，不要调用工具：{normalized}"
    )


async def _route_frontgate_text_input(session: AgentSession, text: str, language_hint: str = "") -> bool:
    normalized = _normalize_assistant_text(text)
    if not normalized:
        return False
    _mark_effective_user_input(normalized)
    _remember_reply_language_preference(normalized, language_hint)
    _remember_latest_user_text(normalized)
    turn_language = _preferred_reply_language()
    turn_instructions = _reply_language_instruction(turn_language)
    if SETTINGS.agent.backend == "gemini_realtime":
        try:
            session.generate_reply(
                user_input=normalized,
                instructions=turn_instructions,
                allow_interruptions=SETTINGS.agent.allow_interruptions,
                input_modality="text",
            )
            LOGGER.info(
                "frontgate text input routed to gemini_realtime: text=%r language=%s",
                normalized,
                turn_language,
            )
            return True
        except RuntimeError as exc:
            message = str(exc)
            if "isn't running" in message or "is closing" in message:
                LOGGER.warning(
                    "frontgate text input dropped because AgentSession is no longer running; requesting room exit: text=%r error=%s",
                    normalized,
                    message,
                )
                _signal_frontgate_session_exit("agent_session_not_running")
                return False
            LOGGER.exception("frontgate text input route failed for gemini_realtime: text=%r", normalized)
            return False
        except Exception:
            LOGGER.exception("frontgate text input route failed for gemini_realtime: text=%r", normalized)
            return False
    handled = await _try_handle_local_text_decision(session, normalized)
    LOGGER.info("frontgate text input routed to local_text backend: handled=%s text=%r", handled, normalized)
    return handled


def _wire_debug_events(session: AgentSession) -> None:
    interrupted_while_speaking = {"value": False}
    mirrored_texts: set[str] = set()
    rt_hooks_bound = {"value": False}
    loop = asyncio.get_running_loop()
    idle_shutdown_started = {"value": False}
    _reset_effective_user_input_timer()

    async def _monitor_user_input_idle() -> None:
        if not ENABLE_FRONTGATE_IDLE_SESSION_EXIT:
            LOGGER.info("frontgate idle session exit disabled; keeping multi-turn session active")
            return
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
        if kind == "vision":
            async def _run_vision_fastpath() -> None:
                reply = await _execute_vision_local(payload, source="fastpath")
                if not reply:
                    return
                try:
                    session.say(
                        reply,
                        allow_interruptions=SETTINGS.agent.allow_interruptions,
                        add_to_chat_ctx=True,
                    )
                except RuntimeError as exc:
                    LOGGER.warning(
                        "vision fastpath session.say unavailable, fallback to local speak: error=%s text=%r",
                        exc,
                        reply,
                    )
                    _speak_local_text_reply_fallback(reply)

            asyncio.create_task(_run_vision_fastpath())
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
        old_state = getattr(ev, "old_state", "")
        new_state = getattr(ev, "new_state", "")
        _update_session_states(agent_state=new_state)
        LOGGER.info(
            "agent_state_changed: %s -> %s",
            old_state,
            new_state,
        )
        if old_state == "speaking" and new_state == "listening":
            _mark_agent_speech_ended()
        if old_state == "initializing" and new_state == "listening":
            _resume_active_listen_led_delayed("room_ready")

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
        if transcript and _should_ignore_low_information_transcript(transcript):
            LOGGER.info(
                "user_input_transcribed ignored low-information transcript: final=%s text=%r",
                is_final,
                transcript,
            )
            if is_final:
                interrupted_while_speaking["value"] = False
            return
        if transcript and _should_ignore_post_speech_gibberish(transcript):
            LOGGER.info(
                "user_input_transcribed ignored post-speech short gibberish: final=%s text=%r",
                is_final,
                transcript,
            )
            if is_final:
                interrupted_while_speaking["value"] = False
            return
        if transcript and _looks_like_recent_assistant_reply_echo(transcript):
            LOGGER.info(
                "user_input_transcribed ignored recent assistant reply echo: final=%s text=%r",
                is_final,
                transcript,
            )
            if is_final:
                interrupted_while_speaking["value"] = False
            return
        if local_playback_guard_active() and _should_ignore_user_backchannel(transcript):
            LOGGER.info(
                "user_input_transcribed ignored during local playback guard: final=%s text=%r",
                is_final,
                transcript,
            )
            if is_final:
                interrupted_while_speaking["value"] = False
            return
        if transcript and should_ignore_transcript(transcript):
            LOGGER.info(
                "user_input_transcribed ignored probable self-playback echo: final=%s text=%r",
                is_final,
                transcript,
            )
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
                loop.create_task(_try_handle_local_text_decision(session, transcript))
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
            if _should_ignore_low_information_transcript(text):
                LOGGER.info(
                    "conversation_item_added ignored low-information user text=%r",
                    text,
                )
                return
            if _should_ignore_post_speech_gibberish(text):
                LOGGER.info(
                    "conversation_item_added ignored post-speech short gibberish text=%r",
                    text,
                )
                return
            if local_playback_guard_active() and _should_ignore_user_backchannel(text):
                LOGGER.info(
                    "conversation_item_added ignored during local playback guard text=%r",
                    text,
                )
                return
            if should_ignore_transcript(text):
                LOGGER.info("conversation_item_added ignored probable self-playback echo text=%r", text)
                return
            _mark_effective_user_input(text)
            _remember_reply_language_preference(text)
            _remember_latest_user_text(text)
            loop.create_task(_try_handle_local_query_ack(text))
            loop.create_task(_try_handle_robot_fastpath(text))
            return
        if role != "assistant" or interrupted or not text:
            return
        _log_assistant_language_alignment(text)
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
    LOGGER.info(
        "agent backend selected: backend=%s runtime_mode=%s model=%s local_text_decision_mode=%s local_text_provider=%s local_text_model=%s",
        SETTINGS.agent.backend,
        SETTINGS.agent.runtime_mode,
        SETTINGS.agent.model,
        SETTINGS.agent.local_text_decision_mode,
        SETTINGS.agent.local_text_provider,
        SETTINGS.agent.local_text_model,
    )
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

    @ctx.room.on("data_received")
    def _on_room_data(packet) -> None:
        topic = str(getattr(packet, "topic", "") or "")
        payload = getattr(packet, "data", b"") or b""
        if topic == "interrupt/frontgate/room_ready_ack":
            try:
                text = payload.decode("utf-8", errors="ignore").strip()
            except Exception:
                text = ""
            if not text:
                return

            async def _relay_ready_prompt() -> None:
                ok = True
                mode = "session_say"
                try:
                    session.say(
                        text,
                        allow_interruptions=SETTINGS.agent.allow_interruptions,
                        add_to_chat_ctx=False,
                    )
                except Exception:
                    mode = "local_tts_fallback"
                    LOGGER.warning(
                        "frontgate ready prompt relay session.say unavailable, fallback to local speak: text=%r",
                        text,
                        exc_info=True,
                    )
                    ok = await asyncio.to_thread(_speak_local_text_reply_fallback, text)
                else:
                    ok = True
                LOGGER.info("frontgate ready prompt relay: ok=%s mode=%s text=%r", ok, mode, text)

            asyncio.create_task(_relay_ready_prompt())
            return

        if topic != "interrupt/local_text/transcript":
            return

        try:
            message = json.loads(payload.decode("utf-8", errors="ignore"))
        except Exception:
            LOGGER.warning("room transcript data decode failed", exc_info=True)
            return
        text = _normalize_assistant_text(str(message.get("text", "") or ""))
        language_hint = str(message.get("language", "") or "")
        text_input_only = bool(message.get("text_input_only")) or FRONTGATE_TEXT_INPUT_ONLY
        identity = str(getattr(packet, "participant", None) and getattr(packet.participant, "identity", "") or "")
        if identity and identity != SETTINGS.rtc_endpoint.identity:
            return
        if not text:
            return
        _remember_reply_language_preference(text, language_hint)
        _remember_latest_user_text(text)
        if (
            (_looks_like_self_echo_transcript(text) or should_ignore_transcript(text))
            or _looks_like_recent_assistant_reply_echo(text)
            or _looks_like_recent_assistant_reprompt(text)
            or (local_playback_guard_active() and _should_ignore_user_backchannel(text))
        ):
            LOGGER.info("room transcript data ignored during local playback guard: text=%r", text)
            return
        if _should_ignore_low_information_transcript(text) or _should_ignore_post_speech_gibberish(text):
            LOGGER.info("room transcript data ignored in local_text backend: text=%r", text)
            return

        async def _run_text_from_data() -> None:
            if text_input_only:
                handled = await _route_frontgate_text_input(session, text, language_hint)
                LOGGER.info("room transcript data handled in frontgate text-only mode: handled=%s text=%r", handled, text)
                return
            handled = await _try_handle_local_text_decision(session, text)
            LOGGER.info("room transcript data handled by local_text backend: handled=%s text=%r", handled, text)

        asyncio.create_task(_run_text_from_data())

    room_io = getattr(session, "_room_io", None)
    if room_io is not None:
        room_io.set_participant(SETTINGS.rtc_endpoint.identity)
        LOGGER.info("room input participant pinned: %s", SETTINGS.rtc_endpoint.identity)

    if _is_local_text_room_backend():
        local_text_busy = {"value": False}
        pending_room_transcript = {"text": ""}

        @ctx.room.on("transcription_received")
        def _on_room_transcription(segments, participant, _publication) -> None:
            identity = str(getattr(participant, "identity", "") or "")
            if identity != SETTINGS.rtc_endpoint.identity:
                return
            final_texts = [
                _normalize_assistant_text(getattr(segment, "text", "") or "")
                for segment in (segments or [])
                if getattr(segment, "final", False)
            ]
            text = next((item for item in final_texts if item), "")
            if not text:
                return
            if should_ignore_transcript(text) or (
                local_playback_guard_active() and _should_ignore_user_backchannel(text)
            ):
                LOGGER.info(
                    "room transcription ignored during local playback guard: identity=%s text=%r",
                    identity,
                    text,
                )
                return
            if _looks_like_recent_assistant_reply_echo(text):
                LOGGER.info("room transcription ignored recent assistant reply echo: identity=%s text=%r", identity, text)
                return
            if _should_ignore_low_information_transcript(text) or _should_ignore_post_speech_gibberish(text):
                LOGGER.info("room transcription ignored in local_text backend: identity=%s text=%r", identity, text)
                return
            if local_text_busy["value"]:
                pending_room_transcript["text"] = text
                LOGGER.info("room transcription queued while local_text backend busy: text=%r", text)
                return

            async def _run_local_text() -> None:
                local_text_busy["value"] = True
                try:
                    current_text = text
                    current_identity = identity
                    while current_text:
                        pending_room_transcript["text"] = ""
                        handled = await _try_handle_local_text_decision(session, current_text)
                        LOGGER.info(
                            "room transcription handled by local_text backend: handled=%s identity=%s text=%r",
                            handled,
                            current_identity,
                            current_text,
                        )
                        current_text = pending_room_transcript["text"]
                        current_identity = SETTINGS.rtc_endpoint.identity
                finally:
                    local_text_busy["value"] = False

            asyncio.create_task(_run_local_text())


async def on_request(req: JobRequest) -> None:
    room_name = getattr(req.room, "name", "room")
    LOGGER.info(
        "接受 job request: room=%s job_id=%s",
        room_name,
        req.id,
    )
    await req.accept()


_server_kwargs = {
    "job_executor_type": _job_executor_type(),
    "ws_url": SETTINGS.livekit.url,
    "api_key": SETTINGS.livekit.api_key,
    "api_secret": SETTINGS.livekit.api_secret,
    "http_proxy": _livekit_proxy(),
    # Keep robot-side worker bootstrap light. The embedded box does not benefit
    # from prewarming multiple idle job processes before it has even registered
    # with LiveKit, and that startup cost can delay or derail frontgate handoff.
    "num_idle_processes": max(0, _env_int("INTERRUPT_AGENT_NUM_IDLE_PROCESSES") or 0),
    "initialize_process_timeout": max(
        10.0,
        _env_float("INTERRUPT_AGENT_INITIALIZE_PROCESS_TIMEOUT_S") or 30.0,
    ),
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
