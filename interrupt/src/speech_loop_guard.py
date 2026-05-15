from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path


DEFAULT_GUARD_STATE_PATH = "/tmp/interrupt_speech_loop_guard.json"
_CJK_CHAR_RE = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_CJK_LATIN_DIGIT_RE = re.compile(rf"(?<=[{_CJK_CHAR_RE}A-Za-z0-9])\s+(?=[{_CJK_CHAR_RE}A-Za-z0-9])")
_PUNCT_SPACING_RE = re.compile(r"\s+([，。！？；：,.!?;:])")
_NON_WORD_RE = re.compile(r"[^\w\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")


def guard_state_path() -> Path:
    return Path(
        os.getenv("INTERRUPT_SPEECH_LOOP_GUARD_FILE", DEFAULT_GUARD_STATE_PATH).strip()
        or DEFAULT_GUARD_STATE_PATH
    )


def _normalize_text(text: str) -> str:
    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return ""
    normalized = _CJK_LATIN_DIGIT_RE.sub("", normalized)
    normalized = _PUNCT_SPACING_RE.sub(r"\1", normalized)
    return normalized.strip()


def _fold_text(text: str) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return ""
    return _NON_WORD_RE.sub("", normalized).lower()


def _default_guard_duration_s(text: str) -> float:
    length = len(_fold_text(text))
    return min(6.0, max(2.5, 1.8 + 0.12 * length))


def note_local_playback(text: str, *, language: str = "", duration_s: float | None = None) -> None:
    normalized = _normalize_text(text)
    folded = _fold_text(normalized)
    if not normalized or not folded:
        return
    guard_s = duration_s if duration_s is not None else _default_guard_duration_s(normalized)
    payload = {
        "text": normalized,
        "folded": folded,
        "language": language,
        "guard_until": time.time() + max(0.0, guard_s),
        "updated_at": time.time(),
    }
    guard_state_path().write_text(json.dumps(payload), encoding="utf-8")


def _load_state() -> dict[str, object] | None:
    try:
        raw = guard_state_path().read_text(encoding="utf-8")
        payload = json.loads(raw)
    except Exception:
        return None
    if float(payload.get("guard_until", 0.0) or 0.0) <= time.time():
        return None
    return payload


def local_playback_guard_active() -> bool:
    return _load_state() is not None


def should_ignore_transcript(text: str) -> bool:
    folded = _fold_text(text)
    if not folded:
        return False
    payload = _load_state()
    if not payload:
        return False
    guarded = str(payload.get("folded", "") or "")
    if not guarded:
        return False
    if folded == guarded:
        return True
    if len(folded) >= 4 and (folded in guarded or guarded in folded):
        return True
    return False
