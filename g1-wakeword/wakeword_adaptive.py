#!/usr/bin/env python3
from __future__ import annotations

import argparse
import queue
import re
import threading
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

import numpy as np

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - optional for import-only bridge usage
    sd = None

try:
    from funasr import AutoModel
except Exception as exc:  # pragma: no cover - surfaced at runtime
    AutoModel = None
    _FUNASR_IMPORT_ERROR = exc
else:
    _FUNASR_IMPORT_ERROR = None


DEFAULT_MODEL_PATH = "/home/unitree/.cache/modelscope/hub/iic/SenseVoiceSmall"
DEFAULT_WAKEWORD_SIMILARITY_THRESHOLD = 0.62


def _clean_text(text: str) -> str:
    cleaned = re.sub(r"<\|[^|]+\|>", "", text or "")
    return " ".join(cleaned.split()).strip()


def _compact_text(text: str) -> str:
    return re.sub(r"[\s,，。.!！?？、…]+", "", (text or "").lower()).strip()


def _normalize_detected_text(text: str) -> str:
    cleaned = " ".join((text or "").split())
    replacements = {
        "笨笨你好": "你好笨笨",
        "笨笨，你好": "你好笨笨",
        "本本你好": "你好笨笨",
        "奔奔你好": "你好笨笨",
        "笨本同学": "笨笨同学",
        "本笨同学": "笨笨同学",
        "奔笨同学": "笨笨同学",
        "笨笨同學": "笨笨同学",
        "benben同学": "笨笨同学",
        "本本同学": "笨笨同学",
        "本本同學": "笨笨同学",
        "贝贝同学": "笨笨同学",
        "貝貝同學": "笨笨同学",
        "这对同学": "笨笨同学",
        "這對同學": "笨笨同学",
        "这都同学": "笨笨同学",
        "這都同學": "笨笨同学",
        "这的同学": "笨笨同学",
        "這的同學": "笨笨同学",
        "这得同学": "笨笨同学",
        "這得同學": "笨笨同学",
        "这顿同学": "笨笨同学",
        "這頓同學": "笨笨同学",
        "雷后笨笨": "雷猴笨笨",
        "雷猴本本": "雷猴笨笨",
        "hello ben ben": "hello benben",
    }
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
    return cleaned.strip()


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _compact_text(a), _compact_text(b)).ratio()


def list_audio_devices() -> None:
    if sd is None:
        print("sounddevice unavailable")
        return
    print("\n所有音频输入设备:")
    print("=" * 70)
    for index, device in enumerate(sd.query_devices()):
        if device["max_input_channels"] > 0:
            print(f"\n设备 {index}: {device['name']}")
            print(f"  输入通道: {device['max_input_channels']}")
            print(f"  采样率: {device['default_samplerate']} Hz")
    print("\n" + "=" * 70)


@dataclass
class WakeDetection:
    detected: bool
    keyword: str | None
    language: str | None
    similarity: float


