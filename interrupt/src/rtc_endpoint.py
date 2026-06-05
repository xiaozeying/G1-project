from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import threading
import time
import uuid
import wave
from pathlib import Path

import numpy as np
from livekit import rtc

from src.console_audio_compat import _resample_i16
from src.frontgate_watchdog import (
    detect_pending_prefix_fragment,
    evaluate_frontgate_text,
    followup_window_s,
    frontgate_watchdog_enabled,
    normalize_watchdog_language,
    pending_prefix_window_s,
    text_starts_with_robot_term,
)
from src.livekit_room import build_room_token, ensure_room_ready
from src.settings import RtcEndpointConfig, load_settings
from src.speech_loop_guard import local_playback_guard_active, should_ignore_transcript
from src.tts_mute_state import should_mute_remote_audio


LOGGER = logging.getLogger("interrupt.rtc_endpoint")
TARGET_SAMPLE_RATE = 24000
TARGET_FRAME_SAMPLES = 240
PLAYBACK_ACTIVE_RMS_THRESHOLD = 400.0
MIC_PLAYBACK_DUCK_HOLD_S = 0.9
PLAYBACK_PREBUFFER_MS = int(os.getenv("INTERRUPT_RTC_PLAYBACK_PREBUFFER_MS", "220").strip() or "220")
PLAYBACK_BLOCKSIZE_MS = int(os.getenv("INTERRUPT_RTC_PLAYBACK_BLOCKSIZE_MS", "20").strip() or "20")
PLAYBACK_REBUFFER_MS = int(os.getenv("INTERRUPT_RTC_PLAYBACK_REBUFFER_MS", "120").strip() or "120")
MIC_BARGE_IN_MIN_RMS = 1800.0
MIC_BARGE_IN_PLAYBACK_RATIO = 0.65
MIC_BARGE_IN_OPEN_HOLD_S = 0.8
PAUSE_MIC_DURING_LOCAL_PLAYBACK = os.getenv(
    "INTERRUPT_RTC_PAUSE_MIC_DURING_LOCAL_PLAYBACK",
    "1",
).strip().lower() not in {"0", "false", "no", "off"}
AEC_RESIDUAL_ECHO_CLEAN_RMS = float(
    os.getenv("INTERRUPT_RTC_AEC_RESIDUAL_ECHO_CLEAN_RMS", "320").strip() or "320"
)
AEC_RESIDUAL_ECHO_RAW_RMS = float(
    os.getenv("INTERRUPT_RTC_AEC_RESIDUAL_ECHO_RAW_RMS", "1200").strip() or "1200"
)
AEC_RESIDUAL_ECHO_RATIO = float(
    os.getenv("INTERRUPT_RTC_AEC_RESIDUAL_ECHO_RATIO", "0.20").strip() or "0.20"
)
RTC_TRANSCRIBE_ENABLED = os.getenv("INTERRUPT_RTC_TRANSCRIBE_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
RTC_TRANSCRIBE_MIN_RMS = float(os.getenv("INTERRUPT_RTC_TRANSCRIBE_MIN_RMS", "220.0").strip() or "220.0")
RTC_TRANSCRIBE_SILENCE_S = float(os.getenv("INTERRUPT_RTC_TRANSCRIBE_SILENCE_S", "0.85").strip() or "0.85")
RTC_TRANSCRIBE_MAX_AUDIO_S = float(os.getenv("INTERRUPT_RTC_TRANSCRIBE_MAX_AUDIO_S", "8.0").strip() or "8.0")
RTC_TRANSCRIBE_MIN_AUDIO_S = float(os.getenv("INTERRUPT_RTC_TRANSCRIBE_MIN_AUDIO_S", "0.45").strip() or "0.45")
RTC_TRANSCRIBE_TMP_DIR = Path(
    os.getenv("INTERRUPT_RTC_TRANSCRIBE_TMP_DIR", "/tmp/interrupt_rtc_transcribe").strip()
    or "/tmp/interrupt_rtc_transcribe"
)
RTC_TRANSCRIBE_WORKER = (
    os.getenv("INTERRUPT_RTC_TRANSCRIBE_WORKER", "").strip()
    or "/data/HongTu/interrupt/tools/local_funasr_worker.py"
)
RTC_TRANSCRIBE_PYTHON = (
    os.getenv("INTERRUPT_RTC_TRANSCRIBE_PYTHON", "").strip()
    or "/home/unitree/miniforge3/envs/wakeword-clean/bin/python"
)
RTC_TRANSCRIBE_LANGUAGE = (
    os.getenv("INTERRUPT_RTC_TRANSCRIBE_LANGUAGE", "").strip().lower() or "auto"
)
RTC_TEXT_INPUT_ONLY = os.getenv("INTERRUPT_RTC_TEXT_INPUT_ONLY", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_RTC_CJK_CHAR_RE = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_RTC_TRANSCRIPT_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_RTC_TRANSCRIPT_DIGIT_RE = re.compile(r"\d{2,}")
_RTC_TRANSCRIPT_CJK_RE = re.compile(rf"[{_RTC_CJK_CHAR_RE}]")
_RTC_TRANSCRIPT_CORE_RE = re.compile(rf"[A-Za-z0-9{_RTC_CJK_CHAR_RE}]")
_RTC_TRANSCRIPT_NON_CORE_RE = re.compile(rf"[^A-Za-z0-9{_RTC_CJK_CHAR_RE}]+")


def _normalize_transcript_text(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _is_low_value_local_transcript(text: str) -> bool:
    normalized = _normalize_transcript_text(text)
    if not normalized:
        return True
    if _RTC_TRANSCRIPT_WORD_RE.search(normalized):
        return False
    if _RTC_TRANSCRIPT_DIGIT_RE.search(normalized):
        return False
    if _RTC_TRANSCRIPT_CJK_RE.search(normalized):
        core = _RTC_TRANSCRIPT_NON_CORE_RE.sub("", normalized)
        return len(core) <= 1
    compact = re.sub(r"\s+", "", normalized)
    if not compact:
        return True
    if not _RTC_TRANSCRIPT_CORE_RE.search(compact):
        return True
    return len(compact) <= 1


def _normalize_transcribe_language(raw: str) -> str:
    normalized = (raw or "").strip().lower()
    alias_map = {
        "": "auto",
        "auto": "auto",
        "zh": "zh",
        "zh-cn": "zh",
        "mandarin": "zh",
        "chinese": "zh",
        "yue": "yue",
        "zh-yue": "yue",
        "cantonese": "yue",
        "en": "en",
        "english": "en",
    }
    return alias_map.get(normalized, "auto")


def _resolve_audio_device(device: str | None, *, kind: str) -> tuple[str | None, dict]:
    import sounddevice as sd

    requested = (device or "").strip() or None
    available_devices = sd.query_devices()
    if requested is not None:
        normalized_requested = requested.lower()
        for index, entry in enumerate(available_devices):
            assert isinstance(entry, dict)
            name = str(entry.get("name", ""))
            channels_key = "max_input_channels" if kind == "input" else "max_output_channels"
            if int(entry.get(channels_key, 0) or 0) <= 0:
                continue
            if normalized_requested == name.lower() or normalized_requested in name.lower():
                return index, entry
    candidates: list[str | None] = []
    if requested is not None:
        candidates.append(requested)
    if kind == "input":
        # On the robot, PortAudio often exposes the Pulse virtual input as the
        # only working capture path even when the USB microphone is selected as
        # Pulse's default source. Prefer `pulse` over `default` for input so we
        # bind to the explicit Pulse capture backend instead of an unstable
        # generic default device alias.
        if requested != "pulse":
            candidates.append("pulse")
        if requested != "default":
            candidates.append("default")
    else:
        if requested != "default":
            candidates.append("default")
        if requested != "pulse":
            candidates.append("pulse")
    seen: set[str | None] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            device_info = sd.query_devices(candidate, kind=kind)
        except Exception:
            continue
        assert isinstance(device_info, dict)
        if candidate != requested:
            LOGGER.warning(
                "RTC endpoint %s device fallback: requested=%s resolved=%s",
                kind,
                requested or "default",
                candidate or "default",
            )
        return candidate, device_info
    raise ValueError(f"Unable to resolve {kind} audio device: {requested or 'default'}")


class EchoCanceller:
    def __init__(self) -> None:
        enabled = os.getenv("INTERRUPT_RTC_AEC_ENABLED", "1").strip().lower()
        self._enabled = enabled not in {"0", "false", "no", "off"}
        self._apm: rtc.AudioProcessingModule | None = None
        self._lock = threading.Lock()
        self._reverse_pending = np.empty(0, dtype=np.int16)
        self._last_reverse_log_at = 0.0
        self._last_capture_log_at = 0.0
        if not self._enabled:
            LOGGER.info("RTC AEC disabled by INTERRUPT_RTC_AEC_ENABLED")
            return
        try:
            self._apm = rtc.AudioProcessingModule(
                echo_cancellation=True,
                noise_suppression=False,
                high_pass_filter=True,
                auto_gain_control=False,
            )
            LOGGER.info("RTC AEC enabled: livekit AudioProcessingModule")
        except Exception:
            self._enabled = False
            LOGGER.exception("RTC AEC initialization failed; falling back to microphone ducking")

    @property
    def enabled(self) -> bool:
        return self._enabled and self._apm is not None

    def set_stream_delay_ms(self, delay_ms: int) -> None:
        if not self.enabled:
            return
        assert self._apm is not None
        with self._lock:
            try:
                self._apm.set_stream_delay_ms(max(0, delay_ms))
            except RuntimeError:
                pass

    def process_reverse(self, samples: np.ndarray) -> None:
        if not self.enabled or samples.size <= 0:
            return
        assert self._apm is not None
        with self._lock:
            if self._reverse_pending.size:
                pending = np.concatenate((self._reverse_pending, samples.astype(np.int16, copy=False)))
            else:
                pending = samples.astype(np.int16, copy=False)
            full_frames = pending.size // TARGET_FRAME_SAMPLES
            for index in range(full_frames):
                start = index * TARGET_FRAME_SAMPLES
                end = start + TARGET_FRAME_SAMPLES
                frame = rtc.AudioFrame(
                    data=pending[start:end].tobytes(),
                    samples_per_channel=TARGET_FRAME_SAMPLES,
                    sample_rate=TARGET_SAMPLE_RATE,
                    num_channels=1,
                )
                self._apm.process_reverse_stream(frame)
            self._reverse_pending = pending[full_frames * TARGET_FRAME_SAMPLES :].copy()
        now = time.monotonic()
        if now - self._last_reverse_log_at >= 5.0:
            LOGGER.info("RTC AEC reverse stream updated: samples=%s", samples.size)
            self._last_reverse_log_at = now

    def process_capture(self, samples: np.ndarray) -> np.ndarray:
        if not self.enabled or samples.size != TARGET_FRAME_SAMPLES:
            return samples
        assert self._apm is not None
        frame = rtc.AudioFrame(
            data=samples.astype(np.int16, copy=False).tobytes(),
            samples_per_channel=TARGET_FRAME_SAMPLES,
            sample_rate=TARGET_SAMPLE_RATE,
            num_channels=1,
        )
        with self._lock:
            self._apm.process_stream(frame)
        cleaned = np.frombuffer(frame.data, dtype=np.int16).copy()
        now = time.monotonic()
        if now - self._last_capture_log_at >= 5.0:
            raw_level = samples.astype(np.float32)
            clean_level = cleaned.astype(np.float32)
            raw_rms = float(np.sqrt(np.mean(np.square(raw_level)))) if raw_level.size else 0.0
            clean_rms = float(np.sqrt(np.mean(np.square(clean_level)))) if clean_level.size else 0.0
            LOGGER.info("RTC AEC capture processed: raw_rms=%.1f clean_rms=%.1f", raw_rms, clean_rms)
            self._last_capture_log_at = now
        return cleaned


class OutputPlayback:
    def __init__(self, device: str | None, *, aec: EchoCanceller | None = None) -> None:
        self._device = device or None
        self._aec = aec
        self._stream = None
        self._sample_rate = TARGET_SAMPLE_RATE
        self._channels = 1
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._last_level_log_at = 0.0
        self._prebuffering = True
        self._prebuffer_bytes = 0
        self._rebuffer_bytes = 0
        self._last_active_audio_at = 0.0
        self._last_active_rms = 0.0
        self._output_delay_s = 0.0
        self._last_buffer_warning_at = 0.0

    def start(self) -> None:
        import sounddevice as sd

        self._device, device_info = _resolve_audio_device(self._device, kind="output")
        self._sample_rate = int(round(float(device_info.get("default_samplerate", TARGET_SAMPLE_RATE))))
        self._channels = max(1, min(int(device_info.get("max_output_channels", 1) or 1), 2))
        blocksize = max(
            TARGET_FRAME_SAMPLES,
            int(self._sample_rate * (PLAYBACK_BLOCKSIZE_MS / 1000.0)),
        )
        self._stream = sd.OutputStream(
            callback=self._callback,
            dtype="int16",
            channels=self._channels,
            device=self._device,
            samplerate=self._sample_rate,
            blocksize=blocksize,
        )
        self._stream.start()
        self._prebuffer_bytes = max(
            int(self._sample_rate * 2 * (PLAYBACK_PREBUFFER_MS / 1000.0)),
            TARGET_FRAME_SAMPLES * 4,
        )
        self._rebuffer_bytes = max(
            int(self._sample_rate * 2 * (PLAYBACK_REBUFFER_MS / 1000.0)),
            TARGET_FRAME_SAMPLES * 2,
        )
        self._prebuffering = True
        LOGGER.info(
            "RTC endpoint output started: device=%s sr=%s channels=%s blocksize=%s prebuffer_bytes=%s rebuffer_bytes=%s",
            device_info.get("name", self._device or "default"),
            self._sample_rate,
            self._channels,
            blocksize,
            self._prebuffer_bytes,
            self._rebuffer_bytes,
        )

    def close(self) -> None:
        if self._stream is None:
            return
        try:
            self._stream.abort()
        except Exception:
            pass
        try:
            self._stream.stop()
        except Exception:
            pass
        self._stream.close()
        self._stream = None

    def push_frame(self, frame: rtc.AudioFrame, *, source_identity: str = "") -> None:
        if should_mute_remote_audio(identity=source_identity):
            return
        samples = np.frombuffer(frame.data, dtype=np.int16).copy()
        if self._aec is not None and self._aec.enabled:
            self._aec.process_reverse(_resample_i16(samples, frame.sample_rate, TARGET_SAMPLE_RATE))
        rendered = _resample_i16(samples, frame.sample_rate, self._sample_rate)
        now = time.monotonic()
        if now - self._last_level_log_at >= 2.0:
            level = rendered.astype(np.float32)
            rms = float(np.sqrt(np.mean(np.square(level)))) if level.size else 0.0
            peak = int(np.max(np.abs(level))) if level.size else 0
            LOGGER.info("RTC playback level: rms=%.1f peak=%s", rms, peak)
            self._last_level_log_at = now
        if rendered.size:
            level = rendered.astype(np.float32)
            rms = float(np.sqrt(np.mean(np.square(level)))) if level.size else 0.0
            if rms >= PLAYBACK_ACTIVE_RMS_THRESHOLD:
                self._last_active_audio_at = now
                self._last_active_rms = rms
        with self._lock:
            self._buffer.extend(rendered.tobytes())
            max_bytes = self._sample_rate * 2 * 6
            if len(self._buffer) > max_bytes:
                drop = len(self._buffer) - max_bytes
                del self._buffer[:drop]

    def recently_active(self) -> bool:
        return (time.monotonic() - self._last_active_audio_at) <= MIC_PLAYBACK_DUCK_HOLD_S

    def recent_rms(self) -> float:
        if not self.recently_active():
            return 0.0
        return self._last_active_rms

    def output_delay_s(self) -> float:
        return self._output_delay_s

    def _callback(
        self,
        outdata: np.ndarray,
        frames: int,
        time_info: object = None,
        status: object = None,
    ) -> None:
        current_time = getattr(time_info, "currentTime", None)
        output_time = getattr(time_info, "outputBufferDacTime", None)
        if current_time is not None and output_time is not None:
            self._output_delay_s = max(0.0, float(output_time) - float(current_time))
        bytes_needed = frames * 2
        with self._lock:
            if getattr(status, "output_underflow", False):
                self._prebuffering = True
            if not self._prebuffering and len(self._buffer) < bytes_needed:
                self._prebuffering = True
                now = time.monotonic()
                if now - self._last_buffer_warning_at >= 2.0:
                    LOGGER.warning(
                        "RTC output buffer underrun: available_bytes=%s required_bytes=%s rebuffer_bytes=%s",
                        len(self._buffer),
                        bytes_needed,
                        self._rebuffer_bytes,
                    )
                    self._last_buffer_warning_at = now
            buffer_target = self._prebuffer_bytes if self._last_active_audio_at == 0.0 else self._rebuffer_bytes
            if self._prebuffering and len(self._buffer) < buffer_target:
                outdata[:] = 0
                return
            self._prebuffering = False
            raw = bytes(self._buffer[:bytes_needed])
            del self._buffer[: len(raw)]
        samples = np.frombuffer(raw, dtype=np.int16)
        outdata[:] = 0
        write_frames = min(frames, samples.size)
        if write_frames <= 0:
            return
        if outdata.ndim == 1:
            outdata[:write_frames] = samples[:write_frames]
            return
        mono = samples[:write_frames]
        outdata[:write_frames, : self._channels] = np.repeat(mono[:, None], self._channels, axis=1)


class MicrophonePublisher:
    def __init__(
        self,
        device: str | None,
        loop: asyncio.AbstractEventLoop,
        *,
        playback: OutputPlayback | None = None,
        aec: EchoCanceller | None = None,
    ) -> None:
        self._device = device or None
        self._loop = loop
        self._playback = playback
        self._aec = aec
        self._stream = None
        self._source: rtc.AudioSource | None = None
        self._track: rtc.LocalAudioTrack | None = None
        self._queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=32)
        self._pending = np.empty(0, dtype=np.int16)
        self._input_sr = TARGET_SAMPLE_RATE
        self._input_channels = 1
        self._task: asyncio.Task[None] | None = None
        self._last_level_log_at = 0.0
        self._barge_in_open_until = 0.0
        self._last_duck_log_at = 0.0
        self._last_barge_in_log_at = 0.0
        self._last_local_playback_pause_log_at = 0.0
        self._last_residual_echo_log_at = 0.0
        self._input_delay_s = 0.0
        self._callback_count = 0
        self._last_callback_at = 0.0
        self._last_queue_push_at = 0.0
        self._restart_lock = threading.Lock()
        self._restarting = False
        self._restart_count = 0
        self._watchdog_stop: threading.Event | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._reader_proc: subprocess.Popen[bytes] | None = None
        self._reader_thread: threading.Thread | None = None
        self._use_arecord_backend = False
        self._transcriber: LocalTranscriber | None = None

    async def start(self, room: rtc.Room) -> None:
        device_request = (self._device or "").strip()
        self._use_arecord_backend = device_request.startswith("plughw:") or device_request.startswith("hw:")
        if self._use_arecord_backend:
            device_info = {"name": device_request or "arecord", "default_samplerate": TARGET_SAMPLE_RATE}
            self._input_sr = TARGET_SAMPLE_RATE
            self._input_channels = 1
        else:
            self._device, device_info = _resolve_audio_device(self._device, kind="input")
            self._input_sr = int(round(float(device_info.get("default_samplerate", TARGET_SAMPLE_RATE))))
            self._input_channels = max(1, min(int(device_info.get("max_input_channels", 1) or 1), 2))
        self._source = rtc.AudioSource(TARGET_SAMPLE_RATE, 1, queue_size_ms=1000, loop=self._loop)
        self._track = rtc.LocalAudioTrack.create_audio_track("robot-microphone", self._source)
        await room.local_participant.publish_track(
            self._track,
            rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
        )
        if RTC_TRANSCRIBE_ENABLED:
            self._transcriber = LocalTranscriber(room, self._track.sid, self._loop)
            await self._transcriber.start()
        self._open_stream()
        self._task = asyncio.create_task(self._pump())
        self._last_callback_at = time.monotonic()
        self._last_queue_push_at = self._last_callback_at
        self._ensure_watchdog()
        LOGGER.info(
            "RTC endpoint microphone started: device=%s sr=%s channels=%s",
            device_info.get("name", self._device or "default"),
            self._input_sr,
            self._input_channels,
        )

    async def aclose(self) -> None:
        if self._watchdog_stop is not None:
            self._watchdog_stop.set()
            self._watchdog_stop = None
        if self._stream is not None:
            self._close_stream()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._transcriber is not None:
            await self._transcriber.aclose()
            self._transcriber = None
        if self._source is not None:
            await self._source.aclose()
            self._source = None

    def _open_stream(self) -> None:
        if self._use_arecord_backend:
            self._open_arecord_reader()
            return

        import sounddevice as sd

        self._stream = sd.InputStream(
            callback=self._callback,
            dtype="int16",
            channels=self._input_channels,
            device=self._device,
            samplerate=self._input_sr,
            blocksize=max(TARGET_FRAME_SAMPLES, self._input_sr // 100),
        )
        self._stream.start()

    def _close_stream(self) -> None:
        if self._use_arecord_backend:
            self._close_arecord_reader()
            return
        if self._stream is None:
            return
        try:
            self._stream.abort()
        except Exception:
            pass
        try:
            self._stream.stop()
        except Exception:
            pass
        self._stream.close()
        self._stream = None

    def _open_arecord_reader(self) -> None:
        device = self._device or "plughw:CARD=audio,DEV=0"
        cmd = [
            "arecord",
            "-D",
            device,
            "-q",
            "-t",
            "raw",
            "-f",
            "S16_LE",
            "-r",
            str(self._input_sr),
            "-c",
            str(self._input_channels),
        ]
        self._reader_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        self._stream = self._reader_proc

        def _reader() -> None:
            assert self._reader_proc is not None
            assert self._reader_proc.stdout is not None
            bytes_per_chunk = TARGET_FRAME_SAMPLES * self._input_channels * 2
            while True:
                try:
                    raw = self._reader_proc.stdout.read(bytes_per_chunk)
                except Exception:
                    break
                if not raw:
                    break
                chunk = np.frombuffer(raw, dtype=np.int16).copy()
                if self._input_channels > 1:
                    chunk = chunk.reshape(-1, self._input_channels)
                else:
                    chunk = chunk.reshape(-1, 1)
                self._callback(chunk, len(chunk), None)

        self._reader_thread = threading.Thread(
            target=_reader,
            name="interrupt-rtc-arecord-reader",
            daemon=True,
        )
        self._reader_thread.start()

    def _close_arecord_reader(self) -> None:
        proc = self._reader_proc
        self._reader_proc = None
        self._stream = None
        if proc is None:
            return
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=1.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        self._reader_thread = None

    def _ensure_watchdog(self) -> None:
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            return
        stop_event = threading.Event()
        self._watchdog_stop = stop_event

        def _watchdog() -> None:
            stall_s = float(os.getenv("INTERRUPT_RTC_INPUT_STALL_S", "2.5").strip() or "2.5")
            poll_s = float(os.getenv("INTERRUPT_RTC_INPUT_WATCHDOG_POLL_S", "0.5").strip() or "0.5")
            while not stop_event.wait(max(0.2, poll_s)):
                if self._stream is None:
                    continue
                if self._restarting:
                    continue
                if not self._use_arecord_backend and not getattr(self._stream, "active", True):
                    self._restart_stream("stream_inactive")
                    continue
                callback_count = self._callback_count
                if callback_count <= 0:
                    if time.monotonic() - self._last_callback_at >= stall_s:
                        self._restart_stream("no_callbacks")
                    continue
                if time.monotonic() - self._last_callback_at >= stall_s:
                    self._restart_stream("callback_stalled")
                    continue
                if time.monotonic() - self._last_queue_push_at >= stall_s:
                    self._restart_stream("queue_push_stalled")

        self._watchdog_thread = threading.Thread(
            target=_watchdog,
            name="interrupt-rtc-input-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

    def _restart_stream(self, reason: str) -> None:
        if not self._restart_lock.acquire(blocking=False):
            return
        try:
            if self._restarting:
                return
            self._restarting = True
            LOGGER.warning(
                "RTC endpoint restarting microphone stream: reason=%s device=%s callbacks=%s restarts=%s",
                reason,
                self._device or "default",
                self._callback_count,
                self._restart_count,
            )
            self._close_stream()
            time.sleep(float(os.getenv("INTERRUPT_RTC_INPUT_RESTART_DELAY_S", "0.15").strip() or "0.15"))
            self._open_stream()
            self._callback_count = 0
            self._last_callback_at = time.monotonic()
            self._last_queue_push_at = self._last_callback_at
            self._restart_count += 1
            LOGGER.info(
                "RTC endpoint microphone stream restarted: device=%s restarts=%s",
                self._device or "default",
                self._restart_count,
            )
        except Exception:
            LOGGER.exception(
                "RTC endpoint microphone stream restart failed: reason=%s device=%s",
                reason,
                self._device or "default",
            )
        finally:
            self._restarting = False
            self._restart_lock.release()

    def _callback(self, indata: np.ndarray, _frames: int, time_info: object = None, *_: object) -> None:
        current_time = getattr(time_info, "currentTime", None)
        input_time = getattr(time_info, "inputBufferAdcTime", None)
        if current_time is not None and input_time is not None:
            self._input_delay_s = max(0.0, float(current_time) - float(input_time))
        self._callback_count += 1
        self._last_callback_at = time.monotonic()
        chunk = np.array(indata, copy=True)
        if chunk.ndim == 1:
            mono = chunk.astype(np.int16, copy=False)
        elif chunk.shape[1] == 1:
            mono = chunk[:, 0].astype(np.int16, copy=False)
        else:
            mono = np.mean(chunk.astype(np.float32), axis=1).astype(np.int16)
        now = time.monotonic()
        level = mono.astype(np.float32)
        rms = float(np.sqrt(np.mean(np.square(level)))) if level.size else 0.0
        peak = int(np.max(np.abs(level))) if level.size else 0
        if now - self._last_level_log_at >= 2.0:
            LOGGER.info("RTC microphone level: rms=%.1f peak=%s", rms, peak)
            self._last_level_log_at = now
        if PAUSE_MIC_DURING_LOCAL_PLAYBACK and local_playback_guard_active():
            if now - self._last_local_playback_pause_log_at >= 1.0:
                LOGGER.info(
                    "RTC microphone paused during local playback guard: mic_rms=%.1f peak=%s",
                    rms,
                    peak,
                )
                self._last_local_playback_pause_log_at = now
            mono = np.zeros_like(mono)
        if (
            (self._aec is None or not self._aec.enabled)
            and self._playback is not None
            and self._playback.recently_active()
        ):
            playback_rms = self._playback.recent_rms()
            gate_rms = max(MIC_BARGE_IN_MIN_RMS, playback_rms * MIC_BARGE_IN_PLAYBACK_RATIO)
            if rms >= gate_rms:
                self._barge_in_open_until = now + MIC_BARGE_IN_OPEN_HOLD_S
                if now - self._last_barge_in_log_at >= 1.0:
                    LOGGER.info(
                        "RTC microphone barge-in opened: mic_rms=%.1f playback_rms=%.1f gate_rms=%.1f",
                        rms,
                        playback_rms,
                        gate_rms,
                    )
                    self._last_barge_in_log_at = now
            elif now < self._barge_in_open_until:
                pass
            else:
                if now - self._last_duck_log_at >= 1.0:
                    LOGGER.info(
                        "RTC microphone ducked during playback: mic_rms=%.1f playback_rms=%.1f gate_rms=%.1f",
                        rms,
                        playback_rms,
                        gate_rms,
                    )
                    self._last_duck_log_at = now
                mono = np.zeros_like(mono)
        try:
            self._loop.call_soon_threadsafe(self._enqueue_chunk, mono)
        except RuntimeError:
            return

    def _enqueue_chunk(self, chunk: np.ndarray) -> None:
        self._last_queue_push_at = time.monotonic()
        if self._transcriber is not None:
            self._transcriber.push_chunk(chunk)
        try:
            self._queue.put_nowait(chunk)
        except asyncio.QueueFull:
            try:
                _ = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(chunk)
            except asyncio.QueueFull:
                LOGGER.warning("RTC endpoint microphone queue full; dropped chunk")

    async def _pump(self) -> None:
        assert self._source is not None
        while True:
            chunk = await self._queue.get()
            resampled = _resample_i16(chunk, self._input_sr, TARGET_SAMPLE_RATE)
            if self._pending.size:
                self._pending = np.concatenate((self._pending, resampled))
            else:
                self._pending = resampled
            full_frames = self._pending.size // TARGET_FRAME_SAMPLES
            if full_frames <= 0:
                continue
            for index in range(full_frames):
                start = index * TARGET_FRAME_SAMPLES
                end = start + TARGET_FRAME_SAMPLES
                frame_samples = self._pending[start:end]
                if self._aec is not None and self._aec.enabled:
                    output_delay_s = self._playback.output_delay_s() if self._playback is not None else 0.0
                    self._aec.set_stream_delay_ms(int((self._input_delay_s + output_delay_s) * 1000))
                    raw_frame_samples = frame_samples
                    frame_samples = self._aec.process_capture(frame_samples)
                    if self._looks_like_residual_echo(raw_frame_samples, frame_samples):
                        frame_samples = np.zeros_like(frame_samples)
                outbound_samples = (
                    np.zeros_like(frame_samples) if RTC_TEXT_INPUT_ONLY else frame_samples
                )
                frame = rtc.AudioFrame(
                    data=outbound_samples.tobytes(),
                    samples_per_channel=TARGET_FRAME_SAMPLES,
                    sample_rate=TARGET_SAMPLE_RATE,
                    num_channels=1,
                )
                await self._source.capture_frame(frame)
            self._pending = self._pending[full_frames * TARGET_FRAME_SAMPLES :]

    def _looks_like_residual_echo(self, raw_samples: np.ndarray, clean_samples: np.ndarray) -> bool:
        if self._playback is None or not self._playback.recently_active():
            return False
        raw_level = raw_samples.astype(np.float32)
        clean_level = clean_samples.astype(np.float32)
        raw_rms = float(np.sqrt(np.mean(np.square(raw_level)))) if raw_level.size else 0.0
        clean_rms = float(np.sqrt(np.mean(np.square(clean_level)))) if clean_level.size else 0.0
        if raw_rms < AEC_RESIDUAL_ECHO_RAW_RMS:
            return False
        if clean_rms > AEC_RESIDUAL_ECHO_CLEAN_RMS:
            return False
        if clean_rms > raw_rms * AEC_RESIDUAL_ECHO_RATIO:
            return False
        now = time.monotonic()
        if now - self._last_residual_echo_log_at >= 1.0:
            LOGGER.info(
                "RTC AEC residual echo suppressed: raw_rms=%.1f clean_rms=%.1f playback_rms=%.1f",
                raw_rms,
                clean_rms,
                self._playback.recent_rms(),
            )
            self._last_residual_echo_log_at = now
        return True


class LocalTranscriber:
    def __init__(self, room: rtc.Room, track_sid: str, loop: asyncio.AbstractEventLoop) -> None:
        self._room = room
        self._track_sid = track_sid
        self._loop = loop
        self._queue: asyncio.Queue[tuple[str, str, str]] = asyncio.Queue()
        self._drain_task: asyncio.Task[None] | None = None
        self._worker: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._request_lock = threading.Lock()
        self._last_active_at = 0.0
        self._segment_started_at = 0.0
        self._segment_buffers: list[np.ndarray] = []
        self._language_hint = _normalize_transcribe_language(RTC_TRANSCRIBE_LANGUAGE)
        self._followup_until = 0.0
        self._followup_language = ""
        self._pending_prefix_until = 0.0
        self._pending_prefix_language = ""
        self._pending_prefix_text = ""

    async def start(self) -> None:
        RTC_TRANSCRIBE_TMP_DIR.mkdir(parents=True, exist_ok=True)
        self._worker = subprocess.Popen(
            [RTC_TRANSCRIBE_PYTHON, RTC_TRANSCRIBE_WORKER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        assert self._worker.stdout is not None
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="interrupt-rtc-local-transcriber-reader",
            daemon=True,
        )
        self._reader_thread.start()
        self._drain_task = asyncio.create_task(self._drain_results())
        LOGGER.info(
            "RTC local transcriber started: worker=%s python=%s language_hint=%s text_input_only=%s watchdog=%s",
            RTC_TRANSCRIBE_WORKER,
            RTC_TRANSCRIBE_PYTHON,
            self._language_hint,
            RTC_TEXT_INPUT_ONLY,
            frontgate_watchdog_enabled(),
        )

    async def aclose(self) -> None:
        await self._flush_segment(force=True)
        if self._drain_task is not None:
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass
            self._drain_task = None
        worker = self._worker
        self._worker = None
        if worker is not None:
            try:
                if worker.stdin is not None:
                    worker.stdin.close()
            except Exception:
                pass
            try:
                worker.terminate()
            except Exception:
                pass
        self._reader_thread = None

    def push_chunk(self, chunk: np.ndarray) -> None:
        now = time.monotonic()
        level = chunk.astype(np.float32)
        rms = float(np.sqrt(np.mean(np.square(level)))) if level.size else 0.0
        active = rms >= RTC_TRANSCRIBE_MIN_RMS
        if active:
            if not self._segment_buffers:
                self._segment_started_at = now
            self._last_active_at = now
            self._segment_buffers.append(chunk.copy())
            if self._segment_duration_s() >= RTC_TRANSCRIBE_MAX_AUDIO_S:
                asyncio.run_coroutine_threadsafe(self._flush_segment(force=True), self._loop)
            return
        if not self._segment_buffers:
            return
        if now - self._last_active_at >= RTC_TRANSCRIBE_SILENCE_S:
            asyncio.run_coroutine_threadsafe(self._flush_segment(), self._loop)
            return
        self._segment_buffers.append(chunk.copy())
        if self._segment_duration_s() >= RTC_TRANSCRIBE_MAX_AUDIO_S:
            asyncio.run_coroutine_threadsafe(self._flush_segment(force=True), self._loop)

    def _segment_duration_s(self) -> float:
        if not self._segment_buffers:
            return 0.0
        total_samples = sum(chunk.size for chunk in self._segment_buffers)
        return total_samples / float(TARGET_SAMPLE_RATE)

    async def _flush_segment(self, force: bool = False) -> None:
        if not self._segment_buffers:
            return
        duration_s = self._segment_duration_s()
        if not force and duration_s < RTC_TRANSCRIBE_MIN_AUDIO_S:
            self._segment_buffers.clear()
            self._segment_started_at = 0.0
            return
        request_id = uuid.uuid4().hex
        wav_path = RTC_TRANSCRIBE_TMP_DIR / f"{request_id}.wav"
        audio = np.concatenate(self._segment_buffers).astype(np.int16, copy=False)
        self._segment_buffers.clear()
        self._segment_started_at = 0.0
        await asyncio.to_thread(self._write_wav, wav_path, audio)
        payload = {
            "id": request_id,
            "wav_path": str(wav_path),
            "language": self._language_hint,
        }
        worker = self._worker
        if worker is None or worker.stdin is None:
            LOGGER.warning("RTC local transcriber unavailable; dropped request=%s", request_id)
            return
        with self._request_lock:
            worker.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            worker.stdin.flush()

    def _reader_loop(self) -> None:
        worker = self._worker
        if worker is None or worker.stdout is None:
            return
        for line in worker.stdout:
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            request_id = str(payload.get("id", "") or "")
            text = str(payload.get("text", "") or "")
            language = str(payload.get("language", "") or "")
            error = str(payload.get("error", "") or "")
            try:
                asyncio.run_coroutine_threadsafe(
                    self._queue.put((request_id, text, language or "zh", error)),
                    self._loop,
                )
            except RuntimeError:
                return

    async def _drain_results(self) -> None:
        while True:
            request_id, text, language, error = await self._queue.get()
            wav_path = RTC_TRANSCRIBE_TMP_DIR / f"{request_id}.wav"
            try:
                wav_path.unlink(missing_ok=True)
            except Exception:
                pass
            if error:
                LOGGER.warning("RTC local transcription failed: id=%s error=%s", request_id, error)
                continue
            cleaned = _normalize_transcript_text(text)
            if not cleaned:
                continue
            if _is_low_value_local_transcript(cleaned):
                LOGGER.info(
                    "RTC local transcription dropped low-value text: id=%s text=%r language=%s",
                    request_id,
                    cleaned,
                    language,
                )
                continue
            if local_playback_guard_active() and should_ignore_transcript(cleaned):
                LOGGER.info("RTC local transcription dropped probable self-playback echo: text=%r", cleaned)
                continue
            accepted_text, accepted_language = self._apply_frontgate_watchdog(cleaned, language)
            if not accepted_text:
                continue
            segment = rtc.TranscriptionSegment(
                id=request_id,
                text=accepted_text,
                start_time=0,
                end_time=0,
                language=accepted_language,
                final=True,
            )
            transcription = rtc.Transcription(
                participant_identity=self._room.local_participant.identity,
                track_sid=self._track_sid,
                segments=[segment],
            )
            try:
                if not RTC_TEXT_INPUT_ONLY:
                    await self._room.local_participant.publish_transcription(transcription)
                payload = json.dumps(
                    {
                        "text": accepted_text,
                        "language": accepted_language,
                        "final": True,
                        "text_input_only": RTC_TEXT_INPUT_ONLY,
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                await self._room.local_participant.publish_data(
                    payload,
                    topic="interrupt/local_text/transcript",
                )
                LOGGER.info(
                    "RTC local transcription published: identity=%s text=%r language=%s",
                    self._room.local_participant.identity,
                    accepted_text,
                    accepted_language,
                )
            except Exception:
                LOGGER.exception("RTC local transcription publish failed: text=%r", accepted_text)

    def _apply_frontgate_watchdog(self, text: str, language: str) -> tuple[str, str]:
        normalized_language = normalize_watchdog_language(language)
        if not frontgate_watchdog_enabled():
            return text, language
        if self._pending_prefix_until > time.monotonic():
            pending_language = self._pending_prefix_language or normalized_language or language
            merged = f"{self._pending_prefix_text} {text}".strip()
            if text_starts_with_robot_term(text, language=pending_language) or self._pending_prefix_text:
                self._clear_pending_prefix_state()
                decision = evaluate_frontgate_text(merged, default_language=pending_language)
                if decision.action == "accepted":
                    self._clear_followup_state()
                    LOGGER.info(
                        "RTC frontgate watchdog accepted merged prefix fragments: merged=%r language=%s",
                        merged,
                        decision.language or pending_language,
                    )
                    return decision.content, decision.language or pending_language
            self._clear_pending_prefix_state()
        decision = evaluate_frontgate_text(text, default_language=normalized_language)
        if decision.action == "accepted":
            self._clear_followup_state()
            self._clear_pending_prefix_state()
            return decision.content, decision.language or language
        if decision.action == "prefix_only":
            window_s = followup_window_s()
            self._followup_until = time.monotonic() + window_s
            self._followup_language = decision.language
            self._clear_pending_prefix_state()
            LOGGER.info(
                "RTC frontgate watchdog armed follow-up window: language=%s prefix=%r timeout=%.1fs",
                decision.language,
                decision.prefix,
                window_s,
            )
            return "", language
        pending = detect_pending_prefix_fragment(text, default_language=normalized_language)
        if pending.action == "pending_prefix":
            window_s = pending_prefix_window_s()
            self._pending_prefix_until = time.monotonic() + window_s
            self._pending_prefix_language = pending.language
            self._pending_prefix_text = pending.prefix
            LOGGER.info(
                "RTC frontgate watchdog armed pending-prefix window: language=%s prefix=%r timeout=%.1fs",
                pending.language,
                pending.prefix,
                window_s,
            )
            return "", language
        if self._followup_until > time.monotonic():
            followup_language = self._followup_language or normalized_language or language
            self._clear_followup_state()
            self._clear_pending_prefix_state()
            LOGGER.info(
                "RTC frontgate watchdog accepted follow-up without repeated prefix: text=%r language=%s",
                text,
                followup_language,
            )
            return text, followup_language or language
        self._clear_pending_prefix_state()
        LOGGER.info("RTC frontgate watchdog dropped unmatched transcript: text=%r language=%s", text, language)
        return "", language

    def _clear_followup_state(self) -> None:
        self._followup_until = 0.0
        self._followup_language = ""

    def _clear_pending_prefix_state(self) -> None:
        self._pending_prefix_until = 0.0
        self._pending_prefix_language = ""
        self._pending_prefix_text = ""

    @staticmethod
    def _write_wav(path: Path, audio: np.ndarray) -> None:
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(TARGET_SAMPLE_RATE)
            handle.writeframes(audio.tobytes())


class RobotRtcEndpoint:
    def __init__(self, config: RtcEndpointConfig) -> None:
        self._settings = load_settings()
        self._config = config
        self._room = rtc.Room()
        self._done = asyncio.Event()
        self._aec = EchoCanceller()
        self._playback = (
            OutputPlayback(config.output_device, aec=self._aec) if config.subscribe_audio else None
        )
        self._mic = None
        self._track_tasks: set[asyncio.Task[None]] = set()
        self._audio_track_tasks_by_participant: dict[str, asyncio.Task[None]] = {}
        self._monitor_task: asyncio.Task[None] | None = None
        self._redispatch_task: asyncio.Task[None] | None = None
        self._agent_participants: set[str] = set()
        self._last_redispatch_at = 0.0

    async def run(self) -> None:
        if self._config.auto_create_room or self._config.auto_dispatch_agent:
            await ensure_room_ready(
                self._settings,
                self._config.room_name,
                create_room=self._config.auto_create_room,
                dispatch_agent=self._config.auto_dispatch_agent,
                dispatch_metadata="robot-rtc-endpoint-bootstrap",
            )

        token = build_room_token(
            self._settings,
            room_name=self._config.room_name,
            identity=self._config.identity,
        )
        self._bind_events()
        await self._room.connect(self._settings.livekit.url, token)
        LOGGER.info(
            "RTC endpoint connected: room=%s identity=%s publish_mic=%s subscribe_audio=%s",
            self._config.room_name,
            self._config.identity,
            self._config.publish_microphone,
            self._config.subscribe_audio,
        )
        for participant in self._room.remote_participants.values():
            identity = getattr(participant, "identity", "")
            if self._is_agent_identity(identity):
                self._agent_participants.add(identity)
        self._maybe_start_room_monitor()

        if self._playback is not None:
            self._playback.start()

        if self._config.publish_microphone:
            self._mic = MicrophonePublisher(
                self._config.input_device,
                asyncio.get_running_loop(),
                playback=self._playback,
                aec=self._aec,
            )
            await self._mic.start(self._room)

        await self._done.wait()

    async def aclose(self) -> None:
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        if self._redispatch_task is not None:
            self._redispatch_task.cancel()
            try:
                await self._redispatch_task
            except asyncio.CancelledError:
                pass
            self._redispatch_task = None
        for task in list(self._track_tasks):
            task.cancel()
        for task in list(self._track_tasks):
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._track_tasks.clear()
        self._audio_track_tasks_by_participant.clear()

        if self._mic is not None:
            await self._mic.aclose()
            self._mic = None

        if self._playback is not None:
            self._playback.close()

        if self._room.isconnected():
            await self._room.disconnect()

    def _bind_events(self) -> None:
        @self._room.on("connected")
        def _on_connected() -> None:
            LOGGER.info("RTC endpoint room connected")

        @self._room.on("disconnected")
        def _on_disconnected(reason: object) -> None:
            LOGGER.info("RTC endpoint room disconnected: reason=%s", reason)
            self._done.set()

        @self._room.on("participant_connected")
        def _on_participant_connected(participant: object) -> None:
            identity = getattr(participant, "identity", "")
            LOGGER.info("RTC remote participant connected: identity=%s", identity)
            if self._is_agent_identity(identity):
                self._agent_participants.add(identity)
                LOGGER.info("RTC agent participant online: identity=%s", identity)

        @self._room.on("participant_disconnected")
        def _on_participant_disconnected(participant: object) -> None:
            identity = getattr(participant, "identity", "")
            LOGGER.info("RTC remote participant disconnected: identity=%s", identity)
            prior_task = self._audio_track_tasks_by_participant.pop(identity, None)
            if prior_task is not None:
                prior_task.cancel()
            if self._is_agent_identity(identity):
                self._agent_participants.discard(identity)
                LOGGER.info("RTC agent participant offline: identity=%s", identity)
                self._schedule_redispatch("agent-disconnected")

        @self._room.on("track_subscribed")
        def _on_track_subscribed(track: object, publication: object, participant: object) -> None:
            if not self._config.subscribe_audio:
                return
            if not isinstance(track, rtc.RemoteAudioTrack):
                return
            LOGGER.info(
                "RTC audio track subscribed: participant=%s sid=%s source=%s",
                getattr(participant, "identity", ""),
                getattr(track, "sid", ""),
                getattr(publication, "source", ""),
            )
            participant_identity = getattr(participant, "identity", "")
            prior_task = self._audio_track_tasks_by_participant.get(participant_identity)
            if prior_task is not None and not prior_task.done():
                LOGGER.info(
                    "RTC replacing prior audio track consumer: participant=%s sid=%s",
                    participant_identity,
                    getattr(track, "sid", ""),
                )
                prior_task.cancel()
            task = asyncio.create_task(self._consume_remote_audio(track, participant))
            self._track_tasks.add(task)
            task.add_done_callback(self._track_tasks.discard)
            self._audio_track_tasks_by_participant[participant_identity] = task

        @self._room.on("track_subscription_failed")
        def _on_track_subscription_failed(participant: object, track_sid: str, error: str) -> None:
            LOGGER.warning(
                "RTC track subscription failed: participant=%s sid=%s error=%s",
                getattr(participant, "identity", ""),
                track_sid,
                error,
            )

        @self._room.on("transcription_received")
        def _on_transcription_received(segments: list[object], participant: object, _publication: object) -> None:
            texts = [getattr(segment, "text", "").strip() for segment in segments]
            merged = " ".join(text for text in texts if text)
            if merged:
                LOGGER.info(
                    "RTC transcription: participant=%s text=%r",
                    getattr(participant, "identity", ""),
                    merged,
                )

    async def _consume_remote_audio(self, track: rtc.RemoteAudioTrack, participant: object) -> None:
        if self._playback is None:
            return
        stream = rtc.AudioStream.from_track(
            track=track,
            sample_rate=TARGET_SAMPLE_RATE,
            num_channels=1,
            frame_size_ms=10,
        )
        try:
            async for event in stream:
                self._playback.push_frame(
                    event.frame,
                    source_identity=getattr(participant, "identity", ""),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception(
                "RTC audio consume failed: participant=%s sid=%s",
                getattr(participant, "identity", ""),
                getattr(track, "sid", ""),
            )
        finally:
            await stream.aclose()

    def _is_agent_identity(self, identity: str) -> bool:
        normalized = (identity or "").strip()
        return bool(normalized) and (
            normalized.startswith("agent-") or normalized == self._settings.agent.name
        )

    def _maybe_start_room_monitor(self) -> None:
        interval_s = self._config.agent_absence_check_interval_s
        if not self._config.auto_dispatch_agent or interval_s <= 0:
            return
        if self._monitor_task is not None and not self._monitor_task.done():
            return
        self._monitor_task = asyncio.create_task(self._monitor_agent_presence())

    def _schedule_redispatch(self, reason: str) -> None:
        if not self._config.auto_dispatch_agent:
            return
        if not self._config.auto_redispatch_on_agent_disconnect and reason != "agent-absence-monitor":
            return
        if not self._room.isconnected():
            return
        if self._agent_participants:
            return
        if self._redispatch_task is not None and not self._redispatch_task.done():
            return
        cooldown_s = max(0.0, self._config.redispatch_cooldown_s)
        now = time.monotonic()
        if now - self._last_redispatch_at < cooldown_s:
            LOGGER.info(
                "RTC redispatch skipped by cooldown: reason=%s remaining=%.1fs",
                reason,
                cooldown_s - (now - self._last_redispatch_at),
            )
            return
        self._redispatch_task = asyncio.create_task(self._redispatch_agent(reason))

    async def _monitor_agent_presence(self) -> None:
        interval_s = max(1.0, self._config.agent_absence_check_interval_s)
        try:
            while not self._done.is_set():
                await asyncio.sleep(interval_s)
                if self._done.is_set() or not self._room.isconnected():
                    continue
                if self._agent_participants:
                    continue
                LOGGER.info(
                    "RTC agent absence detected: room=%s identity=%s",
                    self._config.room_name,
                    self._config.identity,
                )
                self._schedule_redispatch("agent-absence-monitor")
        except asyncio.CancelledError:
            raise

    async def _redispatch_agent(self, reason: str) -> None:
        try:
            self._last_redispatch_at = time.monotonic()
            LOGGER.info(
                "RTC redispatch requested: room=%s reason=%s",
                self._config.room_name,
                reason,
            )
            await ensure_room_ready(
                self._settings,
                self._config.room_name,
                create_room=self._config.auto_create_room,
                dispatch_agent=True,
                dispatch_metadata=f"robot-rtc-endpoint-{reason}",
                replace_existing_dispatch=True,
            )
            LOGGER.info(
                "RTC redispatch completed: room=%s reason=%s",
                self._config.room_name,
                reason,
            )
        except Exception as exc:
            LOGGER.warning("RTC redispatch failed: reason=%s error=%s", reason, exc)
        finally:
            self._redispatch_task = None


async def _main_async() -> None:
    settings = load_settings()
    endpoint = RobotRtcEndpoint(settings.rtc_endpoint)
    try:
        await endpoint.run()
    finally:
        await endpoint.aclose()


def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.logging.level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    LOGGER.info(
        "RTC endpoint bootstrap: enabled=%s room=%s identity=%s",
        settings.rtc_endpoint.enabled,
        settings.rtc_endpoint.room_name,
        settings.rtc_endpoint.identity,
    )
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
