from __future__ import annotations

import json
import os
import time
from pathlib import Path


DEFAULT_MUTE_STATE_PATH = "/tmp/interrupt_cantonese_tts_mute.json"


def mute_state_path() -> Path:
    return Path(
        os.getenv("INTERRUPT_CANTONESE_TTS_MUTE_STATE_FILE", DEFAULT_MUTE_STATE_PATH).strip()
        or DEFAULT_MUTE_STATE_PATH
    )


def set_mute_remote_audio(duration_s: float, *, language: str) -> None:
    expires_at = max(time.time(), time.time() + max(0.0, duration_s))
    payload = {
        "mute_remote_until": expires_at,
        "language": language,
        "updated_at": time.time(),
    }
    mute_state_path().write_text(json.dumps(payload), encoding="utf-8")


def should_mute_remote_audio(*, identity: str = "") -> bool:
    try:
        raw = mute_state_path().read_text(encoding="utf-8")
        payload = json.loads(raw)
    except Exception:
        return False
    expires_at = float(payload.get("mute_remote_until", 0.0) or 0.0)
    language = str(payload.get("language", "") or "")
    if expires_at <= time.time():
        return False
    if identity and not identity.startswith("agent-") and identity != "interrupt-web-agent":
        return False
    return language == "zh-YUE"
