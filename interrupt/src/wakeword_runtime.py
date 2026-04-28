from __future__ import annotations

import importlib
import time
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Callable, Protocol

from src.settings import AppSettings


@dataclass
class WakeWordEvent:
    wakeword: str
    text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    detected_at: float = field(default_factory=time.monotonic)


class WakeWordGate(Protocol):
    def wait_for_wake(self) -> WakeWordEvent | None:
        ...

    def close(self) -> None:
        ...


WakeWordFactory = Callable[..., WakeWordGate]


def _split_factory_spec(factory_spec: str) -> tuple[str, str]:
    module_name, sep, attr_name = (factory_spec or "").strip().partition(":")
    if not sep or not module_name or not attr_name:
        raise ValueError(
            "wake word factory must use 'module.submodule:factory_name' format"
        )
    return module_name, attr_name


def load_factory_from_spec(factory_spec: str) -> WakeWordFactory:
    module_name, attr_name = _split_factory_spec(factory_spec)
    module = importlib.import_module(module_name)
    factory = getattr(module, attr_name, None)
    if factory is None or not callable(factory):
        raise RuntimeError(f"Wake word factory not found or not callable: {factory_spec}")
    return factory


def create_wake_word_gate(
    factory_spec: str,
    *,
    settings: AppSettings,
    **kwargs: Any,
) -> WakeWordGate:
    factory = load_factory_from_spec(factory_spec)
    gate = factory(settings=settings, **kwargs)
    if gate is None:
        raise RuntimeError(f"Wake word factory returned None: {factory_spec}")
    if not hasattr(gate, "wait_for_wake"):
        raise TypeError(
            f"Wake word gate from {factory_spec} does not implement wait_for_wake()"
        )
    return gate


def load_module(factory_spec: str) -> ModuleType:
    module_name, _ = _split_factory_spec(factory_spec)
    return importlib.import_module(module_name)
