#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import signal
import shlex
import subprocess
import sys
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.livekit_room import ensure_room_ready, list_room_participants
from src.g1_om1_adapter import G1Om1Adapter
from src.settings import load_environment, load_settings


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ensure the robot LiveKit room session is available for frontgate wake flows.",
    )
    parser.add_argument(
        "--room-agent-command",
        default=os.getenv(
            "INTERRUPT_FRONTGATE_ROOM_AGENT_COMMAND",
            str(ROOT_DIR / "run_room_agent.sh"),
        ),
        help="Command used to start the room agent if it is not already running.",
    )
    parser.add_argument(
        "--room-agent-pattern",
        default=os.getenv(
            "INTERRUPT_FRONTGATE_ROOM_AGENT_PATTERN",
            "python -m src.agent start",
        ),
        help="pgrep -f pattern used to detect a running room agent process.",
    )
    parser.add_argument(
        "--rtc-endpoint-command",
        default=os.getenv(
            "INTERRUPT_FRONTGATE_RTC_ENDPOINT_COMMAND",
            str(ROOT_DIR / "run_robot_rtc_endpoint.sh"),
        ),
        help="Command used to start the robot rtc endpoint if it is not already running.",
    )
    parser.add_argument(
        "--rtc-endpoint-pattern",
        default=os.getenv(
            "INTERRUPT_FRONTGATE_RTC_ENDPOINT_PATTERN",
            "python -m src.rtc_endpoint",
        ),
        help="pgrep -f pattern used to detect a running robot rtc endpoint process.",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=float(
            os.getenv("INTERRUPT_FRONTGATE_ROOM_STARTUP_TIMEOUT_S", "30").strip() or "30"
        ),
        help="Seconds to wait for an agent participant to join after dispatch.",
    )
    parser.add_argument(
        "--pre-dispatch-delay",
        type=float,
        default=float(
            os.getenv("INTERRUPT_FRONTGATE_ROOM_PRE_DISPATCH_DELAY_S", "0").strip() or "0"
        ),
        help="Seconds to wait after starting managed processes before dispatching the agent.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(
            os.getenv("INTERRUPT_FRONTGATE_ROOM_POLL_INTERVAL_S", "1.0").strip() or "1.0"
        ),
        help="Polling interval in seconds while monitoring room participants.",
    )
    parser.add_argument(
        "--idle-grace",
        type=float,
        default=float(
            os.getenv("INTERRUPT_FRONTGATE_ROOM_IDLE_GRACE_S", "5.0").strip() or "5.0"
        ),
        help="How long the room can stay without an agent participant before the session exits.",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=float(
            os.getenv("INTERRUPT_FRONTGATE_ROOM_MAX_DURATION_S", "0").strip() or "0"
        ),
        help="Hard cap for one frontgate room session. <=0 disables the cap.",
    )
    parser.add_argument(
        "--session-exit-signal-file",
        default=os.getenv(
            "INTERRUPT_FRONTGATE_SESSION_EXIT_SIGNAL_FILE",
            "/tmp/interrupt_frontgate_room_exit.signal",
        ),
        help="Local file used by the room agent to signal that the frontgate session should exit.",
    )
    return parser


