from __future__ import annotations

from dataclasses import dataclass, field
import re
import time


def _normalize_text(text: str) -> str:
    cleaned = (text or "").strip().lower()
    cleaned = re.sub(r"[，。！？、,.!?：:\s]+", "", cleaned)
    return cleaned


def _strip_wakeword(raw_text: str, wakeword: str) -> str:
    text = (raw_text or "").strip()
    if not text:
        return ""

    normalized = _normalize_text(text)
    normalized_wake = _normalize_text(wakeword)
    if not normalized_wake or normalized_wake not in normalized:
        return text

    index = normalized.find(normalized_wake)
    # best effort: for Chinese wakewords, remove first literal occurrence from original text
    literal_index = text.lower().find(wakeword.lower())
    if literal_index >= 0:
        stripped = text[:literal_index] + text[literal_index + len(wakeword) :]
    else:
        stripped = text

    stripped = stripped.strip(" ，。！？、,.!?:：")
    return stripped.strip()


@dataclass(frozen=True)
class DialogueEvent:
    kind: str
    text: str = ""
    reply: str = ""
    wakeword: str = ""
    interrupt_suffix: str = ""


@dataclass
class DialogueConfig:
    wakewords: list[str]
    interrupt_suffixes: list[str]
    enter_dialogue_reply: str = "我在，请说"
    interruption_reply: str = "好的，那您还有其他需求吗？"
    session_timeout_s: float = 15.0


@dataclass
class DialogueSessionState:
    active: bool = False
    last_active_at: float = field(default_factory=time.monotonic)


class WakewordDialogueController:
    def __init__(self, config: DialogueConfig) -> None:
        self.config = config
        self.state = DialogueSessionState(active=False)

    def _match_wakeword(self, text: str) -> str:
        normalized = _normalize_text(text)
        for wakeword in self.config.wakewords:
            if _normalize_text(wakeword) and _normalize_text(wakeword) in normalized:
                return wakeword
        return ""

    def _match_interrupt_suffix(self, text: str) -> str:
        normalized = _normalize_text(text)
        for suffix in self.config.interrupt_suffixes:
            if _normalize_text(suffix) and _normalize_text(suffix) in normalized:
                return suffix
        return ""

    def _touch(self, now: float) -> None:
        self.state.active = True
        self.state.last_active_at = now

    def expire_if_needed(self, now: float | None = None) -> DialogueEvent | None:
        current = time.monotonic() if now is None else now
        if self.state.active and current - self.state.last_active_at > self.config.session_timeout_s:
            self.state.active = False
            return DialogueEvent(kind="session_timeout")
        return None

    def process_text(self, text: str, now: float | None = None) -> DialogueEvent:
        current = time.monotonic() if now is None else now
        expired = self.expire_if_needed(current)
        if expired is not None:
            # timeout event is informational; continue processing current text as fresh input
            pass

        raw = (text or "").strip()
        if not raw:
            return DialogueEvent(kind="ignore")

        wakeword = self._match_wakeword(raw)
        interrupt_suffix = self._match_interrupt_suffix(raw)

        if self.state.active:
            if wakeword and interrupt_suffix:
                self._touch(current)
                return DialogueEvent(
                    kind="interrupt",
                    reply=self.config.interruption_reply,
                    wakeword=wakeword,
                    interrupt_suffix=interrupt_suffix,
                )

            if wakeword:
                command = _strip_wakeword(raw, wakeword).strip()
                self._touch(current)
                if command:
                    return DialogueEvent(
                        kind="forward_command",
                        text=command,
                        wakeword=wakeword,
                    )
                return DialogueEvent(
                    kind="wake_ack",
                    reply=self.config.enter_dialogue_reply,
                    wakeword=wakeword,
                )

            self._touch(current)
            return DialogueEvent(kind="forward_followup", text=raw)

        if wakeword:
            command = _strip_wakeword(raw, wakeword).strip()
            self._touch(current)
            if command:
                return DialogueEvent(
                    kind="enter_and_forward",
                    text=command,
                    wakeword=wakeword,
                )
            return DialogueEvent(
                kind="wake_ack",
                reply=self.config.enter_dialogue_reply,
                wakeword=wakeword,
            )

        return DialogueEvent(kind="ignore")
