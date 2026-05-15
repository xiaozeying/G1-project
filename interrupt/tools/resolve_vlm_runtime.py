#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.settings import load_environment, load_settings


@dataclass(frozen=True)
class Candidate:
    source: str
    provider: str
    base_url: str
    model: str
    api_key: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve the VLM backend to use for local or robot-side smoke tests."
    )
    parser.add_argument("--mode", choices=("local", "robot"), default="local")
    parser.add_argument(
        "--allow-online-fallback",
        action="store_true",
        help="Allow non-probeable cloud backends such as Gemini as a last resort.",
    )
    parser.add_argument(
        "--require-offline",
        action="store_true",
        help="Fail unless a local/OpenAI-compatible backend is reachable.",
    )
    parser.add_argument("--timeout", type=float, default=1.5)
    parser.add_argument(
        "--format",
        choices=("shell", "json"),
        default="shell",
        help="Output format.",
    )
    return parser.parse_args()


def build_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    return headers


def build_opener(base_url: str, provider: str) -> urllib.request.OpenerDirector:
    host = (urlparse(base_url).hostname or "").strip().lower()
    if provider == "ollama_native" or host in {"127.0.0.1", "localhost", "::1"}:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def is_probeable(provider: str) -> bool:
    return provider in {"ollama_native", "openai_compatible"}


def probe(candidate: Candidate, timeout: float) -> tuple[bool, str]:
    if candidate.provider == "ollama_native":
        url = candidate.base_url.rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3]
        url = url.rstrip("/") + "/api/tags"
    elif candidate.provider == "openai_compatible":
        url = candidate.base_url.rstrip("/") + "/models"
    else:
        return True, "non_probeable"

    request = urllib.request.Request(
        url=url,
        headers=build_headers(candidate.api_key),
        method="GET",
    )
    try:
        opener = build_opener(candidate.base_url, candidate.provider)
        with opener.open(request, timeout=max(0.5, timeout)) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}"
    except Exception as exc:  # pragma: no cover - depends on machine/runtime
        return False, str(exc)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return False, f"invalid_json:{exc}"

    if candidate.provider == "ollama_native":
        models = [
            str(item.get("name") or "").strip()
            for item in payload.get("models", [])
            if isinstance(item, dict)
        ]
    else:
        models = [
            str(item.get("id") or "").strip()
            for item in payload.get("data", [])
            if isinstance(item, dict)
        ]

    if candidate.model and candidate.model not in models:
        return False, "model_not_found"
    return True, "ok"


def _candidate(
    source: str,
    provider: str,
    base_url: str,
    model: str,
    api_key: str,
) -> Candidate | None:
    provider = provider.strip()
    base_url = base_url.strip()
    model = model.strip()
    if not provider or not model:
        return None
    return Candidate(
        source=source,
        provider=provider,
        base_url=base_url,
        model=model,
        api_key=api_key.strip(),
    )


