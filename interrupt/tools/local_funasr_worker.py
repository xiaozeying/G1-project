#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import wave
from pathlib import Path

import numpy as np

try:
    from funasr import AutoModel
except Exception as exc:  # pragma: no cover - runtime dependency on robot
    AutoModel = None
    _FUNASR_IMPORT_ERROR = exc
else:
    _FUNASR_IMPORT_ERROR = None

try:
    import torch
except Exception:
    torch = None


DEFAULT_MODEL_PATH = "/home/unitree/.cache/modelscope/hub/iic/SenseVoiceSmall"
_LANG_TAG_RE = re.compile(r"<\|(zh|yue|en|ja|ko)\|>")
_META_TAG_RE = re.compile(r"<\|[^|]+\|>")
_CJK_CHAR_RE = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_DIGIT_RE = re.compile(r"\d{2,}")
_CJK_RE = re.compile(rf"[{_CJK_CHAR_RE}]")
_CORE_RE = re.compile(rf"[A-Za-z0-9{_CJK_CHAR_RE}]")
_NON_CORE_RE = re.compile(rf"[^A-Za-z0-9{_CJK_CHAR_RE}]+")


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_device() -> str:
    configured = os.getenv("INTERRUPT_RTC_TRANSCRIBE_DEVICE", "auto").strip().lower() or "auto"
    if configured in {"auto", "gpu"}:
        if torch is not None:
            try:
                if bool(torch.cuda.is_available()):
                    index = int(os.getenv("INTERRUPT_RTC_TRANSCRIBE_CUDA_INDEX", "0").strip() or "0")
                    return f"cuda:{index}"
            except Exception:
                pass
        return "cpu"
    if configured == "cuda":
        index = int(os.getenv("INTERRUPT_RTC_TRANSCRIBE_CUDA_INDEX", "0").strip() or "0")
        return f"cuda:{index}"
    return configured


def _build_model(model_ref: str, *, device: str):
    return AutoModel(
        model=model_ref,
        device=device,
        disable_update=True,
        disable_pbar=True,
    )


def _load_model():
    if AutoModel is None:
        raise RuntimeError(f"FunASR import failed: {_FUNASR_IMPORT_ERROR}")

    configured = Path(
        os.getenv("INTERRUPT_RTC_TRANSCRIBE_MODEL_PATH", DEFAULT_MODEL_PATH).strip() or DEFAULT_MODEL_PATH
    )
    model_ref = str(configured) if configured.exists() else "iic/SenseVoiceSmall"
    preferred_device = _resolve_device()
    try:
        return _build_model(model_ref, device=preferred_device), preferred_device
    except Exception as exc:
        if preferred_device != "cpu" and _env_flag("INTERRUPT_RTC_TRANSCRIBE_ALLOW_CPU_FALLBACK", True):
            try:
                return _build_model(model_ref, device="cpu"), "cpu"
            except Exception as fallback_exc:
                raise RuntimeError(
                    f"FunASR load failed on {preferred_device}: {exc}; cpu fallback failed: {fallback_exc}"
                ) from fallback_exc
        raise RuntimeError(f"FunASR load failed on {preferred_device}: {exc}") from exc


def _read_wav(path: str) -> np.ndarray:
    with wave.open(path, "rb") as handle:
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        frames = handle.getnframes()
        raw = handle.readframes(frames)
    if sample_width != 2:
        raise RuntimeError(f"unsupported sample width: {sample_width}")
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio / 32768.0


def _clean_result_text(text: str) -> tuple[str, str]:
    tagged = text or ""
    lang_match = _LANG_TAG_RE.search(tagged)
    language = lang_match.group(1) if lang_match else ""
    cleaned = _META_TAG_RE.sub("", tagged)
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned, language


def _is_low_value_text(text: str) -> bool:
    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return True
    if _WORD_RE.search(normalized):
        return False
    if _DIGIT_RE.search(normalized):
        return False
    if _CJK_RE.search(normalized):
        core = _NON_CORE_RE.sub("", normalized)
        return len(core) <= 1
    compact = re.sub(r"\s+", "", normalized)
    if not compact:
        return True
    if not _CORE_RE.search(compact):
        return True
    return len(compact) <= 1


def main() -> int:
    try:
        model, device = _load_model()
    except Exception as exc:
        print(json.dumps({"type": "fatal", "error": str(exc)}), flush=True)
        return 1

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            request_id = str(payload.get("id", "") or "")
            wav_path = str(payload.get("wav_path", "") or "")
            language = str(payload.get("language", "auto") or "auto")
            if not request_id or not wav_path:
                raise RuntimeError("missing id or wav_path")
            audio = _read_wav(wav_path)
            result = model.generate(
                input=audio,
                cache={},
                language=language,
                use_itn=True,
                disable_pbar=True,
            )
            tagged_text = ""
            if result:
                tagged_text = str(result[0].get("text", "") or "")
            clean_text, detected_language = _clean_result_text(tagged_text)
            if _is_low_value_text(clean_text):
                clean_text = ""
            response = {
                "id": request_id,
                "text": clean_text,
                "language": detected_language,
                "error": "",
                "device": device,
            }
        except Exception as exc:
            response = {
                "id": locals().get("request_id", ""),
                "text": "",
                "language": "",
                "error": str(exc),
                "device": locals().get("device", ""),
            }
        print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
