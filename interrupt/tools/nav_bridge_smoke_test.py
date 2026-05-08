#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import runpy
import socket
import subprocess
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest import mock


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.g1_om1_adapter import G1Om1Adapter, G1Om1AdapterConfig


class _MockNavBridge(BaseHTTPRequestHandler):
    locations: dict[str, dict[str, Any]] = {
        "前台": {
            "name": "前台",
            "pose": {
                "position": {"x": 1.0, "y": 2.0, "z": 0.0},
                "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
            },
        }
    }
    last_navigation_label: str | None = None
    last_remember_payload: dict[str, Any] | None = None

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/maps/locations/list":
            self._write_json(HTTPStatus.OK, self.locations)
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        payload = self._read_json()
        if self.path == "/navigate/location":
            label = str(payload.get("label") or "").strip()
            if label != "前台":
                self._write_json(
                    HTTPStatus.NOT_FOUND,
                    {"ok": False, "message": f"location not found: {label}"},
                )
                return
            _MockNavBridge.last_navigation_label = label
            self._write_json(
                HTTPStatus.OK,
                {"ok": True, "message": f"navigating to {label}", "entry": self.locations[label]},
            )
            return
        if self.path == "/maps/locations/add/slam":
            _MockNavBridge.last_remember_payload = payload
            self._write_json(
                HTTPStatus.OK,
                {"ok": True, "message": "saved", "entry": payload},
            )
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"ok": False, "message": "not found"})

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _serve(server: ThreadingHTTPServer) -> None:
    server.serve_forever()


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _exercise_cli(base_url: str) -> None:
    env = os.environ.copy()
    env["INTERRUPT_G1_NAV_BASE_URL"] = base_url
    command = [
        sys.executable,
        str(ROOT_DIR / "tools" / "g1_om1_cli.py"),
        "list-locations",
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False, env=env)
    _assert(result.returncode == 0, f"list-locations cli failed: {result.stderr or result.stdout}")


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload
        if isinstance(payload, str):
            self.text = payload
        else:
            self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> Any:
        if isinstance(self._payload, str):
            raise ValueError("string payload")
        return self._payload

    def raise_for_status(self) -> None:
        if 200 <= self.status_code < 300:
            return
        raise RuntimeError(f"http {self.status_code}")


def _run_g1_nav_command_inproc(argv: list[str], *, state: dict[str, Any]) -> tuple[int, str]:
    captured: list[str] = []

    def _fake_print(*args: object, **kwargs: object) -> None:
        captured.append(" ".join(str(arg) for arg in args))

    def _fake_get(url: str, timeout: float) -> _FakeResponse:
        _assert(url.endswith("/maps/locations/list"), f"unexpected GET url: {url}")
        return _FakeResponse(200, state["locations"])

    def _fake_post(url: str, json: dict[str, Any], timeout: float) -> _FakeResponse:
        if url.endswith("/navigate/location"):
            state["last_navigation_label"] = json.get("label")
            return _FakeResponse(
                200,
                {"ok": True, "message": f"navigating to {json.get('label')}", "entry": state["locations"]["前台"]},
            )
        if url.endswith("/maps/locations/add/slam"):
            state["last_remember_payload"] = dict(json)
            return _FakeResponse(200, {"ok": True, "message": "saved", "entry": json})
        return _FakeResponse(404, {"ok": False, "message": "not found"})

    old_argv = sys.argv[:]
    try:
        sys.argv = ["g1_nav_command.py", *argv]
        with mock.patch("requests.get", side_effect=_fake_get), mock.patch(
            "requests.post",
            side_effect=_fake_post,
        ), mock.patch("builtins.print", side_effect=_fake_print):
            try:
                runpy.run_path(
                    str(ROOT_DIR / ".." / "OM1" / "scripts" / "g1_nav_command.py"),
                    run_name="__main__",
                )
            except SystemExit as exc:
                code = int(exc.code or 0)
            else:
                code = 0
    finally:
        sys.argv = old_argv
    return code, "\n".join(captured)


def _fallback_inproc_smoke() -> None:
    state: dict[str, Any] = {
        "locations": {
            "前台": {
                "name": "前台",
                "pose": {
                    "position": {"x": 1.0, "y": 2.0, "z": 0.0},
                    "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
                },
            }
        },
        "last_navigation_label": None,
        "last_remember_payload": None,
    }

    adapter = G1Om1Adapter()
    _assert(adapter.config.navigation_base_url.startswith("http://"), "unexpected default nav base url")

    code, output = _run_g1_nav_command_inproc(["list", "--compact"], state=state)
    _assert(code == 0, f"list command failed: {output}")
    payload = json.loads(output)
    _assert("前台" in payload.get("locations", []), f"unexpected list payload: {payload}")

    code, output = _run_g1_nav_command_inproc(["remember", "茶水间", "--description", "二楼"], state=state)
    _assert(code == 0, f"remember command failed: {output}")
    _assert(state["last_remember_payload"] is not None, "remember payload missing")
    _assert(state["last_remember_payload"].get("label") == "茶水间", "remember label mismatch")

    code, output = _run_g1_nav_command_inproc(["navigate", "前台"], state=state)
    _assert(code == 0, f"navigate command failed: {output}")
    _assert(state["last_navigation_label"] == "前台", "navigate label mismatch")


def main() -> int:
    try:
        port = _find_free_port()
    except PermissionError:
        _fallback_inproc_smoke()
        print("nav bridge smoke test passed (in-process fallback)")
        return 0
    server = ThreadingHTTPServer(("127.0.0.1", port), _MockNavBridge)
    thread = threading.Thread(target=_serve, args=(server,), daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    config = G1Om1AdapterConfig(
        python_executable=sys.executable,
        direct_command_script=str(ROOT_DIR / ".." / "OM1" / "scripts" / "g1_direct_command_fallback.py"),
        feedback_script=str(ROOT_DIR / ".." / "OM1" / "scripts" / "g1_watchdog_feedback.py"),
        navigation_script=str(ROOT_DIR / ".." / "OM1" / "scripts" / "g1_nav_command.py"),
        navigation_base_url=base_url,
        navigation_timeout_s=3.0,
        unitree_interface="eth1",
    )
    adapter = G1Om1Adapter(config)

    try:
        list_result = adapter.list_saved_locations(compact=True)
        _assert(list_result.ok, f"list saved locations failed: {list_result.stderr or list_result.stdout}")
        list_payload = json.loads(list_result.stdout)
        _assert("前台" in list_payload.get("locations", []), f"unexpected locations payload: {list_payload}")

        remember_result = adapter.remember_location("茶水间", description="二楼")
        _assert(remember_result.ok, f"remember location failed: {remember_result.stderr or remember_result.stdout}")
        _assert(_MockNavBridge.last_remember_payload is not None, "remember payload missing")
        _assert(_MockNavBridge.last_remember_payload.get("label") == "茶水间", "remember label mismatch")

        navigate_result = adapter.navigate_to_location("前台")
        _assert(navigate_result.ok, f"navigate failed: {navigate_result.stderr or navigate_result.stdout}")
        _assert(_MockNavBridge.last_navigation_label == "前台", "navigate label mismatch")

        _exercise_cli(base_url)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)

    print("nav bridge smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
