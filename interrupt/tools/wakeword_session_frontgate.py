#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import pty
import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.settings import load_environment, load_settings
from src.g1_om1_adapter import G1Om1Adapter
from src.speech_loop_guard import note_local_playback
from src.wakeword_runtime import WakeWordEvent, create_wake_word_gate


DEFAULT_FACTORY = "src.mock_wakeword:factory"
DEFAULT_WAKE_ACK = "我在，请稍等一下吧"
DEFAULT_INTRO_MANDARIN = (
    "你好！我是笨笨同学，中国移动环球智算中心的专属智能导览机器人。"
    "我可以用粤语、普通话和英文与您交流。今天很高兴在这里为您服务！"
    "如果您想了解数据中心的任何信息，随时告诉我哦。"
)
DEFAULT_INTRO_CANTONESE = (
    "你好！我係笨笨同學，中國移動環球智算中心嘅專屬智能導覽機械人。"
    "我可以用粵語、普通話同英文同您交流。今日好高興喺呢度為您服務！"
    "如果您想了解數據中心嘅任何資訊，隨時同我講哦。"
)
DEFAULT_INTRO_ENGLISH = (
    "Hello! I am Benben, the dedicated intelligent guide robot for China Mobile "
    "Global Intelligent Computing Center. I can talk with you in Cantonese, Mandarin, "
    "and English. I am very happy to serve you here today. If you would like to know "
    "anything about the data center, just let me know."
)
DEFAULT_ACTIVE_LED = "green"
DEFAULT_IDLE_LED = "blue"
DEFAULT_WAKE_RETRY_DELAY_S = 1.0
DEFAULT_WAKE_REOPEN_DELAY_S = 0.6
DEFAULT_SESSION_PROCESS_PATTERNS = (
    "python -m src.rtc_endpoint",
    "python -m src.agent start",
    "run_frontgate_room_session.sh",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Wakeword front gate that launches an interrupt realtime session command."
    )
    parser.add_argument(
        "--factory",
        default="",
        help="Wakeword factory in module:callable format. Defaults to config/env, then mock stdin factory.",
    )
    parser.add_argument(
        "--session-command",
        default=str(ROOT_DIR / "run_local_voice_agent.sh"),
        help="Shell-style command used to launch the realtime session after wake.",
    )
    parser.add_argument(
        "--session-timeout",
        type=float,
        default=0.0,
        help="Optional seconds to keep the session process alive. <=0 means wait until it exits naturally.",
    )
    parser.add_argument(
        "--wakeword",
        action="append",
        default=[],
        help="Wakeword override passed to compatible factories such as src.mock_wakeword:factory.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Exit after one wake -> session cycle.",
    )
    return parser


def _resolve_factory(cli_factory: str, settings_factory: str) -> str:
    candidate = (cli_factory or "").strip() or (settings_factory or "").strip()
    return candidate or DEFAULT_FACTORY


def _factory_fallback_enabled() -> bool:
    return _env_flag("INTERRUPT_FRONTGATE_ALLOW_FACTORY_FALLBACK", True)


def _fallback_factory(
    factory_spec: str,
    exc: Exception,
) -> str:
    fallback = os.getenv("INTERRUPT_FRONTGATE_FALLBACK_FACTORY", DEFAULT_FACTORY).strip() or DEFAULT_FACTORY
    if factory_spec == fallback or not _factory_fallback_enabled():
        raise exc
    print(
        "[FrontGate] wake factory unavailable, falling back "
        f"from {factory_spec} to {fallback}: {exc}",
        flush=True,
    )
    return fallback


def _build_gate_kwargs(args: argparse.Namespace) -> dict[str, object]:
    kwargs: dict[str, object] = {}
    if args.wakeword:
        kwargs["wakewords"] = tuple(args.wakeword)
    return kwargs


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _start_active_led(adapter: G1Om1Adapter) -> subprocess.Popen[bytes] | None:
    active_color = os.getenv("INTERRUPT_FRONTGATE_ACTIVE_LED", DEFAULT_ACTIVE_LED).strip() or DEFAULT_ACTIVE_LED
    command = [
        adapter.config.python_executable,
        adapter.config.feedback_script,
        "--interface",
        adapter.config.unitree_interface,
        "--mode",
        "breathe",
        "--color",
        active_color,
        "--period",
        os.getenv("INTERRUPT_FRONTGATE_ACTIVE_LED_PERIOD", "2.0").strip() or "2.0",
    ]
    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        print(
            f"[FrontGate] wake_led start failed color={active_color} error={exc}",
            flush=True,
        )
        return None
    print(
        f"[FrontGate] wake_led color={active_color} started pid={proc.pid}",
        flush=True,
    )
    return proc


