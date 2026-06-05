from __future__ import annotations

import os
import re
from dataclasses import dataclass


_SEPARATOR_RE = r"[\s,，。！？!?、;；:：-]*"
_TRAILING_RE = re.compile(rf"^{_SEPARATOR_RE}")

_DEFAULT_PREFIXES = {
    "zh": "你好，机器人|你好机器人|你好，機器人|你好機器人|机器人，你好|机器人你好|機器人，你好|機器人你好",
    "zh-YUE": "你好，機器人|你好機器人|你好，机器人|你好机器人|機器人，你好|機器人你好|机器人，你好|机器人你好",
    "en": "Hello, Robot|Hello Robot|Hi, Robot|Hi Robot|Hey, Robot|Hey Robot|Oh, Robot|Oh Robot",
}

_DEFAULT_PENDING_PREFIXES = {
    "zh": "你好",
    "zh-YUE": "你好",
    "en": "Hello|Hi|Hey|Oh",
}

_DEFAULT_ROBOT_TERMS = {
    "zh": "机器人|機器人",
    "zh-YUE": "機器人|机器人",
    "en": "Robot",
}


@dataclass(frozen=True)
class FrontgateWatchdogDecision:
    action: str
    language: str
    prefix: str
    content: str


def frontgate_watchdog_enabled() -> bool:
    raw = os.getenv("INTERRUPT_FRONTGATE_WATCHDOG_ENABLED", "0").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def normalize_watchdog_language(language: str) -> str:
    normalized = (language or "").strip().lower()
    alias_map = {
        "": "",
        "zh": "zh",
        "zh-cn": "zh",
        "cmn": "zh",
        "mandarin": "zh",
        "yue": "zh-YUE",
        "zh-yue": "zh-YUE",
        "cantonese": "zh-YUE",
        "en": "en",
        "en-us": "en",
        "en-gb": "en",
        "english": "en",
    }
    return alias_map.get(normalized, "")


def followup_window_s() -> float:
    raw = os.getenv("INTERRUPT_FRONTGATE_WATCHDOG_FOLLOWUP_WINDOW_S", "6").strip()
    try:
        return max(0.0, float(raw or "6"))
    except ValueError:
        return 6.0


def pending_prefix_window_s() -> float:
    raw = os.getenv("INTERRUPT_FRONTGATE_WATCHDOG_PENDING_PREFIX_WINDOW_S", "3.5").strip()
    try:
        return max(0.0, float(raw or "3.5"))
    except ValueError:
        return 3.5


def evaluate_frontgate_text(text: str, *, default_language: str = "") -> FrontgateWatchdogDecision:
    normalized_text = " ".join((text or "").split()).strip()
    if not normalized_text:
        return FrontgateWatchdogDecision("drop", "", "", "")
    if not frontgate_watchdog_enabled():
        return FrontgateWatchdogDecision(
            action="accepted",
            language=normalize_watchdog_language(default_language),
            prefix="",
            content=normalized_text,
        )

    preferred_language = normalize_watchdog_language(default_language)
    language_order = [language for language in (preferred_language, "zh", "zh-YUE", "en") if language]
    seen: set[str] = set()
    ordered_languages: list[str] = []
    for language in language_order:
        if language in seen:
            continue
        seen.add(language)
        ordered_languages.append(language)

    for language in ordered_languages:
        for alias in _prefix_aliases(language):
            match = _candidate_pattern(alias).match(normalized_text)
            if match is None:
                continue
            rest = _TRAILING_RE.sub("", match.group("rest") or "").strip()
            if not rest:
                return FrontgateWatchdogDecision("prefix_only", language, alias, "")
            return FrontgateWatchdogDecision("accepted", language, alias, rest)
    for language in ordered_languages:
        for alias in _robot_term_aliases(language):
            match = _candidate_pattern(alias).match(normalized_text)
            if match is None:
                continue
            rest = _TRAILING_RE.sub("", match.group("rest") or "").strip()
            if not rest:
                return FrontgateWatchdogDecision("prefix_only", language, alias, "")
            if _looks_like_explicit_user_request(rest, language=language):
                return FrontgateWatchdogDecision("accepted", language, alias, rest)
    return FrontgateWatchdogDecision("drop", preferred_language, "", "")


