from __future__ import annotations

import logging
import threading
from typing import Callable

from src.g1_om1_adapter import G1Om1Adapter
from src.settings import FeedbackConfig


LOGGER = logging.getLogger("interrupt.speech_feedback")

MODE_OM1_MIRROR = "om1_mirror"
MODE_TRANSPORT_ONLY = "transport_only"
MODE_DISABLED = "disabled"


class SpeechFeedbackRouter:
    def __init__(self, config: FeedbackConfig, adapter: G1Om1Adapter) -> None:
        self._config = config
        self._adapter = adapter

    def speak_assistant_reply(
        self,
        text: str,
        *,
        normalize_tts_text: Callable[[str], str],
    ) -> bool:
        return self._speak_with_mode(
            text,
            mode=self._config.assistant_audio_mode,
            normalize_tts_text=normalize_tts_text,
            success_log="OM1 本地播报 assistant 回复成功",
            failure_log="OM1 本地播报 assistant 回复失败",
            skip_log_prefix="跳过 assistant 本地播报",
        )

    def speak_assistant_reply_async(
        self,
        text: str,
        *,
        normalize_tts_text: Callable[[str], str],
    ) -> None:
        normalized = normalize_tts_text(text)
        if not normalized:
            return
        threading.Thread(
            target=self.speak_assistant_reply,
            args=(normalized,),
            kwargs={"normalize_tts_text": normalize_tts_text},
            name="interrupt-om1-tts-mirror",
            daemon=True,
        ).start()

    def speak_local_tool_ack(
        self,
        text: str,
        *,
        normalize_tts_text: Callable[[str], str],
    ) -> bool:
        return self._speak_with_mode(
            text,
            mode=self._config.local_tool_ack_audio_mode,
            normalize_tts_text=normalize_tts_text,
            success_log="本地工具前置播报成功",
            failure_log="本地工具前置播报失败",
            skip_log_prefix="跳过本地工具前置播报",
        )

    def _speak_with_mode(
        self,
        text: str,
        *,
        mode: str,
        normalize_tts_text: Callable[[str], str],
        success_log: str,
        failure_log: str,
        skip_log_prefix: str,
    ) -> bool:
        if mode == MODE_DISABLED:
            LOGGER.info("%s: mode=disabled", skip_log_prefix)
            return False
        if mode == MODE_TRANSPORT_ONLY:
            LOGGER.info("%s: mode=transport_only", skip_log_prefix)
            return False
        if mode != MODE_OM1_MIRROR:
            LOGGER.warning("%s: unknown mode=%s", skip_log_prefix, mode)
            return False
        if not self._adapter.available:
            LOGGER.info("%s: adapter unavailable", skip_log_prefix)
            return False
        normalized = normalize_tts_text(text)
        if not normalized:
            return False
        result = self._adapter.speak(normalized)
        if result.ok:
            LOGGER.info("%s: text=%r", success_log, normalized)
            return True
        LOGGER.warning(
            "%s: rc=%s stdout=%r stderr=%r text=%r",
            failure_log,
            result.returncode,
            result.stdout,
            result.stderr,
            normalized,
        )
        return False
