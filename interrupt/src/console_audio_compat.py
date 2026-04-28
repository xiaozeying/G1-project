from __future__ import annotations

import logging
import os
import threading
import time as pytime

import numpy as np
from livekit import rtc


LOGGER = logging.getLogger("interrupt.console_audio_compat")
TARGET_SAMPLE_RATE = 24000
TARGET_FRAME_SAMPLES = 240


def _resample_i16(samples: np.ndarray, input_sr: int, output_sr: int) -> np.ndarray:
    if samples.size == 0:
        return samples.astype(np.int16, copy=False)
    if input_sr == output_sr:
        return samples.astype(np.int16, copy=False)

    src = samples.astype(np.float32, copy=False)
    out_count = max(1, int(round(src.size * output_sr / float(input_sr))))
    src_x = np.linspace(0.0, src.size - 1.0, num=src.size, dtype=np.float32)
    dst_x = np.linspace(0.0, src.size - 1.0, num=out_count, dtype=np.float32)
    resampled = np.interp(dst_x, src_x, src).astype(np.int16)
    return resampled


def apply_console_audio_compat_patch() -> None:
    if os.getenv("INTERRUPT_DISABLE_CONSOLE_AUDIO_COMPAT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return

    from livekit.agents.cli import cli as lk_cli
    import sounddevice as sd

    if getattr(lk_cli.AgentsConsole, "_interrupt_audio_compat_patched", False):
        return

    def _close_input_stream(self) -> None:
        stream = getattr(self, "_input_stream", None)
        if stream is None:
            return
        try:
            try:
                stream.abort()
            except Exception:
                pass
            try:
                stream.stop()
            except Exception:
                pass
            stream.close()
        except Exception:
            LOGGER.exception(
                "console audio compat close input stream failed: device=%s",
                getattr(self, "_input_name", "unknown"),
            )
        finally:
            self._input_stream = None

    def _open_input_stream(self) -> None:
        device = getattr(self, "_compat_input_device", None)
        self._compat_frame_buffer = np.empty(0, dtype=np.int16)
        self._compat_last_log_at = 0.0
        self._compat_callback_count = 0
        self._compat_pushed_frames = 0
        self._compat_last_callback_monotonic = pytime.monotonic()
        self._compat_last_push_monotonic = self._compat_last_callback_monotonic
        self._input_stream = sd.InputStream(
            callback=self._sd_input_callback,
            dtype="int16",
            channels=self._compat_input_channels,
            device=device,
            samplerate=self._compat_input_sr,
            blocksize=max(TARGET_FRAME_SAMPLES, self._compat_input_sr // 100),
        )
        self._input_stream.start()

    def _restart_input_stream(self, reason: str) -> None:
        if getattr(self, "_compat_input_restarting", False):
            return
        self._compat_input_restarting = True
        try:
            LOGGER.warning(
                "console audio compat restarting input stream: reason=%s device=%s callbacks=%s pushed_frames=%s restarts=%s",
                reason,
                getattr(self, "_input_name", "unknown"),
                getattr(self, "_compat_callback_count", 0),
                getattr(self, "_compat_pushed_frames", 0),
                getattr(self, "_compat_input_restart_count", 0),
            )
            _close_input_stream(self)
            pytime.sleep(
                float(os.getenv("INTERRUPT_CONSOLE_INPUT_RESTART_DELAY_S", "0.15").strip() or "0.15")
            )
            _open_input_stream(self)
            self._compat_input_restart_count = getattr(self, "_compat_input_restart_count", 0) + 1
            LOGGER.info(
                "console audio compat input stream restarted: device=%s restarts=%s",
                getattr(self, "_input_name", "unknown"),
                getattr(self, "_compat_input_restart_count", 0),
            )
        except Exception:
            LOGGER.exception(
                "console audio compat input stream restart failed: device=%s",
                getattr(self, "_input_name", "unknown"),
            )
        finally:
            self._compat_input_restarting = False

    def _ensure_input_watchdog(self) -> None:
        thread = getattr(self, "_compat_input_watchdog_thread", None)
        if thread is not None and thread.is_alive():
            return

        stop_event = threading.Event()
        self._compat_input_watchdog_stop = stop_event

        def _watchdog() -> None:
            stall_s = float(os.getenv("INTERRUPT_CONSOLE_INPUT_STALL_S", "2.5").strip() or "2.5")
            poll_s = float(
                os.getenv("INTERRUPT_CONSOLE_INPUT_WATCHDOG_POLL_S", "0.5").strip() or "0.5"
            )
            while not stop_event.wait(max(0.2, poll_s)):
                if not getattr(self, "_io_acquired", False):
                    continue
                if getattr(self, "_compat_input_restarting", False):
                    continue
                stream = getattr(self, "_input_stream", None)
                if stream is None:
                    continue
                if not getattr(stream, "active", True):
                    _restart_input_stream(self, "stream_inactive")
                    continue
                callback_count = int(getattr(self, "_compat_callback_count", 0))
                if callback_count <= 0:
                    continue
                last_callback_at = float(getattr(self, "_compat_last_callback_monotonic", 0.0))
                if pytime.monotonic() - last_callback_at < stall_s:
                    last_push_at = float(
                        getattr(self, "_compat_last_push_monotonic", last_callback_at)
                    )
                    if pytime.monotonic() - last_push_at < stall_s:
                        continue
                    _restart_input_stream(self, "push_stalled")
                    continue
                _restart_input_stream(self, "callback_stalled")

        self._compat_input_watchdog_thread = threading.Thread(
            target=_watchdog,
            name="interrupt-console-input-watchdog",
            daemon=True,
        )
        self._compat_input_watchdog_thread.start()

    def _set_microphone_enabled(self, enable: bool, *, device: int | str | None = None) -> None:
        stop_event = getattr(self, "_compat_input_watchdog_stop", None)
        if stop_event is not None:
            stop_event.set()
            self._compat_input_watchdog_stop = None

        if self._input_stream:
            _close_input_stream(self)
            self._input_name = None

        if not enable:
            return

        if device is None:
            device, _ = sd.default.device

        try:
            device_info = sd.query_devices(device, kind="input")
        except Exception:
            raise lk_cli.CLIError(
                "Unable to access the microphone. \n"
                "Please ensure a microphone is connected and recognized by your system. "
                "To see available input devices, run: lk-agents console --list-devices"
            ) from None

        assert isinstance(device_info, dict), "device_info is dict"

        self._input_name = device_info.get("name", "Unnamed microphone")
        self._compat_input_device = device
        self._compat_input_sr = int(round(float(device_info.get("default_samplerate", 44100.0))))
        self._compat_input_channels = max(
            1,
            min(
                int(device_info.get("max_input_channels", 1) or 1),
                int(os.getenv("INTERRUPT_CONSOLE_MAX_INPUT_CHANNELS", "2")),
            ),
        )
        self._compat_input_restarting = False
        self._compat_input_restart_count = 0
        LOGGER.info(
            "console audio compat input configured: device=%s sr=%s channels=%s",
            self._input_name,
            self._compat_input_sr,
            self._compat_input_channels,
        )
        _open_input_stream(self)
        _ensure_input_watchdog(self)

    def _sd_input_callback(self, indata: np.ndarray, frame_count: int, time, *_: object) -> None:
        try:
            self._compat_callback_count = getattr(self, "_compat_callback_count", 0) + 1
            self._compat_last_callback_monotonic = pytime.monotonic()
            self._input_delay = time.currentTime - time.inputBufferAdcTime
            total_delay = self._output_delay + self._input_delay

            try:
                self._apm.set_stream_delay_ms(int(total_delay * 1000))
            except RuntimeError:
                pass

            if indata.ndim == 1:
                mono = indata.astype(np.int16, copy=False)
            elif indata.shape[1] == 1:
                mono = indata[:, 0].astype(np.int16, copy=False)
            else:
                mono = np.mean(indata.astype(np.float32), axis=1).astype(np.int16)

            input_rms = float(np.sqrt(np.mean(mono.astype(np.float32) ** 2))) if mono.size else 0.0
            mono = _resample_i16(
                mono,
                getattr(self, "_compat_input_sr", TARGET_SAMPLE_RATE),
                TARGET_SAMPLE_RATE,
            )
            if mono.size == 0:
                return

            sr = TARGET_SAMPLE_RATE
            x = mono.astype(np.float32) / 32768.0
            n = x.size
            x *= np.hanning(n).astype(np.float32)

            X = np.fft.rfft(x, n=n)
            mag = np.abs(X).astype(np.float32) * (2.0 / n)
            mag[0] *= 0.5
            mag[-1] *= 1.0 - 0.5 * float(n % 2 == 0)

            freqs = np.fft.rfftfreq(n, d=1.0 / sr)
            nb = len(self._input_levels)
            edges = np.geomspace(20.0, (sr * 0.5) * 0.96, nb + 1).astype(np.float32)
            b = np.clip(np.digitize(freqs, edges) - 1, 0, nb - 1)

            p = (mag * mag).astype(np.float32)
            sump = np.bincount(b, weights=p, minlength=nb)
            cnts = np.maximum(np.bincount(b, minlength=nb), 1)
            pmean = sump / cnts

            db = 10.0 * np.log10(pmean + 1e-12)
            floor_db, hot_db = -70.0, -20
            lev = np.clip(((db - floor_db) / (hot_db - floor_db)).astype(np.float32), 0.0, 1.0)
            lev = np.maximum(lev**0.75 - 0.02, 0.0)
            peak = float(lev.max())
            lev *= np.clip(0.95 / (peak + 1e-6), 0.0, 3.0)
            lev = np.clip(lev, 0.0, 1.0)

            decay = float(np.exp(-(n / sr) / 0.1))
            with self._input_lock:
                prev = self._input_levels.astype(np.float32)
                self._input_levels = np.maximum(lev, prev * decay)

            now = float(getattr(time, "currentTime", 0.0))
            last_log_at = float(getattr(self, "_compat_last_log_at", 0.0))
            if now - last_log_at >= 2.0:
                LOGGER.info(
                    "console audio compat callback: device=%s callbacks=%s frame_count=%s input_rms=%.1f resampled=%s io_acquired=%s pushed_frames=%s",
                    getattr(self, "_input_name", "unknown"),
                    getattr(self, "_compat_callback_count", 0),
                    frame_count,
                    input_rms,
                    mono.size,
                    self._io_acquired,
                    getattr(self, "_compat_pushed_frames", 0),
                )
                self._compat_last_log_at = now

            if not self._io_acquired:
                return

            buffered = np.concatenate((getattr(self, "_compat_frame_buffer", np.empty(0, dtype=np.int16)), mono))
            full_frames = buffered.size // TARGET_FRAME_SAMPLES
            if full_frames <= 0:
                self._compat_frame_buffer = buffered
                return

            self._compat_frame_buffer = buffered[full_frames * TARGET_FRAME_SAMPLES :]

            for i in range(full_frames):
                start = i * TARGET_FRAME_SAMPLES
                end = start + TARGET_FRAME_SAMPLES
                capture_chunk = buffered[start:end]

                frame = rtc.AudioFrame(
                    data=capture_chunk.tobytes(),
                    samples_per_channel=TARGET_FRAME_SAMPLES,
                    sample_rate=TARGET_SAMPLE_RATE,
                    num_channels=1,
                )
                self._apm.process_stream(frame)

                in_data_aec = np.frombuffer(frame.data, dtype=np.int16)
                rms = np.sqrt(np.mean(in_data_aec.astype(np.float32) ** 2))
                max_int16 = np.iinfo(np.int16).max
                self._micro_db = 20.0 * np.log10(rms / max_int16 + 1e-6)

                self._io_loop.call_soon_threadsafe(self._io_audio_input.push_frame, frame)
                self._compat_pushed_frames = getattr(self, "_compat_pushed_frames", 0) + 1
                self._compat_last_push_monotonic = pytime.monotonic()
        except Exception:
            LOGGER.exception(
                "console audio compat input callback failed: device=%s callbacks=%s pushed_frames=%s",
                getattr(self, "_input_name", "unknown"),
                getattr(self, "_compat_callback_count", 0),
                getattr(self, "_compat_pushed_frames", 0),
            )

    def _set_speaker_enabled(self, enable: bool, *, device: int | str | None = None) -> None:
        if self._output_stream:
            self._output_stream.close()
            self._output_stream = self._output_name = None

        if not enable:
            return

        if device is None:
            _, device = sd.default.device

        try:
            device_info = sd.query_devices(device, kind="output")
        except Exception:
            raise lk_cli.CLIError(
                "Unable to access the speaker. \n"
                "Please ensure a speaker is connected and recognized by your system. "
                "To see available output devices, run: lk-agents console --list-devices"
            ) from None

        assert isinstance(device_info, dict), "device_info is dict"

        self._output_name = device_info.get("name", "Unnamed speaker")
        self._compat_output_sr = int(round(float(device_info.get("default_samplerate", 44100.0))))
        self._compat_output_channels = max(
            1,
            min(
                int(device_info.get("max_output_channels", 1) or 1),
                int(os.getenv("INTERRUPT_CONSOLE_MAX_OUTPUT_CHANNELS", "2")),
            ),
        )
        self._compat_output_last_log_at = 0.0
        self._compat_output_callbacks = 0
        self._compat_output_rendered_frames = 0
        self._output_stream = sd.OutputStream(
            callback=self._sd_output_callback,
            dtype="int16",
            channels=self._compat_output_channels,
            device=device,
            samplerate=self._compat_output_sr,
            blocksize=max(TARGET_FRAME_SAMPLES, self._compat_output_sr // 100),
        )
        LOGGER.info(
            "console audio compat output configured: device=%s sr=%s channels=%s",
            self._output_name,
            self._compat_output_sr,
            self._compat_output_channels,
        )
        self._output_stream.start()

    def _sd_output_callback(self, outdata: np.ndarray, frames: int, time, *_: object) -> None:
        if not self.io_acquired:
            outdata[:] = 0
            return

        self._compat_output_callbacks = getattr(self, "_compat_output_callbacks", 0) + 1
        self._output_delay = time.outputBufferDacTime - time.currentTime
        output_sr = getattr(self, "_compat_output_sr", TARGET_SAMPLE_RATE)
        output_channels = getattr(self, "_compat_output_channels", 1)

        with self._io_audio_output.audio_lock:
            if self._io_audio_output.paused:
                outdata[:] = 0
                source_chunk = np.empty(0, dtype=np.int16)
            else:
                needed_src = max(1, int(np.ceil(frames * TARGET_SAMPLE_RATE / float(output_sr))))
                available_samples = len(self._io_audio_output.audio_buffer) // 2
                consume_samples = min(available_samples, needed_src)
                if consume_samples > 0:
                    self._io_audio_output._maybe_mark_playback_started()
                    chunk = self._io_audio_output.audio_buffer[: consume_samples * 2]
                    source_chunk = np.frombuffer(chunk, dtype=np.int16, count=consume_samples).copy()
                    del self._io_audio_output.audio_buffer[: consume_samples * 2]
                else:
                    source_chunk = np.empty(0, dtype=np.int16)
                    self.io_loop.call_soon_threadsafe(self._io_audio_output.mark_output_empty)

        if source_chunk.size > 0:
            rendered = _resample_i16(source_chunk, TARGET_SAMPLE_RATE, output_sr)
        else:
            rendered = np.empty(0, dtype=np.int16)

        outdata[:] = 0
        write_frames = min(frames, rendered.size)
        if write_frames > 0:
            if outdata.ndim == 1:
                outdata[:write_frames] = rendered[:write_frames]
            else:
                mono = rendered[:write_frames]
                tiled = np.repeat(mono[:, None], output_channels, axis=1)
                outdata[:write_frames, :output_channels] = tiled
            self._compat_output_rendered_frames = getattr(self, "_compat_output_rendered_frames", 0) + write_frames

        if source_chunk.size > 0:
            num_chunks = source_chunk.size // TARGET_FRAME_SAMPLES
            for i in range(num_chunks):
                start = i * TARGET_FRAME_SAMPLES
                end = start + TARGET_FRAME_SAMPLES
                render_chunk = source_chunk[start:end]
                render_frame_for_aec = rtc.AudioFrame(
                    data=render_chunk.tobytes(),
                    samples_per_channel=TARGET_FRAME_SAMPLES,
                    sample_rate=TARGET_SAMPLE_RATE,
                    num_channels=1,
                )
                self._apm.process_reverse_stream(render_frame_for_aec)

        now = float(getattr(time, "currentTime", 0.0))
        last_log_at = float(getattr(self, "_compat_output_last_log_at", 0.0))
        if now - last_log_at >= 2.0:
            LOGGER.info(
                "console audio compat output callback: device=%s callbacks=%s frames=%s rendered=%s source=%s",
                getattr(self, "_output_name", "unknown"),
                getattr(self, "_compat_output_callbacks", 0),
                frames,
                getattr(self, "_compat_output_rendered_frames", 0),
                source_chunk.size,
            )
            self._compat_output_last_log_at = now

    lk_cli.AgentsConsole.set_microphone_enabled = _set_microphone_enabled
    lk_cli.AgentsConsole.set_speaker_enabled = _set_speaker_enabled
    lk_cli.AgentsConsole._sd_input_callback = _sd_input_callback
    lk_cli.AgentsConsole._sd_output_callback = _sd_output_callback
    lk_cli.AgentsConsole._interrupt_audio_compat_patched = True
    LOGGER.info("applied console audio compatibility patch")
