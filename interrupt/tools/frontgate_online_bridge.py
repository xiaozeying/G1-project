#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.settings import load_environment


@dataclass
class _WakeSessionRequest:
    wakeword: str
    text: str
    language: str
    detected_lang: str
    intro_done_signal_file: str
    metadata: dict[str, object]


_SESSION_LOCK = threading.Lock()


def _room_session_command() -> list[str]:
    command = (
        os.getenv("INTERRUPT_FRONTGATE_ROOM_SESSION_COMMAND", "").strip()
        or str(ROOT_DIR / "run_frontgate_room_session.sh")
    )
    return shlex.split(command)


def _serialize_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, object]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _run_room_session(request: _WakeSessionRequest) -> dict[str, object]:
    env = os.environ.copy()
    env["INTERRUPT_WAKE_EVENT_WAKEWORD"] = request.wakeword
    env["INTERRUPT_WAKE_EVENT_TEXT"] = request.text
    env["INTERRUPT_WAKE_EVENT_LANGUAGE"] = request.language
    env["INTERRUPT_WAKE_EVENT_DETECTED_LANG"] = request.detected_lang
    if request.intro_done_signal_file:
        env["INTERRUPT_FRONTGATE_INTRO_DONE_SIGNAL_FILE"] = request.intro_done_signal_file
    for key, value in request.metadata.items():
        env_key = f"INTERRUPT_WAKE_EVENT_{str(key).upper()}"
        env[env_key] = str(value)
    command = _room_session_command()
    started_at = time.monotonic()
    print(
        "[FrontGateOnlineBridge] wake request accepted "
        f"wakeword={request.wakeword!r} language={request.language} command={' '.join(command)}",
        flush=True,
    )
    result = subprocess.run(
        command,
        cwd=str(ROOT_DIR),
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    elapsed = time.monotonic() - started_at
    print(
        "[FrontGateOnlineBridge] wake session finished "
        f"rc={result.returncode} elapsed={elapsed:.1f}s wakeword={request.wakeword!r}",
        flush=True,
    )
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "elapsed_s": round(elapsed, 3),
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "FrontGateOnlineBridge/1.0"

    def do_GET(self) -> None:
        if self.path != "/healthz":
            _serialize_json(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        busy = _SESSION_LOCK.locked()
        _serialize_json(self, HTTPStatus.OK, {"ok": True, "busy": busy})

    def do_POST(self) -> None:
        if self.path != "/wake-session":
            _serialize_json(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        raw_body = self.rfile.read(max(0, length))
        try:
            payload = json.loads(raw_body.decode("utf-8", errors="ignore") or "{}")
        except json.JSONDecodeError:
            _serialize_json(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
            return
        request = _WakeSessionRequest(
            wakeword=str(payload.get("wakeword", "") or "").strip(),
            text=str(payload.get("text", "") or "").strip(),
            language=str(payload.get("language", "") or "").strip(),
            detected_lang=str(payload.get("detected_lang", "") or "").strip(),
            intro_done_signal_file=str(payload.get("intro_done_signal_file", "") or "").strip(),
            metadata=dict(payload.get("metadata") or {}),
        )
        if not _SESSION_LOCK.acquire(blocking=False):
            _serialize_json(
                self,
                HTTPStatus.CONFLICT,
                {"ok": False, "error": "session_busy"},
            )
            return
        try:
            result = _run_room_session(request)
        finally:
            _SESSION_LOCK.release()
        _serialize_json(self, HTTPStatus.OK, result)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[FrontGateOnlineBridge] {fmt % args}", flush=True)


def main() -> int:
    load_environment(ROOT_DIR / "config.yaml")
    host = os.getenv("INTERRUPT_FRONTGATE_ONLINE_BRIDGE_BIND", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("INTERRUPT_FRONTGATE_ONLINE_BRIDGE_PORT", "8787").strip() or "8787")
    server = ThreadingHTTPServer((host, port), _Handler)
    print(
        f"[FrontGateOnlineBridge] listening host={host} port={port} room_session_command={' '.join(_room_session_command())}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[FrontGateOnlineBridge] interrupted, shutting down", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
