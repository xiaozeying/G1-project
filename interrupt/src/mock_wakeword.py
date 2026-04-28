from __future__ import annotations

from dataclasses import dataclass

from src.settings import AppSettings
from src.wakeword_runtime import WakeWordEvent


def _normalize_text(text: str) -> str:
    return "".join((text or "").strip().lower().split())


@dataclass
class StdinWakeWordGate:
    wakewords: tuple[str, ...]
    prompt: str = "wakeword> "

    def wait_for_wake(self) -> WakeWordEvent | None:
        while True:
            try:
                raw = input(self.prompt)
            except EOFError:
                return None
            text = (raw or "").strip()
            if not text:
                continue
            normalized = _normalize_text(text)
            for wakeword in self.wakewords:
                if _normalize_text(wakeword) in normalized:
                    return WakeWordEvent(wakeword=wakeword, text=text)
            print(f"[FrontGate] ignore non-wake input: {text}", flush=True)

    def close(self) -> None:
        return None


def factory(
    *,
    settings: AppSettings,
    wakewords: list[str] | tuple[str, ...] | None = None,
    prompt: str = "wakeword> ",
) -> StdinWakeWordGate:
    configured = tuple(wakewords or ("笨笨同学", "你好笨笨", "hello benben"))
    return StdinWakeWordGate(wakewords=configured, prompt=prompt)
