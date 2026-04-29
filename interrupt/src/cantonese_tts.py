from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

import edge_tts

from src.tts_mute_state import set_mute_remote_audio


LOGGER = logging.getLogger("interrupt.cantonese_tts")


@dataclass
class CantoneseTtsConfig:
    enabled: bool
    voice: str
    rate: str
    volume: str
    pitch: str
    playback_command: str
    keep_debug_audio: bool
    mute_remote_audio: bool
    mute_padding_s: float


class CantoneseTtsError(RuntimeError):
    pass


class EdgeCantoneseTts:
    def __init__(self, config: CantoneseTtsConfig) -> None:
        self._config = config

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def is_available(self) -> bool:
        if not self._config.enabled:
            return False
        if not shutil.which(self._resolve_playback_command()):
            LOGGER.warning(
                "Cantonese TTS playback command not found: %s",
                self._resolve_playback_command(),
            )
            return False
        return True

    def synthesize_and_play(self, text: str) -> bool:
        normalized = " ".join((text or "").split()).strip()
        if not normalized or not self.is_available():
            return False
        audio_path = asyncio.run(self._synthesize_to_file(normalized))
        try:
            duration_s = _probe_duration_seconds(audio_path)
            if self._config.mute_remote_audio:
                set_mute_remote_audio(
                    duration_s + self._config.mute_padding_s,
                    language="zh-YUE",
                )
            LOGGER.info(
                "Edge Cantonese TTS synthesized: voice=%s duration=%.2fs text=%r",
                self._config.voice,
                duration_s,
                normalized,
            )
            self._play_file(audio_path)
            return True
        finally:
            if not self._config.keep_debug_audio:
                with contextlib.suppress(OSError):
                    os.remove(audio_path)

    async def _synthesize_to_file(self, text: str) -> str:
        fd, temp_path = tempfile.mkstemp(prefix="interrupt-yue-tts-", suffix=".mp3")
        os.close(fd)
        communicate = edge_tts.Communicate(
            text=text,
            voice=self._config.voice,
            rate=self._config.rate,
            volume=self._config.volume,
            pitch=self._config.pitch,
        )
        try:
            await communicate.save(temp_path)
        except Exception as exc:  # pragma: no cover
            with contextlib.suppress(OSError):
                os.remove(temp_path)
            raise CantoneseTtsError(str(exc)) from exc
        return temp_path

    def _play_file(self, audio_path: str) -> None:
        command = self._resolve_playback_command()
        argv = [command, audio_path]
        if command == "ffplay":
            argv = [command, "-nodisp", "-autoexit", "-loglevel", "error", audio_path]
        elif command == "mpv":
            argv = [command, "--no-video", "--really-quiet", audio_path]
        elif command == "play":
            argv = [command, "-q", audio_path]
        elif command == "gst-play-1.0":
            argv = [command, "--quiet", audio_path]
        try:
            subprocess.run(
                argv,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise CantoneseTtsError(exc.stderr.strip() or str(exc)) from exc

    def _resolve_playback_command(self) -> str:
        requested = (self._config.playback_command or "").strip()
        if requested:
            return requested
        if shutil.which("mpg123"):
            return "mpg123"
        if shutil.which("ffplay"):
            return "ffplay"
        if shutil.which("mpv"):
            return "mpv"
        if shutil.which("gst-play-1.0"):
            return "gst-play-1.0"
        if shutil.which("play"):
            return "play"
        if shutil.which("paplay"):
            return "paplay"
        return "mpg123"


def load_cantonese_tts_config() -> CantoneseTtsConfig:
    return CantoneseTtsConfig(
        enabled=os.getenv("INTERRUPT_CANTONESE_TTS_ENABLED", "0").strip().lower()
        in {"1", "true", "yes", "on"},
        voice=os.getenv("INTERRUPT_CANTONESE_TTS_VOICE", "zh-HK-HiuGaaiNeural").strip()
        or "zh-HK-HiuGaaiNeural",
        rate=os.getenv("INTERRUPT_CANTONESE_TTS_RATE", "+0%").strip() or "+0%",
        volume=os.getenv("INTERRUPT_CANTONESE_TTS_VOLUME", "+0%").strip() or "+0%",
        pitch=os.getenv("INTERRUPT_CANTONESE_TTS_PITCH", "+0Hz").strip() or "+0Hz",
        playback_command=os.getenv("INTERRUPT_CANTONESE_TTS_PLAYBACK_COMMAND", "").strip(),
        keep_debug_audio=os.getenv("INTERRUPT_CANTONESE_TTS_KEEP_DEBUG_AUDIO", "0").strip().lower()
        in {"1", "true", "yes", "on"},
        mute_remote_audio=os.getenv("INTERRUPT_CANTONESE_TTS_MUTE_REMOTE_AUDIO", "1").strip().lower()
        in {"1", "true", "yes", "on"},
        mute_padding_s=float(
            os.getenv("INTERRUPT_CANTONESE_TTS_MUTE_PADDING_S", "0.35").strip() or "0.35"
        ),
    )


def _probe_duration_seconds(audio_path: str) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 3.0
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return 3.0
    try:
        return float((result.stdout or "").strip() or "3.0")
    except ValueError:
        return 3.0
