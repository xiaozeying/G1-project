#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${INTERRUPT_FRONTGATE_NOTIFY_PYTHON:-python3}"
REQUEST_TIMEOUT_S="${INTERRUPT_FRONTGATE_ONLINE_BRIDGE_TIMEOUT_S:-900}"
DIALOGUE_MODE="${INTERRUPT_DIALOGUE_MODE:-online}"
ONLINE_BRIDGE_URL="${INTERRUPT_FRONTGATE_ONLINE_BRIDGE_URL:-http://127.0.0.1:8787/wake-session}"
OFFLINE_BRIDGE_URL="${INTERRUPT_FRONTGATE_OFFLINE_BRIDGE_URL:-http://127.0.0.1:8788/wake-session}"

resolve_bridge_url() {
  case "${DIALOGUE_MODE}" in
    offline)
      printf '%s\n' "${OFFLINE_BRIDGE_URL}"
      ;;
    *)
      printf '%s\n' "${ONLINE_BRIDGE_URL}"
      ;;
  esac
}

BRIDGE_URL="$(resolve_bridge_url)"

exec "${PYTHON_BIN}" - "${BRIDGE_URL}" "${REQUEST_TIMEOUT_S}" <<'PY'
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _payload() -> dict[str, object]:
    metadata: dict[str, object] = {}
    for key in ("similarity",):
        value = os.getenv(f"INTERRUPT_WAKE_EVENT_{key.upper()}", "").strip()
        if not value:
            continue
        try:
            metadata[key] = float(value)
        except ValueError:
            metadata[key] = value
    for key in ("seed_text", "source"):
        value = os.getenv(f"INTERRUPT_WAKE_EVENT_{key.upper()}", "").strip()
        if value:
            metadata[key] = value
    intro_done_signal = os.getenv("INTERRUPT_FRONTGATE_INTRO_DONE_SIGNAL_FILE", "").strip()
    return {
        "wakeword": os.getenv("INTERRUPT_WAKE_EVENT_WAKEWORD", "").strip(),
        "text": os.getenv("INTERRUPT_WAKE_EVENT_TEXT", "").strip(),
        "language": os.getenv("INTERRUPT_WAKE_EVENT_LANGUAGE", "").strip(),
        "detected_lang": os.getenv("INTERRUPT_WAKE_EVENT_DETECTED_LANG", "").strip(),
        "intro_done_signal_file": intro_done_signal,
        "metadata": metadata,
    }


def main() -> int:
    url = sys.argv[1]
    timeout_s = max(1.0, float(sys.argv[2]))
    payload = _payload()
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        print(
            f"[FrontGateNotify] bridge http error url={url} status={exc.code} body={body!r}",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"[FrontGateNotify] bridge request failed url={url} error={exc}", file=sys.stderr)
        return 1
    try:
        parsed = json.loads(body or "{}")
    except json.JSONDecodeError:
        parsed = {"raw": body}
    ok = bool(parsed.get("ok", False))
    print(
        f"[FrontGateNotify] bridge wake completed ok={ok} rc={parsed.get('returncode')} "
        f"language={payload.get('language')} wakeword={payload.get('wakeword')!r}"
    )
    return 0 if ok else int(parsed.get("returncode", 1) or 1)


raise SystemExit(main())
PY