def build_candidates(mode: str, allow_online_fallback: bool) -> list[Candidate]:
    load_environment()
    settings = load_settings(ROOT_DIR / "config.yaml")

    configured = _candidate(
        "configured",
        settings.vision.provider,
        settings.vision.base_url,
        settings.vision.model,
        settings.vision.api_key,
    )
    explicit_override = any(
        os.getenv(name, "").strip()
        for name in (
            "INTERRUPT_VLM_PROVIDER",
            "INTERRUPT_VLM_BASE_URL",
            "INTERRUPT_VLM_MODEL",
            "INTERRUPT_VLM_API_KEY",
        )
    )

    candidates: list[Candidate] = []
    if explicit_override and configured is not None:
        candidates.append(
            Candidate(
                source="env_override",
                provider=configured.provider,
                base_url=configured.base_url,
                model=configured.model,
                api_key=configured.api_key,
            )
        )

    if mode == "local":
        defaults = [
            _candidate(
                "qwen25_vl_7b_local",
                "openai_compatible",
                os.getenv("INTERRUPT_LOCAL_QWEN_BASE_URL", "http://127.0.0.1:8000/v1"),
                os.getenv("INTERRUPT_LOCAL_QWEN_MODEL", "Qwen2.5-VL-7B-Instruct"),
                os.getenv("INTERRUPT_LOCAL_QWEN_API_KEY", ""),
            ),
            _candidate(
                "qwen25_vl_3b_local",
                "openai_compatible",
                os.getenv("INTERRUPT_LOCAL_QWEN_BASE_URL", "http://127.0.0.1:8000/v1"),
                os.getenv("INTERRUPT_LOCAL_QWEN_3B_MODEL", "Qwen2.5-VL-3B-Instruct"),
                os.getenv("INTERRUPT_LOCAL_QWEN_API_KEY", ""),
            ),
            _candidate(
                "gemma3_ollama_local",
                "ollama_native",
                os.getenv("INTERRUPT_LOCAL_OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
                os.getenv("INTERRUPT_LOCAL_OLLAMA_MODEL", "gemma3:latest"),
                os.getenv("INTERRUPT_LOCAL_OLLAMA_API_KEY", ""),
            ),
        ]
        candidates.extend(candidate for candidate in defaults if candidate is not None)
        if configured is not None and (allow_online_fallback or is_probeable(configured.provider)):
            candidates.append(configured)
    else:
        robot_defaults = [
            _candidate(
                "robot_offline_ollama",
                os.getenv("INTERRUPT_ROBOT_OFFLINE_VLM_PROVIDER", "ollama_native"),
                os.getenv(
                    "INTERRUPT_ROBOT_OFFLINE_VLM_BASE_URL",
                    "http://192.168.100.48:11434/v1",
                ),
                os.getenv("INTERRUPT_ROBOT_OFFLINE_VLM_MODEL", "gemma3:latest"),
                os.getenv("INTERRUPT_ROBOT_OFFLINE_VLM_API_KEY", ""),
            ),
            _candidate(
                "robot_offline_openai_compat",
                os.getenv("INTERRUPT_ROBOT_OFFLINE_OPENAI_PROVIDER", "openai_compatible"),
                os.getenv("INTERRUPT_ROBOT_OFFLINE_OPENAI_BASE_URL", ""),
                os.getenv("INTERRUPT_ROBOT_OFFLINE_OPENAI_MODEL", ""),
                os.getenv("INTERRUPT_ROBOT_OFFLINE_OPENAI_API_KEY", ""),
            ),
        ]
        candidates.extend(candidate for candidate in robot_defaults if candidate is not None)
        if configured is not None:
            candidates.append(configured)

    deduped: list[Candidate] = []
    seen: set[tuple[str, str, str]] = set()
    for candidate in candidates:
        key = (candidate.provider, candidate.base_url, candidate.model)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def choose_candidate(args: argparse.Namespace) -> tuple[Candidate, str]:
    candidates = build_candidates(args.mode, args.allow_online_fallback)
    errors: list[str] = []

    for candidate in candidates:
        if not is_probeable(candidate.provider):
            if args.require_offline:
                errors.append(f"{candidate.source}:{candidate.provider}:offline_required")
                continue
            return candidate, "fallback_non_probeable"

        ok, reason = probe(candidate, args.timeout)
        if ok:
            return candidate, reason
        errors.append(f"{candidate.source}:{candidate.provider}:{reason}")

    error_text = " ; ".join(errors) if errors else "no_candidates"
    raise RuntimeError(error_text)


def emit_shell(candidate: Candidate, probe_reason: str) -> None:
    values = {
        "INTERRUPT_VLM_ENABLED": "1",
        "INTERRUPT_VLM_PROVIDER": candidate.provider,
        "INTERRUPT_VLM_BASE_URL": candidate.base_url,
        "INTERRUPT_VLM_MODEL": candidate.model,
        "INTERRUPT_VLM_API_KEY": candidate.api_key,
        "INTERRUPT_VLM_RESOLVED_SOURCE": candidate.source,
        "INTERRUPT_VLM_RESOLVED_REASON": probe_reason,
    }
    for key, value in values.items():
        print(f"export {key}={shlex.quote(value)}")


def emit_json(candidate: Candidate, probe_reason: str) -> None:
    print(
        json.dumps(
            {
                "provider": candidate.provider,
                "base_url": candidate.base_url,
                "model": candidate.model,
                "api_key_set": bool(candidate.api_key),
                "source": candidate.source,
                "reason": probe_reason,
            },
            ensure_ascii=False,
        )
    )


def main() -> int:
    args = parse_args()
    try:
        candidate, probe_reason = choose_candidate(args)
    except Exception as exc:
        print(f"resolve_vlm_runtime failed: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        emit_json(candidate, probe_reason)
    else:
        emit_shell(candidate, probe_reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
