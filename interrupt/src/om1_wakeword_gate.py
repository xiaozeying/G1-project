from __future__ import annotations

import importlib.util
import os
import queue
import re
import select
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from src.settings import AppSettings
from src.wakeword_runtime import WakeWordEvent, WakeWordGate


DEFAULT_WAKEWORD_SCRIPT = "/home/unitree/g1-wakeword/wakeword_adaptive.py"
DEFAULT_CAPTURE_HINTS = (
    "8888:1719",
    "MV-SILICON",
    "mvsilicon B1 usb audio",
    "B1 usb audio",
    "B1",
    "BY Y02",
    "Y02",
    "USB Audio",
    "usb audio",
)
DEFAULT_EXTRA_WAKEWORDS = (
    "笨笨",
    "笨笨同学",
)
DEFAULT_WAKEWORD_SIMILARITY_THRESHOLD = 0.62
_ALSA_HW_RE = re.compile(
    r"card\s+\d+:\s+(?P<card_id>[^ ]+)\s+\[(?P<card_name>[^\]]+)\],\s+"
    r"device\s+(?P<device_num>\d+):\s+(?P<device_name>.+)"
)


def _dedupe_keep_order(items: Iterable[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _effective_capture_hints(explicit_hints: Sequence[str] | None = None) -> list[str]:
    env_hints = re.split(r"[,\n]+", os.environ.get("OM1_CAPTURE_HINTS", ""))
    merged = list(explicit_hints or []) + env_hints
    hints = _dedupe_keep_order(merged)
    return hints or list(DEFAULT_CAPTURE_HINTS)


def _pick_linux_capture_device(
    requested_device: str,
    explicit_hints: Sequence[str] | None = None,
) -> tuple[str, list[str], list[str]]:
    requested = (requested_device or "").strip()
    if requested.casefold() == "pulse":
        return requested, [], _effective_capture_hints(explicit_hints)
    if requested and requested.casefold() not in {"default", "pulse"}:
        return requested_device, [], _effective_capture_hints(explicit_hints)

    for env_name in ("OM1_CAPTURE_DEVICE", "AUDIO_CAPTURE_DEVICE"):
        env_device = os.environ.get(env_name, "").strip()
        if env_device.casefold() == "pulse":
            return env_device, [], _effective_capture_hints(explicit_hints)
        if env_device and env_device.casefold() not in {"default", "pulse"}:
            return env_device, [], _effective_capture_hints(explicit_hints)

    hints = _effective_capture_hints(explicit_hints)
    if os.name != "posix" or shutil.which("arecord") is None:
        return requested_device, [], hints

    try:
        result = subprocess.run(
            ["arecord", "-l"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return requested_device, [], hints

    preferred: list[tuple[str, str]] = []
    fallback: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        match = _ALSA_HW_RE.search(line)
        if not match:
            continue
        card_id = match.group("card_id")
        device_num = match.group("device_num")
        card_name = match.group("card_name").strip()
        device_name = match.group("device_name").strip()
        capture_device = f"plughw:CARD={card_id},DEV={device_num}"
        summary = f"{capture_device} [{card_name} / {device_name}]"
        haystack = " ".join((card_id, card_name, device_name)).casefold()
        if any(hint.casefold() in haystack for hint in hints):
            preferred.append((capture_device, summary))
        else:
            fallback.append((capture_device, summary))
    candidates = preferred + fallback
    if not candidates:
        return requested_device, [], hints
    return candidates[0][0], [item[1] for item in candidates], hints


def _apply_software_gain(audio_chunk: np.ndarray, gain: float) -> np.ndarray:
    if gain == 1.0 or audio_chunk.size == 0:
        return audio_chunk
    amplified = audio_chunk.astype(np.float32) * gain
    return np.clip(amplified, -32768, 32767).astype(np.int16)


def _audio_levels(audio_chunk: np.ndarray) -> tuple[int, int]:
    if audio_chunk.size == 0:
        return 0, 0
    pcm = audio_chunk.astype(np.float32)
    rms = int(np.sqrt(np.mean(np.square(pcm))))
    peak = int(np.max(np.abs(pcm)))
    return rms, peak


def _normalize_followup_text(text: str) -> str:
    cleaned = " ".join((text or "").split())
    replacements = {
        "L灯": "LED灯",
        "l灯": "LED灯",
        "诶第灯": "LED灯",
        "爱低灯": "LED灯",
        "笨本同学": "笨笨同学",
        "本笨同学": "笨笨同学",
        "奔笨同学": "笨笨同学",
        "笨笨同學": "笨笨同学",
        "benben同学": "笨笨同学",
    }
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
    return cleaned.strip()


def _normalize_wake_text(text: str) -> str:
    cleaned = " ".join((text or "").split())
    replacements = {
        "笨笨你好": "你好笨笨",
        "笨笨，你好": "你好笨笨",
        "本本你好": "你好笨笨",
        "奔奔你好": "你好笨笨",
        "本本": "笨笨",
        "对本": "笨笨",
        "對本": "笨笨",
        "奔奔": "笨笨",
        "本笨": "笨笨",
        "贝贝同学": "笨笨同学",
        "貝貝同學": "笨笨同学",
        "根本同学": "笨笨同学",
        "根本同學": "笨笨同学",
        "本同学": "笨笨同学",
        "本同學": "笨笨同学",
        "本本同学": "笨笨同学",
        "本本同學": "笨笨同学",
        "笨本同学": "笨笨同学",
        "本笨同学": "笨笨同学",
        "奔笨同学": "笨笨同学",
        "笨笨同學": "笨笨同学",
        "benben同学": "笨笨同学",
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
    }
    for source, target in replacements.items():
        cleaned = cleaned.replace(source, target)
    return cleaned.strip()


def _strip_wakeword(text: str, keyword: str) -> str:
    cleaned = (text or "").strip()
    keyword = (keyword or "").strip()
    if not cleaned or not keyword:
        return cleaned
    significant_chars = [
        re.escape(char)
        for char in keyword
        if not re.fullmatch(r"[\s,，。.!！?？]*", char)
    ]
    if not significant_chars:
        return cleaned
    pattern = re.compile(r"[\s,，。.!！?？]*".join(significant_chars), re.IGNORECASE)
    match = pattern.search(cleaned)
    if not match:
        return cleaned
    stripped = (cleaned[: match.start()] + cleaned[match.end() :]).strip(" ,，。.!！?？")
    return " ".join(stripped.split())


def _compact_wake_text(text: str) -> str:
    cleaned = _normalize_wake_text(text)
    cleaned = re.sub(r"[，。,.!！?？、…\s]+", "", cleaned)
    cleaned = cleaned.replace("ん", "")
    return cleaned.strip()


def _load_wakeword_module(script_path: str):
    path = Path(script_path)
    if not path.exists():
        raise FileNotFoundError(f"Wakeword script not found: {path}")
    spec = importlib.util.spec_from_file_location("wakeword_adaptive_module", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load wakeword module from: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class Om1WakeWordGate(WakeWordGate):
    system: object
    capture_device: str
    capture_hints: tuple[str, ...]
    chunk_duration: float
    software_gain: float
    level_interval: float
    idle_min_rms: int
    idle_min_peak: int
    idle_speech_ratio: float
    idle_release_chunks: int
    merge_history_chunks: int
    debug_recognition: bool
    _closed: bool = False

    def __post_init__(self) -> None:
        self._last_level_log_at = 0.0
        self._noise_floor_rms: float | None = None
        self._release_remaining = 0
        self._missing_asr_logged = False
        self._recent_texts: list[str] = []
        self._consecutive_capture_errors = 0

    def _refresh_capture_device(self) -> bool:
        selected_device, candidates, _hints = _pick_linux_capture_device(
            "default",
            self.capture_hints,
        )
        refreshed = (selected_device or "").strip()
        current = (self.capture_device or "").strip()
        if not refreshed or refreshed == current:
            return False
        self.capture_device = refreshed
        print(
            f"[FrontGate] wake capture device refreshed: old={current} new={refreshed}",
            flush=True,
        )
        if candidates:
            print("[FrontGate] refreshed capture_candidates:", flush=True)
            for candidate in candidates[:8]:
                print(f"  - {candidate}", flush=True)
        return True

    def wait_for_wake(self) -> WakeWordEvent | None:
        if self._closed:
            return None
        if os.name != "posix" or shutil.which("arecord") is None:
            raise RuntimeError("Om1WakeWordGate currently requires arecord on Linux")

        chunk_samples = int(self.system.TARGET_SAMPLE_RATE * self.chunk_duration)
        frame_bytes = chunk_samples * 2
        read_timeout_s = float(
            os.environ.get("OM1_WAKEWORD_READ_TIMEOUT_S", "12.0").strip() or "12.0"
        )
        reopen_delay_s = float(
            os.environ.get("OM1_WAKEWORD_REOPEN_DELAY_S", "0.20").strip() or "0.20"
        )
        max_consecutive_errors = int(
            os.environ.get("OM1_WAKEWORD_MAX_CONSECUTIVE_ERRORS", "20").strip() or "20"
        )

        while not self._closed:
            proc = None
            try:
                proc = subprocess.Popen(
                    [
                        "arecord",
                        "-q",
                        "-D",
                        self.capture_device,
                        "-f",
                        "S16_LE",
                        "-r",
                        str(self.system.TARGET_SAMPLE_RATE),
                        "-c",
                        "1",
                        "-t",
                        "raw",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
                assert proc.stdout is not None
                stdout_fd = proc.stdout.fileno()
                buffered = bytearray()
                self._consecutive_capture_errors = 0
                while not self._closed:
                    ready, _, _ = select.select([stdout_fd], [], [], max(0.5, read_timeout_s))
                    if not ready:
                        raise RuntimeError(f"arecord stalled for {read_timeout_s:.1f}s")
                    chunk = os.read(stdout_fd, min(16384, max(4096, frame_bytes - len(buffered))))
                    if not chunk:
                        err = ""
                        if proc.stderr is not None:
                            try:
                                err = proc.stderr.read().decode("utf-8", errors="ignore").strip()
                            except Exception:
                                err = ""
                        raise RuntimeError(err or "arecord stopped producing audio")
                    buffered.extend(chunk)
                    while len(buffered) >= frame_bytes:
                        frame = bytes(buffered[:frame_bytes])
                        del buffered[:frame_bytes]
                        audio_chunk = np.frombuffer(frame, dtype=np.int16).copy()
                        audio_chunk = _apply_software_gain(audio_chunk, self.software_gain)
                        now = time.monotonic()
                        rms, peak = _audio_levels(audio_chunk)
                        if (
                            self.level_interval > 0
                            and now - self._last_level_log_at >= self.level_interval
                        ):
                            print(f"[FrontGate] audio_level rms={rms} peak={peak}", flush=True)
                            self._last_level_log_at = now
                        if not self._should_process(rms, peak):
                            continue
                        event = self._process_chunk(audio_chunk)
                        if event is not None:
                            return event
            except RuntimeError as exc:
                self._consecutive_capture_errors += 1
                print(
                    "[FrontGate] wake capture auto-recover "
                    f"attempt={self._consecutive_capture_errors} error={exc}",
                    flush=True,
                )
                error_text = str(exc).lower()
                if (
                    "cannot get card index" in error_text
                    or "no such device" in error_text
                    or "audio open error" in error_text
                ):
                    self._refresh_capture_device()
                if self._consecutive_capture_errors >= max_consecutive_errors:
                    raise RuntimeError(
                        f"wake capture failed {self._consecutive_capture_errors} times: {exc}"
                    ) from exc
                time.sleep(max(0.05, reopen_delay_s))
                continue
            finally:
                if proc is not None and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=1)
                    except Exception:
                        proc.kill()
        return None

    def close(self) -> None:
        self._closed = True

    def _process_chunk(self, audio_data: np.ndarray) -> WakeWordEvent | None:
        if audio_data.dtype == np.int16:
            audio_float = audio_data.astype(np.float32) / 32768.0
        else:
            audio_float = audio_data.astype(np.float32)

        asr_model = getattr(self.system, "asr_model", None)
        if asr_model is None:
            if not self._missing_asr_logged:
                print(
                    "[FrontGate] wakeword ASR unavailable; recreating gate and retrying",
                    flush=True,
                )
                self._missing_asr_logged = True
            raise RuntimeError("wakeword ASR model unavailable")

        result = asr_model.generate(
            input=audio_float,
            cache={},
            language="auto",
            use_itn=True,
            disable_pbar=True,
        )
        if not result:
            return None
        text = result[0].get("text", "")
        lang_match = re.search(r"<\|(zh|yue|en|ja|ko)\|>", text)
        detected_lang = lang_match.group(1) if lang_match else "unknown"
        clean_text = re.sub(r"<\|[^|]+\|>", "", text).strip()
        if not clean_text:
            return None

        clean_text = _normalize_wake_text(clean_text)
        compact_text = _compact_wake_text(clean_text)

        if self.debug_recognition:
            print(f"[{detected_lang}] {clean_text}", flush=True)
        self._remember_recent_text(clean_text)
        candidates = self._detection_candidates(clean_text, compact_text)
        for label, candidate_text in candidates:
            detected, keyword, wake_lang, similarity = self.system._check_wake_word(candidate_text)
            if not detected:
                continue
            seed_text = _normalize_followup_text(_strip_wakeword(candidate_text, keyword))
            print(
                f"[FrontGate] wake_detected language={wake_lang} keyword={keyword} "
                f"similarity={similarity:.2f} source={label} seed={seed_text}",
                flush=True,
            )
            return WakeWordEvent(
                wakeword=keyword,
                text=seed_text or candidate_text,
                metadata={
                    "language": wake_lang,
                    "detected_lang": detected_lang,
                    "similarity": similarity,
                    "seed_text": seed_text,
                    "source": label,
                },
            )
        return None

    def _should_process(self, rms: int, peak: int) -> bool:
        rms = max(0, int(rms))
        peak = max(0, int(peak))
        if self._noise_floor_rms is None:
            self._noise_floor_rms = float(rms)
        dynamic_threshold = max(
            float(self.idle_min_rms),
            float(self._noise_floor_rms) * self.idle_speech_ratio,
        )
        active = rms >= dynamic_threshold or peak >= self.idle_min_peak
        if active:
            self._release_remaining = self.idle_release_chunks
            return True
        if self._release_remaining > 0:
            self._release_remaining -= 1
            return True
        assert self._noise_floor_rms is not None
        floor_alpha = 0.08
        if rms <= self._noise_floor_rms:
            self._noise_floor_rms = float(rms)
        else:
            self._noise_floor_rms = (
                (1.0 - floor_alpha) * self._noise_floor_rms + floor_alpha * float(rms)
            )
        return False

    def _remember_recent_text(self, text: str) -> None:
        cleaned = (text or "").strip()
        if not cleaned:
            return
        self._recent_texts.append(cleaned)
        max_items = max(1, self.merge_history_chunks)
        if len(self._recent_texts) > max_items:
            self._recent_texts = self._recent_texts[-max_items:]

    def _detection_candidates(self, clean_text: str, compact_text: str) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        seen: set[str] = set()

        def add(label: str, text: str) -> None:
            normalized = (text or "").strip()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            candidates.append((label, normalized))

        add("chunk", clean_text)
        add("chunk_compact", compact_text)

        if len(self._recent_texts) >= 2:
            merged_spaced = " ".join(self._recent_texts)
            merged_compact = "".join(_compact_wake_text(item) for item in self._recent_texts)
            add("history_spaced", merged_spaced)
            add("history_compact", merged_compact)

        return candidates


def factory(
    *,
    settings: AppSettings,
    wakewords: list[str] | tuple[str, ...] | None = None,
    wakeword_script: str | None = None,
    capture_device: str = "default",
    capture_hint: Sequence[str] | None = None,
    chunk_duration: float | None = None,
    software_gain: float | None = None,
    level_interval: float | None = None,
    idle_min_rms: int | None = None,
    idle_min_peak: int | None = None,
    idle_speech_ratio: float | None = None,
    idle_release_chunks: int | None = None,
) -> Om1WakeWordGate:
    script_path = (
        (wakeword_script or "").strip()
        or os.environ.get("WAKEWORD_SCRIPT", "").strip()
        or DEFAULT_WAKEWORD_SCRIPT
    )
    module = _load_wakeword_module(script_path)
    BaseAdaptiveWakeWordSystem = module.AdaptiveWakeWordSystem
    requested_wakewords = _dedupe_keep_order(
        [item.strip() for item in (wakewords or []) if item.strip()]
        + list(DEFAULT_EXTRA_WAKEWORDS)
    )
    selected_device, candidates, hints = _pick_linux_capture_device(capture_device, capture_hint)

    class FrontGateAdaptiveWakeWordSystem(BaseAdaptiveWakeWordSystem):
        def __init__(self) -> None:
            super().__init__(device_id=None)
            threshold_raw = os.environ.get(
                "OM1_WAKEWORD_SIMILARITY_THRESHOLD",
                str(DEFAULT_WAKEWORD_SIMILARITY_THRESHOLD),
            ).strip()
            try:
                self.SIMILARITY_THRESHOLD = float(threshold_raw)
            except ValueError:
                self.SIMILARITY_THRESHOLD = DEFAULT_WAKEWORD_SIMILARITY_THRESHOLD
            if requested_wakewords:
                all_words = []
                for keywords in self.WAKE_WORDS.values():
                    all_words.extend(list(keywords))
                all_words.extend(requested_wakewords)
                self._wakewords = _dedupe_keep_order(all_words)
                for lang, keywords in list(self.WAKE_WORDS.items()):
                    merged = list(keywords)
                    if lang == "zh":
                        merged.extend(requested_wakewords)
                    self.WAKE_WORDS[lang] = _dedupe_keep_order(merged)

    system = FrontGateAdaptiveWakeWordSystem()
    print(f"[FrontGate] wakeword_script={script_path}", flush=True)
    print(f"[FrontGate] capture_device={selected_device}", flush=True)
    if hints:
        print(f"[FrontGate] capture_hints={', '.join(hints)}", flush=True)
    if candidates:
        print("[FrontGate] capture_candidates:", flush=True)
        for candidate in candidates[:8]:
            print(f"  - {candidate}", flush=True)
    if _env_flag("OM1_WAKEWORD_LIST_AUDIO_DEVICES", False) and hasattr(module, "list_audio_devices"):
        try:
            module.list_audio_devices()
        except Exception:
            pass

    return Om1WakeWordGate(
        system=system,
        capture_device=selected_device,
        capture_hints=tuple(hints),
        chunk_duration=float(
            chunk_duration
            if chunk_duration is not None
            else os.environ.get("OM1_WAKEWORD_CHUNK_DURATION", "1.6")
        ),
        software_gain=float(
            software_gain
            if software_gain is not None
            else os.environ.get("OM1_AUDIO_GAIN", "1.0")
        ),
        level_interval=float(
            level_interval
            if level_interval is not None
            else os.environ.get("OM1_AUDIO_LEVEL_INTERVAL", "1.5")
        ),
        idle_min_rms=int(
            idle_min_rms if idle_min_rms is not None else os.environ.get("OM1_IDLE_MIN_RMS", "1100")
        ),
        idle_min_peak=int(
            idle_min_peak
            if idle_min_peak is not None
            else os.environ.get("OM1_IDLE_MIN_PEAK", "4200")
        ),
        idle_speech_ratio=float(
            idle_speech_ratio
            if idle_speech_ratio is not None
            else os.environ.get("OM1_IDLE_SPEECH_RATIO", "1.45")
        ),
        idle_release_chunks=int(
            idle_release_chunks
            if idle_release_chunks is not None
            else os.environ.get("OM1_IDLE_RELEASE_CHUNKS", "2")
        ),
        merge_history_chunks=int(
            os.environ.get("OM1_WAKEWORD_MERGE_HISTORY_CHUNKS", "3")
        ),
        debug_recognition=_env_flag("OM1_WAKEWORD_DEBUG_TEXT", False),
    )