def _is_process_running(pattern: str) -> bool:
    result = subprocess.run(
        ["pgrep", "-af", pattern],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return False
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return bool(lines)


def _terminate_matching_processes(name: str, pattern: str) -> None:
    result = subprocess.run(
        ["pgrep", "-af", pattern],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return
    for raw_line in (result.stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        pid_text = line.split(None, 1)[0]
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            continue
        print(
            f"[FrontGateRoom] stopping stale {name}: pid={pid} pgid={pgid} pattern={pattern!r}",
            flush=True,
        )
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not _is_process_running(pattern):
                break
            time.sleep(0.2)
        if _is_process_running(pattern):
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _ensure_process_running(name: str, pattern: str, command: str) -> subprocess.Popen[bytes] | None:
    if _is_process_running(pattern):
        _terminate_matching_processes(name, pattern)
    argv = shlex.split(command)
    print(f"[FrontGateRoom] starting {name}: {' '.join(argv)}", flush=True)
    return subprocess.Popen(
        argv,
        cwd=str(ROOT_DIR),
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def _terminate_started_processes(processes: list[tuple[str, subprocess.Popen[bytes]]]) -> None:
    if not _env_flag("INTERRUPT_FRONTGATE_STOP_MANAGED_PROCESSES_ON_EXIT", True):
        return
    for name, proc in reversed(processes):
        if proc.poll() is not None:
            continue
        print(f"[FrontGateRoom] stopping managed {name}: pid={proc.pid}", flush=True)
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()


def _log_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _log_contains_since(path: Path, marker: str, offset: int) -> bool:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            handle.seek(max(0, offset))
            return marker in handle.read()
    except FileNotFoundError:
        return False


async def _wait_for_managed_process_readiness(
    *,
    room_agent_started: bool,
    rtc_endpoint_started: bool,
    room_agent_offset: int,
    rtc_offset: int,
    timeout_s: float,
    poll_s: float,
) -> bool:
    room_agent_log = ROOT_DIR / "logs" / "room-agent.log"
    rtc_log = ROOT_DIR / "logs" / "robot-rtc-endpoint.log"

    # Let newly started processes write their run headers before we begin polling.
    await asyncio.sleep(min(0.3, max(0.0, poll_s)))
    deadline = time.monotonic() + max(0.2, timeout_s)
    room_agent_ready = not room_agent_started
    rtc_ready = not rtc_endpoint_started
    while time.monotonic() < deadline:
        if room_agent_started and not room_agent_ready:
            room_agent_ready = _log_contains_since(
                room_agent_log,
                "registered worker",
                room_agent_offset,
            )
        if rtc_endpoint_started and not rtc_ready:
            rtc_ready = (
                _log_contains_since(
                    rtc_log,
                    "RTC endpoint connected:",
                    rtc_offset,
                )
                or _log_contains_since(
                    rtc_log,
                    "RTC endpoint bootstrap:",
                    rtc_offset,
                )
                or _log_contains_since(
                    rtc_log,
                    "RTC endpoint microphone started:",
                    rtc_offset,
                )
            )
        if room_agent_ready and rtc_ready:
            print(
                f"[FrontGateRoom] managed readiness room-agent={room_agent_ready} rtc-endpoint={rtc_ready}",
                flush=True,
            )
            return True
        await asyncio.sleep(max(0.1, poll_s))
    print(
        f"[FrontGateRoom] managed readiness timeout room-agent={room_agent_ready} rtc-endpoint={rtc_ready}",
        flush=True,
    )
    return room_agent_ready and rtc_ready

def _agent_identity(identity: str, agent_name: str) -> bool:
    normalized = (identity or "").strip()
    return bool(normalized) and (
        normalized.startswith("agent-") or normalized == agent_name
    )


def _speak_room_ready(adapter: G1Om1Adapter) -> None:
    if not adapter.available:
        print("[FrontGateRoom] room_ready_ack skipped: G1/OM1 adapter unavailable", flush=True)
        return
    if not _env_flag("INTERRUPT_FRONTGATE_ENABLE_ROOM_READY_ACK", True):
        return

    reply = (
        os.getenv("INTERRUPT_FRONTGATE_ROOM_READY_ACK_TEXT", "现在可以了").strip()
        or "现在可以了"
    )
    speak_result = adapter.speak(reply)
    print(
        "[FrontGateRoom] room_ready_ack "
        f"reply={reply} ok={speak_result.ok} stdout={speak_result.stdout!r} stderr={speak_result.stderr!r}",
        flush=True,
    )


async def _run(args: argparse.Namespace) -> int:
    settings = load_settings(ROOT_DIR / "config.yaml")
    adapter = G1Om1Adapter()
    started_processes: list[tuple[str, subprocess.Popen[bytes]]] = []
    signal_path = Path(args.session_exit_signal_file).expanduser()
    os.environ["INTERRUPT_FRONTGATE_SESSION_EXIT_SIGNAL_FILE"] = str(signal_path)
    try:
        signal_path.unlink()
    except FileNotFoundError:
        pass

    try:
        room_agent_started = False
        rtc_endpoint_started = False
        room_agent_offset = _log_size(ROOT_DIR / "logs" / "room-agent.log")
        rtc_offset = _log_size(ROOT_DIR / "logs" / "robot-rtc-endpoint.log")
        if _env_flag("INTERRUPT_FRONTGATE_ENSURE_ROOM_AGENT", True):
            proc = _ensure_process_running(
                "room-agent",
                args.room_agent_pattern,
                args.room_agent_command,
            )
            if proc is not None:
                started_processes.append(("room-agent", proc))
                room_agent_started = True
        if _env_flag("INTERRUPT_FRONTGATE_ENSURE_RTC_ENDPOINT", True):
            proc = _ensure_process_running(
                "rtc-endpoint",
                args.rtc_endpoint_pattern,
                args.rtc_endpoint_command,
            )
            if proc is not None:
                started_processes.append(("rtc-endpoint", proc))
                rtc_endpoint_started = True

        pre_dispatch_delay_s = max(0.0, args.pre_dispatch_delay)
        if pre_dispatch_delay_s > 0 and started_processes:
            print(
                f"[FrontGateRoom] waiting before dispatch: {pre_dispatch_delay_s:.1f}s",
                flush=True,
            )
            await asyncio.sleep(pre_dispatch_delay_s)
        if started_processes:
            ready = await _wait_for_managed_process_readiness(
                room_agent_started=room_agent_started,
                rtc_endpoint_started=rtc_endpoint_started,
                room_agent_offset=room_agent_offset,
                rtc_offset=rtc_offset,
                timeout_s=max(2.0, args.startup_timeout),
                poll_s=max(0.2, args.poll_interval),
            )
            if not ready:
                return 1

        await ensure_room_ready(
            settings,
            settings.rtc_endpoint.room_name,
            create_room=settings.rtc_endpoint.auto_create_room,
            dispatch_agent=True,
            dispatch_metadata="frontgate-wake-session",
            replace_existing_dispatch=True,
        )
        print(
            f"[FrontGateRoom] dispatch requested room={settings.rtc_endpoint.room_name}",
            flush=True,
        )

        started_at = time.monotonic()
        saw_session_ready = False
        last_session_ready_at = 0.0
        poll_interval_s = max(0.2, args.poll_interval)
        idle_grace_s = max(0.0, args.idle_grace)
        max_duration_s = max(0.0, args.max_duration)

        while True:
            if signal_path.exists():
                reason = signal_path.read_text(errors="ignore").strip() or "session_exit_signal"
                print(
                    "[FrontGateRoom] room session exit signal received "
                    f"room={settings.rtc_endpoint.room_name} reason={reason}",
                    flush=True,
                )
                return 0
            participants = await list_room_participants(settings, settings.rtc_endpoint.room_name)
            identities = [getattr(item, "identity", "").strip() for item in participants]
            agents = [
                identity
                for identity in identities
                if _agent_identity(identity, settings.agent.name)
            ]
            robots = [
                identity
                for identity in identities
                if identity == settings.rtc_endpoint.identity
            ]
            now = time.monotonic()
            if max_duration_s > 0 and now - started_at >= max_duration_s:
                print(
                    "[FrontGateRoom] room session max duration reached "
                    f"room={settings.rtc_endpoint.room_name} duration={max_duration_s:.1f}s robots={robots}",
                    flush=True,
                )
                return 0
            session_ready = bool(agents and robots)
            if session_ready:
                if not saw_session_ready:
                    _speak_room_ready(adapter)
                    print(
                        "[FrontGateRoom] room session active "
                        f"room={settings.rtc_endpoint.room_name} agents={agents} robots={robots}",
                        flush=True,
                    )
                saw_session_ready = True
                last_session_ready_at = now
            elif not saw_session_ready and now - started_at >= max(1.0, args.startup_timeout):
                print(
                    "[FrontGateRoom] room session startup timeout "
                    f"room={settings.rtc_endpoint.room_name} agents={agents} robots={robots}",
                    flush=True,
                )
                return 1
            elif saw_session_ready and now - last_session_ready_at >= idle_grace_s:
                print(
                    "[FrontGateRoom] room session ended "
                    f"room={settings.rtc_endpoint.room_name} agents={agents} robots={robots}",
                    flush=True,
                )
                return 0

            await asyncio.sleep(poll_interval_s)
    finally:
        try:
            signal_path.unlink()
        except FileNotFoundError:
            pass
        _terminate_started_processes(started_processes)


def main() -> int:
    load_environment()
    args = _build_parser().parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