def detect_pending_prefix_fragment(text: str, *, default_language: str = "") -> FrontgateWatchdogDecision:
    normalized_text = " ".join((text or "").split()).strip()
    if not normalized_text:
        return FrontgateWatchdogDecision("drop", "", "", "")
    compact_text = _compact_watchdog_text(normalized_text)
    if not compact_text:
        return FrontgateWatchdogDecision("drop", "", "", "")
    preferred_language = normalize_watchdog_language(default_language)
    language_order = [language for language in (preferred_language, "zh", "zh-YUE", "en") if language]
    seen: set[str] = set()
    ordered_languages: list[str] = []
    for language in language_order:
        if language in seen:
            continue
        seen.add(language)
        ordered_languages.append(language)
    for language in ordered_languages:
        for alias in _pending_prefix_aliases(language):
            if _exact_candidate_pattern(alias).match(normalized_text):
                return FrontgateWatchdogDecision("pending_prefix", language, alias, "")
        for alias in _prefix_aliases(language):
            compact_alias = _compact_watchdog_text(alias)
            if not compact_alias:
                continue
            if compact_text == compact_alias:
                continue
            if compact_alias.startswith(compact_text) and _is_meaningful_pending_fragment(compact_text):
                return FrontgateWatchdogDecision("pending_prefix", language, normalized_text, "")
    return FrontgateWatchdogDecision("drop", preferred_language, "", "")


def text_starts_with_robot_term(text: str, *, language: str = "") -> bool:
    normalized_text = " ".join((text or "").split()).strip()
    if not normalized_text:
        return False
    normalized_language = normalize_watchdog_language(language)
    for candidate_language in [lang for lang in (normalized_language, "zh", "zh-YUE", "en") if lang]:
        for alias in _robot_term_aliases(candidate_language):
            if _candidate_pattern(alias).match(normalized_text):
                return True
            if _exact_candidate_pattern(alias).match(normalized_text):
                return True
    return False


def _prefix_aliases(language: str) -> tuple[str, ...]:
    env_name = {
        "zh": "INTERRUPT_FRONTGATE_WATCHDOG_PREFIX_ZH",
        "zh-YUE": "INTERRUPT_FRONTGATE_WATCHDOG_PREFIX_YUE",
        "en": "INTERRUPT_FRONTGATE_WATCHDOG_PREFIX_EN",
    }.get(language, "")
    raw = os.getenv(env_name, _DEFAULT_PREFIXES.get(language, "")).strip()
    return tuple(item.strip() for item in raw.split("|") if item.strip())


def _pending_prefix_aliases(language: str) -> tuple[str, ...]:
    env_name = {
        "zh": "INTERRUPT_FRONTGATE_WATCHDOG_PENDING_PREFIX_ZH",
        "zh-YUE": "INTERRUPT_FRONTGATE_WATCHDOG_PENDING_PREFIX_YUE",
        "en": "INTERRUPT_FRONTGATE_WATCHDOG_PENDING_PREFIX_EN",
    }.get(language, "")
    raw = os.getenv(env_name, _DEFAULT_PENDING_PREFIXES.get(language, "")).strip()
    return tuple(item.strip() for item in raw.split("|") if item.strip())


def _robot_term_aliases(language: str) -> tuple[str, ...]:
    env_name = {
        "zh": "INTERRUPT_FRONTGATE_WATCHDOG_ROBOT_TERM_ZH",
        "zh-YUE": "INTERRUPT_FRONTGATE_WATCHDOG_ROBOT_TERM_YUE",
        "en": "INTERRUPT_FRONTGATE_WATCHDOG_ROBOT_TERM_EN",
    }.get(language, "")
    raw = os.getenv(env_name, _DEFAULT_ROBOT_TERMS.get(language, "")).strip()
    return tuple(item.strip() for item in raw.split("|") if item.strip())