class AdaptiveWakeWordSystem:
    TARGET_SAMPLE_RATE = 16000
    WAKE_WORDS = {
        "zh": ["你好笨笨", "笨笨", "笨笨同学"],
        "yue": ["雷猴笨笨", "多多同学", "多多"],
        "en": ["hello benben", "benben"],
    }
    SIMILARITY_THRESHOLD = DEFAULT_WAKEWORD_SIMILARITY_THRESHOLD

    def __init__(
        self,
        device_id: int | None = None,
        on_wakeword_callback: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self.device_id = device_id
        self.on_wakeword_callback = on_wakeword_callback
        self.audio_queue: queue.Queue[np.ndarray] = queue.Queue()
        self.running = False
        threshold_raw = os.environ.get(
            "OM1_WAKEWORD_SIMILARITY_THRESHOLD",
            str(DEFAULT_WAKEWORD_SIMILARITY_THRESHOLD),
        ).strip()
        try:
            self.SIMILARITY_THRESHOLD = float(threshold_raw)
        except ValueError:
            self.SIMILARITY_THRESHOLD = DEFAULT_WAKEWORD_SIMILARITY_THRESHOLD
        self.asr_model = self._load_asr_model()

    def _load_asr_model(self):
        if AutoModel is None:
            raise RuntimeError(f"FunASR import failed: {_FUNASR_IMPORT_ERROR}")

        configured_path = (Path(DEFAULT_MODEL_PATH),)
        for candidate in configured_path:
            if candidate.exists():
                return AutoModel(
                    model=str(candidate),
                    device="cpu",
                    disable_update=True,
                    disable_pbar=True,
                )

        return AutoModel(
            model="iic/SenseVoiceSmall",
            device="cpu",
            disable_update=True,
            disable_pbar=True,
        )

    def _check_wake_word(self, text: str) -> tuple[bool, str | None, str | None, float]:
        normalized = _normalize_detected_text(text)
        compact = _compact_text(normalized)
        if not compact:
            return False, None, None, 0.0

        best = WakeDetection(False, None, None, 0.0)
        for language, keywords in self.WAKE_WORDS.items():
            for keyword in keywords:
                keyword_compact = _compact_text(keyword)
                if keyword_compact and keyword_compact in compact:
                    return True, keyword, language, 1.0
                similarity = _similarity(normalized, keyword)
                if similarity > best.similarity:
                    best = WakeDetection(True, keyword, language, similarity)

        if best.detected and best.similarity >= self.SIMILARITY_THRESHOLD:
            return True, best.keyword, best.language, best.similarity
        return False, None, None, 0.0

    def _resample(self, audio: np.ndarray, orig_sr: int, target_sr: int = TARGET_SAMPLE_RATE) -> np.ndarray:
        if orig_sr == target_sr:
            return audio.astype(np.float32)
        duration = len(audio) / float(orig_sr)
        target_len = max(1, int(duration * target_sr))
        indices = np.linspace(0, len(audio) - 1, target_len)
        return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)

    def _process_audio(self, audio_data: np.ndarray) -> tuple[str, str, str, float] | None:
        volume = float(np.sqrt(np.mean(np.square(audio_data)))) if audio_data.size else 0.0
        if volume < 0.01:
            return None

        audio_float = audio_data.astype(np.float32)
        result = self.asr_model.generate(
            input=audio_float,
            batch_size=1,
            language="auto",
            use_itn=True,
            disable_pbar=True,
        )
        if not result:
            return None

        raw_text = result[0].get("text", "")
        clean_text = _normalize_detected_text(_clean_text(raw_text))
        if not clean_text:
            return None

        detected, keyword, language, similarity = self._check_wake_word(clean_text)
        if not detected or not keyword or not language:
            return None
        return clean_text, keyword, language, similarity

    def _audio_worker(self) -> None:
        while self.running:
            try:
                audio_data = self.audio_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                outcome = self._process_audio(audio_data)
                if outcome is None:
                    continue
                text, keyword, language, similarity = outcome
                print(f"[识别] {text}")
                print(
                    f"[唤醒] language={language} keyword={keyword} similarity={similarity:.2f}",
                    flush=True,
                )
                if self.on_wakeword_callback is not None:
                    self.on_wakeword_callback(language, keyword, text)
            except Exception as exc:
                print(f"处理错误: {exc}", flush=True)

    def start_listening(self) -> None:
        if sd is None:
            raise RuntimeError("sounddevice is required for standalone microphone listening")
        if self.device_id is None:
            raise ValueError("device_id is required for standalone microphone listening")

        device_info = sd.query_devices(self.device_id)
        channels = max(1, int(device_info["max_input_channels"]))
        samplerate = int(device_info["default_samplerate"])

        print("=" * 70)
        print("三语言唤醒词系统 (FunASR + SenseVoice)")
        print("=" * 70)
        for language, keywords in self.WAKE_WORDS.items():
            print(f"{language}: {', '.join(keywords)}")
        print("=" * 70)
        print(f"设备: {device_info['name']}")
        print(f"通道: {channels} | 采样率: {samplerate}Hz")
        print("\n🎤 监听中...\n")

        self.running = True
        worker = threading.Thread(target=self._audio_worker, daemon=True)
        worker.start()

        def callback(indata, frames, time_info, status) -> None:
            if status:
                print(f"⚠️ 音频状态: {status}", flush=True)
            if channels > 1:
                audio = np.mean(indata, axis=1, dtype=np.float32)
            else:
                audio = indata[:, 0].astype(np.float32)
            if samplerate != self.TARGET_SAMPLE_RATE:
                audio = self._resample(audio, samplerate, self.TARGET_SAMPLE_RATE)
            self.audio_queue.put(audio.copy())

        try:
            with sd.InputStream(
                samplerate=samplerate,
                channels=channels,
                callback=callback,
                blocksize=int(samplerate * 2),
                device=self.device_id,
                dtype="float32",
            ):
                while self.running:
                    time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n停止监听", flush=True)
        finally:
            self.running = False


def _main() -> int:
    parser = argparse.ArgumentParser(description="Tri-language wakeword runtime for G1 frontgate.")
    parser.add_argument("--device", type=int, help="Audio input device id for standalone test mode.")
    parser.add_argument("--list", action="store_true", help="List audio input devices.")
    args = parser.parse_args()

    if args.list:
        list_audio_devices()
        return 0
    if args.device is None:
        parser.print_help()
        return 0

    system = AdaptiveWakeWordSystem(device_id=args.device)
    system.start_listening()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
