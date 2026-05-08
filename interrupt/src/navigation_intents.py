from __future__ import annotations

import re


_SPACE_RE = re.compile(r"\s+")
_TRAILING_PUNCT_RE = re.compile(r"^[\s，。！？；：,.!?;:、]+|[\s，。！？；：,.!?;:、]+$")


_RELATIVE_MOTION_KEYWORDS = (
    "往前",
    "向前",
    "前进",
    "前進",
    "往后",
    "往後",
    "向后",
    "向後",
    "后退",
    "後退",
    "左转",
    "左轉",
    "右转",
    "右轉",
    "转个圈",
    "轉個圈",
    "转圈",
    "轉圈",
    "原地转",
    "原地轉",
    "转一下",
    "轉一下",
    "turn around",
    "rotate",
    "spin",
    "move forward",
    "move backward",
    "step forward",
    "step back",
)

_NAV_PREFIXES = (
    "带我去",
    "帶我去",
    "带我到",
    "帶我到",
    "导航去",
    "導航去",
    "导航到",
    "導航到",
    "去到",
    "去",
    "go to",
    "navigate to",
    "take me to",
    "bring me to",
    "lead me to",
)

_LEADING_FILLERS = (
    "请",
    "請",
    "帮我",
    "幫我",
    "麻烦",
    "麻煩",
    "可以",
    "可否",
    "可唔可以",
    "please",
)

_TRAILING_FILLERS = (
    "吧",
    "呀",
    "啊",
    "啦",
    "喇",
    "一下",
    "一吓",
    "先",
    "好吗",
    "好嗎",
    "please",
)

_REMEMBER_PREFIXES = (
    "记住这里是",
    "記住呢度係",
    "記住这里是",
    "记住这里是",
    "记住这里叫",
    "記住呢度叫",
    "把这里记为",
    "把呢度记为",
    "把这里保存为",
    "保存这里为",
    "save this location as",
    "remember this location as",
    "remember this place as",
    "save this place as",
)

_LIST_LOCATIONS_PATTERNS = (
    "哪些地方可以去",
    "哪些位置可以去",
    "有哪些地方可以去",
    "有哪些位置可以去",
    "可以去哪里",
    "可以去邊度",
    "可以去边度",
    "有什么地点",
    "有咩地点",
    "有咩地點",
    "saved locations",
    "which locations",
    "where can you go",
    "what places can you go to",
)


def _normalize(text: str) -> str:
    normalized = _SPACE_RE.sub(" ", (text or "").strip())
    return _TRAILING_PUNCT_RE.sub("", normalized).strip()


def looks_like_relative_motion_command(text: str) -> bool:
    normalized = _normalize(text).lower()
    if not normalized:
        return False
    return any(keyword in normalized for keyword in _RELATIVE_MOTION_KEYWORDS)


def _strip_leading_fillers(text: str) -> str:
    updated = text
    changed = True
    while changed:
        changed = False
        lowered = updated.lower()
        for token in _LEADING_FILLERS:
            token_lower = token.lower()
            if lowered.startswith(token_lower):
                updated = updated[len(token) :].strip()
                changed = True
                break
    return updated


def _strip_trailing_fillers(text: str) -> str:
    updated = text
    changed = True
    while changed:
        changed = False
        lowered = updated.lower()
        for token in _TRAILING_FILLERS:
            token_lower = token.lower()
            if lowered.endswith(token_lower):
                updated = updated[: -len(token)].strip()
                changed = True
                break
    return updated.strip(" ，。！？；：,.!?;:、")


def extract_navigation_destination(text: str) -> str | None:
    normalized = _strip_leading_fillers(_normalize(text))
    if not normalized or looks_like_relative_motion_command(normalized):
        return None
    lowered = normalized.lower()
    for prefix in _NAV_PREFIXES:
        prefix_lower = prefix.lower()
        if lowered.startswith(prefix_lower):
            destination = normalized[len(prefix) :].strip()
            destination = _strip_trailing_fillers(destination)
            if destination:
                return destination
    return None


def looks_like_navigation_command(text: str) -> bool:
    return extract_navigation_destination(text) is not None


def extract_remember_location_name(text: str) -> str | None:
    normalized = _strip_leading_fillers(_normalize(text))
    if not normalized:
        return None
    lowered = normalized.lower()
    for prefix in _REMEMBER_PREFIXES:
        prefix_lower = prefix.lower()
        if lowered.startswith(prefix_lower):
            name = normalized[len(prefix) :].strip()
            name = _strip_trailing_fillers(name)
            if name:
                return name
    return None


def looks_like_remember_location_command(text: str) -> bool:
    return extract_remember_location_name(text) is not None


def looks_like_saved_locations_query(text: str) -> bool:
    normalized = _normalize(text).lower()
    if not normalized:
        return False
    return any(pattern in normalized for pattern in _LIST_LOCATIONS_PATTERNS)