def _candidate_pattern(candidate: str) -> re.Pattern[str]:
    segments = [segment for segment in re.split(r"[\s,，。！？!?、;；:：-]+", candidate.strip()) if segment]
    pattern_body = _candidate_pattern_body(segments)
    if not pattern_body:
        return re.compile(r"^\b\B$")
    return re.compile(rf"^\s*{pattern_body}{_SEPARATOR_RE}(?P<rest>.*)$", re.IGNORECASE)


def _exact_candidate_pattern(candidate: str) -> re.Pattern[str]:
    segments = [segment for segment in re.split(r"[\s,，。！？!?、;；:：-]+", candidate.strip()) if segment]
    pattern_body = _candidate_pattern_body(segments)
    if not pattern_body:
        return re.compile(r"^\b\B$")
    return re.compile(rf"^\s*{pattern_body}{_SEPARATOR_RE}$", re.IGNORECASE)


def _compact_watchdog_text(text: str) -> str:
    return re.sub(r"[\s,，。！？!?、;；:：-]+", "", (text or "").strip()).casefold()


def _looks_like_explicit_user_request(text: str, *, language: str) -> bool:
    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return False
    compact = _compact_watchdog_text(normalized)
    lowered = normalized.casefold()
    compact_lowered = compact.casefold()
    if language == "en":
        if any(token in lowered for token in ("?", "please", "can ", "could ", "would ", "will ", "how ", "what ", "where ", "when ", "why ")):
            return True
        return any(
            compact_lowered.startswith(prefix)
            for prefix in (
                "canyou",
                "couldyou",
                "wouldyou",
                "willyou",
                "doyou",
                "please",
                "helpme",
                "tellme",
                "showme",
                "takeme",
                "sayhello",
                "what",
                "how",
                "where",
                "when",
                "why",
            )
        )
    if any(token in normalized for token in ("？", "?")):
        return True
    if any(
        token in compact
        for token in (
            "可不可以",
            "可唔可以",
            "可以",
            "可否",
            "能不能",
            "请",
            "請",
            "帮我",
            "幫我",
            "带我",
            "帶我",
            "同我",
            "俾我",
            "比我",
            "告诉我",
            "告訴我",
            "话我知",
            "話我知",
            "讲下",
            "講下",
            "介绍",
            "介紹",
            "天气",
            "天氣",
            "几多度",
            "幾多度",
            "打个招呼",
            "打個招呼",
            "导航",
            "導航",
        )
    ):
        return True
    return any(
        compact.startswith(prefix)
        for prefix in (
            "今日天气",
            "今天天气",
            "今日天氣",
            "今天天氣",
            "天气点",
            "天气怎",
            "天氣點",
            "天氣點樣",
            "点样",
            "點樣",
            "点啊",
            "點啊",
            "点呀",
            "點呀",
            "咩",
            "什么",
            "點解",
            "点解",
            "边度",
            "邊度",
            "几时",
            "幾時",
            "带我去",
            "帶我去",
            "去电梯口",
            "去電梯口",
            "讲",
            "講",
            "说",
            "說",
            "查下",
            "睇下",
        )
    )


def _is_meaningful_pending_fragment(compact_text: str) -> bool:
    if not compact_text:
        return False
    if re.search(r"[A-Za-z]", compact_text):
        return len(compact_text) >= 3
    return len(compact_text) >= 2


def _candidate_pattern_body(segments: list[str]) -> str:
    if not segments:
        return ""
    if len(segments) == 1 and _contains_cjk(segments[0]):
        chars = [re.escape(char) for char in segments[0].strip() if char.strip()]
        return _SEPARATOR_RE.join(chars)
    escaped = [re.escape(segment) for segment in segments]
    return _SEPARATOR_RE.join(escaped)


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text or ""))
