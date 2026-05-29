#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.g1_om1_adapter import G1Om1Adapter


def _hongtu_nav_runtime_probe() -> dict[str, Any]:
    script = ROOT_DIR / "tools" / "hongtu_nav_runtime_probe.py"
    if not script.exists():
        return {"ok": False, "detail": "hongtu_nav_runtime_probe_missing"}
    try:
        completed = subprocess.run(
            [sys.executable, str(script)],
            check=False,
            text=True,
            capture_output=True,
            timeout=8.0,
        )
    except OSError as exc:
        return {"ok": False, "detail": str(exc)}
    payload: Any
    try:
        payload = json.loads((completed.stdout or "").strip() or "{}")
    except json.JSONDecodeError:
        payload = (completed.stdout or "").strip()
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "payload": payload,
        "stderr": (completed.stderr or "").strip(),
    }


def _parse_host_port(base_url: str) -> tuple[str, int]:
    parsed = urlparse(base_url)
    host = parsed.hostname or "localhost"
    port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
    return host, port


def _socket_probe(host: str, port: int, timeout_s: float) -> dict[str, Any]:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout_s)
    except OSError as exc:
        return {"ok": False, "detail": str(exc)}
    try:
        sock.connect((host, port))
        return {"ok": True}
    except OSError as exc:
        return {"ok": False, "detail": str(exc)}
    finally:
        sock.close()


def _http_probe(base_url: str, timeout_s: float) -> dict[str, Any]:
    try:
        response = requests.get(f"{base_url.rstrip('/')}/healthz", timeout=timeout_s)
        payload: Any
        try:
            payload = response.json()
        except ValueError:
            payload = response.text.strip()
        return {
            "ok": 200 <= response.status_code < 300,
            "status": response.status_code,
            "payload": payload,
        }
    except requests.RequestException as exc:
        return {"ok": False, "detail": str(exc)}


def _cli_probe() -> dict[str, Any]:
    adapter = G1Om1Adapter()
    result = adapter.list_saved_locations(compact=True)
    payload: Any
    try:
        payload = json.loads(result.stdout) if result.stdout else None
    except json.JSONDecodeError:
        payload = result.stdout
    return {
        "ok": result.ok,
        "returncode": result.returncode,
        "stdout": payload,
        "stderr": result.stderr,
        "command": list(result.command),
    }


def _paths_probe() -> dict[str, Any]:
    adapter = G1Om1Adapter()
    return {
        "script_paths": adapter.script_paths(),
        "path_checks": adapter.validate_paths(),
    }


def _ps_probe() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["ps", "-ef"],
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError as exc:
        return {"ok": False, "detail": str(exc)}
    lines = []
    for line in (completed.stdout or "").splitlines():
        lowered = line.lower()
        if any(token in lowered for token in ("move_base", "amcl", "roscore", "rosmaster", "nav")):
            lines.append(line.strip())
    return {"ok": True, "matches": lines[:30]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe the robot navigation backend used by interrupt voice navigation.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("INTERRUPT_G1_NAV_BASE_URL", "http://localhost:5000"),
        help="Navigation backend base URL.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=2.0,
        help="Probe timeout in seconds.",
    )
    args = parser.parse_args()

    host, port = _parse_host_port(args.base_url)
    payload = {
        "base_url": args.base_url,
        "socket_probe": _socket_probe(host, port, args.timeout),
        "http_probe": _http_probe(args.base_url, args.timeout),
        "cli_probe": _cli_probe(),
        "adapter": _paths_probe(),
        "processes": _ps_probe(),
        "hongtu_nav_runtime": _hongtu_nav_runtime_probe(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
