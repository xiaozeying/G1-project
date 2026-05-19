#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.settings import load_settings


def _probe_local_text(provider: str, base_url: str, api_key: str, model: str) -> tuple[bool, str]:
    normalized_provider = (provider or "").strip().lower()
    if normalized_provider == "openai_compatible":
        url = base_url.rstrip("/")
        if not url.endswith("/v1"):
            url += "/v1"
        url += "/models"
        headers = {"Content-Type": "application/json"}
        if api_key.strip():
            headers["Authorization"] = f"Bearer {api_key.strip()}"
    else:
        url = base_url.rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3]
        url = url.rstrip("/") + "/api/tags"
        headers = {"Content-Type": "application/json"}
    try:
        request = urllib.request.Request(url, headers=headers, method="GET")
        host = (urlparse(base_url).hostname or "").strip().lower()
        opener = (
            urllib.request.build_opener(urllib.request.ProxyHandler({}))
            if host in {"127.0.0.1", "localhost", "::1"} or host.startswith("192.168.")
            else urllib.request.build_opener()
        )
        with opener.open(request, timeout=3) as response:
            payload = response.read().decode("utf-8", errors="replace")
        if normalized_provider == "openai_compatible":
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                return False, "invalid_json"
            model_ids = [
                str(item.get("id") or "").strip()
                for item in data.get("data", [])
                if isinstance(item, dict)
            ]
            if model and model not in model_ids:
                return False, "model_not_found"
        return True, payload[:200]
    except (TimeoutError, URLError, OSError) as exc:
        return False, str(exc)


def _local_text_expected(settings) -> bool:
    return (
        settings.agent.backend in {"local_text_ollama", "local_text_openai_compatible"}
        or settings.agent.runtime_mode == "offline_singlebox"
        or settings.agent.local_text_decision_mode != "disabled"
    )


def main() -> int:
    settings = load_settings()
    backend = settings.agent.backend
    local_text_expected = _local_text_expected(settings)
    payload: dict[str, object] = {
        "backend": backend,
        "runtime_mode": settings.agent.runtime_mode,
        "agent_model": settings.agent.model,
        "local_text_provider": settings.agent.local_text_provider,
        "local_text_api_key_set": bool(settings.agent.local_text_api_key),
        "local_text_decision_mode": settings.agent.local_text_decision_mode,
        "local_text_model": settings.agent.local_text_model,
        "local_text_base_url": settings.agent.local_text_base_url,
        "local_text_integrated": local_text_expected,
        "ready_for_room_agent": False,
        "ready_for_offline_singlebox": False,
        "reason": "",
    }

    if local_text_expected:
        ok, detail = _probe_local_text(
            settings.agent.local_text_provider,
            settings.agent.local_text_base_url,
            settings.agent.local_text_api_key,
            settings.agent.local_text_model,
        )
        payload["local_text_reachable"] = ok
        payload["local_text_probe_detail"] = detail
        payload["ready_for_offline_singlebox"] = ok

    if backend == "gemini_realtime":
        payload["ready_for_room_agent"] = bool(settings.gemini_api_key)
        if not settings.gemini_api_key:
            payload["reason"] = "missing_gemini_api_key"
        elif local_text_expected and payload.get("local_text_reachable") is False:
            payload["reason"] = "gemini_realtime_ready_but_local_text_unreachable"
        elif local_text_expected:
            payload["reason"] = "gemini_realtime_with_local_text_tools"
        else:
            payload["reason"] = "gemini_realtime_only"
    elif backend in {"local_text_ollama", "local_text_openai_compatible"}:
        ok = bool(payload.get("local_text_reachable"))
        payload["ready_for_room_agent"] = ok
        payload["ready_for_offline_singlebox"] = ok
        payload["reason"] = (
            "local_text_room_agent_integrated"
            if ok
            else "local_text_backend_unreachable"
        )
    else:
        payload["reason"] = "unsupported_backend"

    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