def _wake_language(event: WakeWordEvent) -> str:
    metadata = getattr(event, "metadata", {}) or {}
    raw = str(metadata.get("language") or metadata.get("detected_lang") or "").strip().lower()
    if raw in {"yue", "zh-yue", "cantonese"}:
        return "zh-YUE"
    if raw in {"en", "en-us", "en-gb", "english"}:
        return "en"
    return "zh-CN"


def _wake_intro_text(event: WakeWordEvent) -> str:
    language = _wake_language(event)
    if language == "zh-YUE":
        return os.getenv("INTERRUPT_FRONTGATE_WAKE_INTRO_YUE", DEFAULT_INTRO_CANTONESE).strip() or DEFAULT_INTRO_CANTONESE
    if language == "en":
        return os.getenv("INTERRUPT_FRONTGATE_WAKE_INTRO_EN", DEFAULT_INTRO_ENGLISH).strip() or DEFAULT_INTRO_ENGLISH
    return os.getenv("INTERRUPT_FRONTGATE_WAKE_INTRO_ZH", DEFAULT_INTRO_MANDARIN).strip() or DEFAULT_INTRO_MANDARIN


def _local_wake_ack(
    adapter: G1Om1Adapter,
    event: WakeWordEvent,
) -> subprocess.Popen[bytes] | None:
    if not adapter.available:
        print("[FrontGate] local wake ack skipped: G1/OM1 adapter unavailable", flush=True)
        return None

    if _env_flag("INTERRUPT_FRONTGATE_ENABLE_WAKE_ACK", True):
        if _env_flag("INTERRUPT_FRONTGATE_ENABLE_WAKE_INTRO", False):
            reply = _wake_intro_text(event)
        else:
            reply = os.getenv("INTERRUPT_FRONTGATE_WAKE_ACK_TEXT", DEFAULT_WAKE_ACK).strip() or DEFAULT_WAKE_ACK
        speak_result = adapter.speak(reply)
        if speak_result.ok:
            note_local_playback(reply, language=_wake_language(event))
        print(
            f"[FrontGate] wake_ack wakeword={event.wakeword} reply={reply} ok={speak_result.ok} stdout={speak_result.stdout!r} stderr={speak_result.stderr!r}",
            flush=True,
        )

    if _env_flag("INTERRUPT_FRONTGATE_ENABLE_WAKE_LED", True):
        return _start_active_led(adapter)
    return None


def _restore_idle_led(
    adapter: G1Om1Adapter,
    active_led_proc: subprocess.Popen[bytes] | None,
) -> None:
    if active_led_proc is not None and active_led_proc.poll() is None:
        active_led_proc.terminate()
        try:
            active_led_proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            active_led_proc.kill()
            active_led_proc.wait()
        print(f"[FrontGate] wake_led stopped pid={active_led_proc.pid}", flush=True)

    if not adapter.available or not _env_flag("INTERRUPT_FRONTGATE_RESTORE_IDLE_LED", True):
        return
    idle_color = os.getenv("INTERRUPT_FRONTGATE_IDLE_LED", DEFAULT_IDLE_LED).strip() or DEFAULT_IDLE_LED
    led_result = adapter.set_led(idle_color)
    print(
        f"[FrontGate] idle_led color={idle_color} ok={led_result.ok} stdout={led_result.stdout!r} stderr={led_result.stderr!r}",
        flush=True,
    )


def _set_idle_led_on_start(adapter: G1Om1Adapter) -> None:
    if not adapter.available or not _env_flag("INTERRUPT_FRONTGATE_SET_IDLE_LED_ON_START", True):
        return
    _stop_stale_breathe_led(adapter)
    idle_color = os.getenv("INTERRUPT_FRONTGATE_IDLE_LED", DEFAULT_IDLE_LED).strip() or DEFAULT_IDLE_LED
    led_result = adapter.set_led(idle_color)
    print(
        f"[FrontGate] startup_idle_led color={idle_color} ok={led_result.ok} stdout={led_result.stdout!r} stderr={led_result.stderr!r}",
        flush=True,
    )


def _stop_stale_breathe_led(adapter: G1Om1Adapter) -> None:
    script_name = os.path.basename(adapter.config.feedback_script)
    try:
        result = subprocess.run(
            ["pkill", "-f", f"{script_name} --interface {adapter.config.unitree_interface} --mode breathe"],
            check=False,
            text=True,
            capture_output=True,
        )
        print(
            f"[FrontGate] stop_stale_breathe_led rc={result.returncode}",
            flush=True,
        )
    except Exception as exc:
        print(f"[FrontGate] stop_stale_breathe_led error={exc}", flush=True)


