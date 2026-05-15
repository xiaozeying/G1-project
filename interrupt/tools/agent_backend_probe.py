#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import urllib.request
from urllib.error import URLError

from src.settings import load_settings


def _probe_ollama(base_url: str) -> tuple[bool, str]:
    url = base_url.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            payload = response.read().decode("utf-8", errors="replace")
        return True, payload[:200]
    except (TimeoutError, URLError, OSError) as exc:
        return False, str(exc)


def main() -> int:
    settings = load_settings()
    backend = settings.agent.backend
    payload: dict[str, object] = {
        "backend": backend,
        "agent_model": settings.agent.model,
        "local_text_provider": settings.agent.local_text_provider,
        "local_text_model": settings.agent.local_text_model,
        "local_text_base_url": settings.agent.local_text_base_url,
        "ready_for_room_agent": False,
        "reason": "",
    }

    if backend == "gemini_realtime":
        payload["ready_for_room_agent"] = bool(settings.gemini_api_key)
        payload["reason"] = (
            "gemini_api_key_present" if settings.gemini_api_key else "missing_gemini_api_key"
        )
    elif backend == "local_text_ollama":
        ok, detail = _probe_ollama(settings.agent.local_text_base_url)
        payload["local_text_reachable"] = ok
        payload["local_text_probe_detail"] = detail
        payload["ready_for_room_agent"] = False
        payload["reason"] = (
            "local_text_eval_only_room_agent_not_integrated"
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
