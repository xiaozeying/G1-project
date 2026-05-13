#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.settings import load_environment, load_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe an OpenAI-compatible VLM backend and optionally verify a model is present."
    )
    parser.add_argument("--provider", default="", help="Optional provider override.")
    parser.add_argument("--base-url", default="", help="Optional base URL override.")
    parser.add_argument("--api-key", default="", help="Optional API key override.")
    parser.add_argument("--model", default="", help="Optional model override.")
    parser.add_argument("--timeout", type=float, default=8.0, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--require-model",
        action="store_true",
        help="Fail if the configured/selected model is not present in /models.",
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


def main() -> int:
    args = parse_args()
    load_environment()
    settings = load_settings(ROOT_DIR / "config.yaml")

    provider = args.provider.strip() or settings.vision.provider
    base_url = args.base_url.strip() or settings.vision.base_url
    api_key = args.api_key.strip() or settings.vision.api_key
    model = args.model.strip() or settings.vision.model

    if provider == "ollama_native":
        url = base_url.rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3]
        url = url.rstrip("/") + "/api/tags"
        request = urllib.request.Request(
            url=url,
            headers=build_headers(api_key),
            method="GET",
        )
    elif provider == "openai_compatible":
        url = base_url.rstrip("/") + "/models"
        request = urllib.request.Request(
            url=url,
            headers=build_headers(api_key),
            method="GET",
        )
    else:
        print("status: SKIP")
        print(f"provider: {provider}")
        print("reason: backend probe currently targets ollama_native and openai_compatible only")
        return 0
    try:
        opener = build_opener(base_url, provider)
        with opener.open(request, timeout=max(1.0, args.timeout)) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print("status: FAIL")
        print(f"provider: {provider}")
        print(f"base_url: {base_url}")
        print(f"model: {model}")
        print(f"error: http_{exc.code}")
        print(f"body: {body}")
        return 1
    except Exception as exc:
        print("status: FAIL")
        print(f"provider: {provider}")
        print(f"base_url: {base_url}")
        print(f"model: {model}")
        print(f"error: {exc}")
        return 1

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print("status: FAIL")
        print(f"provider: {provider}")
        print(f"base_url: {base_url}")
        print(f"model: {model}")
        print(f"error: invalid_json:{exc}")
        print(f"body: {raw}")
        return 1

    ids = []
    if provider == "ollama_native":
        for item in payload.get("models", []):
            if isinstance(item, dict):
                model_id = str(item.get("name") or "").strip()
                if model_id:
                    ids.append(model_id)
    else:
        for item in payload.get("data", []):
            if isinstance(item, dict):
                model_id = str(item.get("id") or "").strip()
                if model_id:
                    ids.append(model_id)

    found = model in ids

    print("status: OK")
    print(f"provider: {provider}")
    print(f"base_url: {base_url}")
    print(f"model: {model}")
    print(f"model_found: {'yes' if found else 'no'}")
    if ids:
        print("models:")
        for model_id in ids:
            print(f"  - {model_id}")
    else:
        print("models: <empty>")

    if args.require_model and not found:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