def _launch_session(
    session_command: str,
    event: WakeWordEvent,
    *,
    timeout_s: float,
) -> int:
    _wait_for_console_input_device()
    command = shlex.split(session_command)
    env = os.environ.copy()
    env["INTERRUPT_WAKE_EVENT_WAKEWORD"] = event.wakeword
    env["INTERRUPT_WAKE_EVENT_TEXT"] = event.text
    print(f"[FrontGate] session_cmd={' '.join(command)}", flush=True)
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        command,
        env=env,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        start_new_session=True,
        close_fds=True,
    )
    os.close(slave_fd)

    def _relay_pty_output() -> None:
        while True:
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            try:
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
            except BrokenPipeError:
                break

    relay_thread = threading.Thread(target=_relay_pty_output, daemon=True)
    relay_thread.start()
    try:
        if timeout_s > 0:
            proc.wait(timeout=timeout_s)
        else:
            proc.wait()
    except subprocess.TimeoutExpired:
        print(
            f"[FrontGate] session timeout after {timeout_s:.1f}s, terminating session",
            flush=True,
        )
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
    except KeyboardInterrupt:
        print("[FrontGate] interrupted while session was running, forwarding signal", flush=True)
        os.killpg(proc.pid, signal.SIGINT)
        proc.wait()
        raise
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass
    return int(proc.returncode or 0)


def _wait_for_console_input_device() -> None:
    target_device = os.getenv("INTERRUPT_INPUT_DEVICE", "").strip()
    substring = os.getenv("INTERRUPT_FRONTGATE_WAIT_FOR_INPUT_DEVICE_SUBSTRING", "").strip()
    if not target_device and not substring:
        return

    timeout_s = float(os.getenv("INTERRUPT_FRONTGATE_WAIT_FOR_INPUT_DEVICE_TIMEOUT", "3.0").strip() or "3.0")
    poll_s = float(os.getenv("INTERRUPT_FRONTGATE_WAIT_FOR_INPUT_DEVICE_POLL", "0.2").strip() or "0.2")
    probe_ms = int(os.getenv("INTERRUPT_FRONTGATE_INPUT_DEVICE_PROBE_MS", "600").strip() or "600")
    min_callbacks = int(
        os.getenv("INTERRUPT_FRONTGATE_INPUT_DEVICE_MIN_CALLBACKS", "3").strip() or "3"
    )
    ready_delay_s = float(
        os.getenv("INTERRUPT_FRONTGATE_INPUT_DEVICE_READY_DELAY", "0.35").strip() or "0.35"
    )
    python_exe = ROOT_DIR / ".venv" / "bin" / "python"
    if not python_exe.exists():
        print(
            f"[FrontGate] device_wait skipped: missing python={python_exe}",
            flush=True,
        )
        return

    deadline = time.monotonic() + max(0.1, timeout_s)
    script = """
import sys
import sounddevice as sd

target = sys.argv[1].strip()
needle = sys.argv[2].strip().casefold()
probe_ms = max(100, int(sys.argv[3]))
min_callbacks = max(1, int(sys.argv[4]))

device = None
if target:
    device = int(target) if target.lstrip("-").isdigit() else target
elif needle:
    for index, info in enumerate(sd.query_devices()):
        if int(info.get("max_input_channels", 0) or 0) <= 0:
            continue
        if needle in str(info.get("name", "")).casefold():
            device = index
            break

if device is None:
    print("missing-device")
    raise SystemExit(2)

info = sd.query_devices(device, kind="input")
channels = max(1, min(int(info.get("max_input_channels", 1) or 1), 2))
samplerate = int(round(float(info.get("default_samplerate", 44100.0))))
callbacks = {"count": 0}

def cb(indata, frames, time_info, status):
    callbacks["count"] += 1

with sd.InputStream(
    device=device,
    channels=channels,
    samplerate=samplerate,
    dtype="int16",
    blocksize=max(240, samplerate // 100),
    callback=cb,
):
    sd.sleep(probe_ms)

count = callbacks["count"]
name = str(info.get("name", "unknown")).replace("\\n", " ")
if count >= min_callbacks:
    print(f"ready callbacks={count} device={device!r} name={name} sr={samplerate}")
    raise SystemExit(0)

print(f"not-ready callbacks={count} device={device!r} name={name} sr={samplerate}")
raise SystemExit(3)
""".strip()

    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                str(python_exe),
                "-c",
                script,
                target_device,
                substring,
                str(probe_ms),
                str(min_callbacks),
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        details = result.stdout.strip() or result.stderr.strip() or f"rc={result.returncode}"
        if result.returncode == 0:
            print(
                f"[FrontGate] device_wait ready target={target_device!r} substring={substring!r} details={details}",
                flush=True,
            )
            if ready_delay_s > 0:
                time.sleep(ready_delay_s)
            return
        time.sleep(max(0.05, poll_s))

    print(
        f"[FrontGate] device_wait timeout target={target_device!r} substring={substring!r}, launching session anyway",
        flush=True,
    )


def _wait_for_wake_capture_device_release() -> None:
    delay_s = float(
        os.getenv(
            "INTERRUPT_FRONTGATE_WAKE_REOPEN_DELAY_S",
            str(DEFAULT_WAKE_REOPEN_DELAY_S),
        ).strip()
        or str(DEFAULT_WAKE_REOPEN_DELAY_S)
    )
    if delay_s > 0:
        time.sleep(delay_s)
    _wait_for_session_process_release()
    _wait_for_console_input_device()


def _wait_for_session_process_release() -> None:
    timeout_s = float(
        os.getenv("INTERRUPT_FRONTGATE_SESSION_PROCESS_RELEASE_TIMEOUT_S", "8.0").strip() or "8.0"
    )
    poll_s = float(
        os.getenv("INTERRUPT_FRONTGATE_SESSION_PROCESS_RELEASE_POLL_S", "0.2").strip() or "0.2"
    )
    raw_patterns = os.getenv(
        "INTERRUPT_FRONTGATE_SESSION_PROCESS_PATTERNS",
        "\n".join(DEFAULT_SESSION_PROCESS_PATTERNS),
    )
    patterns = [item.strip() for item in raw_patterns.splitlines() if item.strip()]
    if not patterns:
        return

    deadline = time.monotonic() + max(0.1, timeout_s)
    last_busy: list[str] = []
    while time.monotonic() < deadline:
        busy: list[str] = []
        for pattern in patterns:
            result = subprocess.run(
                ["pgrep", "-af", pattern],
                check=False,
                text=True,
                capture_output=True,
            )
            lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
            if lines:
                busy.append(f"{pattern}({len(lines)})")
        if not busy:
            if last_busy:
                print(
                    "[FrontGate] session_process_release ready "
                    f"previously_busy={','.join(last_busy)}",
                    flush=True,
                )
            return
        last_busy = busy
        time.sleep(max(0.05, poll_s))

    print(
        "[FrontGate] session_process_release timeout "
        f"busy={','.join(last_busy) or 'unknown'}",
        flush=True,
    )


def main() -> int:
    load_environment()
    settings = load_settings(ROOT_DIR / "config.yaml")
    args = build_parser().parse_args()
    adapter = G1Om1Adapter()

    factory_spec = _resolve_factory(args.factory, settings.integrations.wake_word_factory)
    gate_kwargs = _build_gate_kwargs(args)
    print(f"[FrontGate] factory={factory_spec}", flush=True)
    print(f"[FrontGate] session_command={args.session_command}", flush=True)
    if args.session_timeout > 0:
        print(f"[FrontGate] session_timeout={args.session_timeout:.1f}s", flush=True)

    _set_idle_led_on_start(adapter)
    retry_delay_s = float(
        os.getenv("INTERRUPT_FRONTGATE_WAKE_RETRY_DELAY_S", str(DEFAULT_WAKE_RETRY_DELAY_S)).strip()
        or str(DEFAULT_WAKE_RETRY_DELAY_S)
    )
    active_factory = factory_spec
    gate = None
    try:
        while True:
            if gate is None:
                try:
                    gate = create_wake_word_gate(active_factory, settings=settings, **gate_kwargs)
                except Exception as exc:
                    fallback_factory = _fallback_factory(active_factory, exc)
                    active_factory = fallback_factory
                    gate = create_wake_word_gate(active_factory, settings=settings, **gate_kwargs)
            try:
                event = gate.wait_for_wake()
            except RuntimeError as exc:
                print(f"[FrontGate] wake gate runtime error: {exc}", flush=True)
                gate.close()
                gate = None
                time.sleep(max(0.1, retry_delay_s))
                continue
            if event is None:
                print("[FrontGate] wake gate closed", flush=True)
                return 0
            print(
                f"[FrontGate] wake_detected wakeword={event.wakeword} text={event.text}",
                flush=True,
            )
            active_led_proc = _local_wake_ack(adapter, event)
            returncode = _launch_session(
                args.session_command,
                event,
                timeout_s=args.session_timeout,
            )
            print(f"[FrontGate] session_exit returncode={returncode}", flush=True)
            _restore_idle_led(adapter, active_led_proc)
            gate.close()
            gate = None
            _wait_for_wake_capture_device_release()
            if args.once:
                return returncode
    finally:
        if gate is not None:
            gate.close()


if __name__ == "__main__":
    raise SystemExit(main())
