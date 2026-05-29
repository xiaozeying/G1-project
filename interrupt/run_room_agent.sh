#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/room-agent.log"
VENV_DIR="${INTERRUPT_VENV_DIR:-${ROOT_DIR}/.venv}"
DEFAULT_PYTHON_BIN="${VENV_DIR}/bin/python"

source "${ROOT_DIR}/libexec/python_env.sh"
interrupt_activate_python_env "${ROOT_DIR}"

exec > >(tee -a "${LOG_FILE}") 2>&1
echo "===== $(date '+%F %T') run_room_agent.sh ====="

load_env_defaults() {
  local env_file="$1"
  [[ -f "${env_file}" ]] || return 0
  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ -z "${line}" ]] && continue
    [[ "${line}" =~ ^[[:space:]]*# ]] && continue
    if [[ "${line}" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
      local key="${BASH_REMATCH[1]}"
      local raw_value="${BASH_REMATCH[2]}"
      if [[ -z "${!key+x}" ]]; then
        if [[ "${raw_value}" =~ ^\"(.*)\"$ ]]; then
          printf -v "${key}" '%s' "${BASH_REMATCH[1]}"
        elif [[ "${raw_value}" =~ ^\'(.*)\'$ ]]; then
          printf -v "${key}" '%s' "${BASH_REMATCH[1]}"
        else
          printf -v "${key}" '%s' "${raw_value}"
        fi
        export "${key}"
      fi
    fi
  done < "${env_file}"
}

load_env_defaults "${ROOT_DIR}/.env.local"
load_env_defaults "${ROOT_DIR}/.env"

navigation_bridge_healthy() {
  local base_url="$1"
  python3 - "${base_url}" <<'PY'
import json
import sys
import urllib.error
import urllib.request

base_url = (sys.argv[1] or "").rstrip("/")
if not base_url:
    raise SystemExit(1)
try:
    with urllib.request.urlopen(f"{base_url}/healthz", timeout=1.5) as response:
        payload = json.loads(response.read().decode("utf-8") or "{}")
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if payload.get("ok") else 1)
PY
}

ensure_navigation_bridge() {
  local provider="${INTERRUPT_G1_NAV_PROVIDER:-http_bridge}"
  local base_url="${INTERRUPT_G1_NAV_BASE_URL:-http://127.0.0.1:5000}"
  local runner="${INTERRUPT_G1_NAV_BRIDGE_RUNNER:-}"
  local nav_log="${LOG_DIR}/g1-nav-bridge.log"
  local wait_seconds="${INTERRUPT_G1_NAV_BRIDGE_WAIT_S:-8}"

  if [[ "${provider}" != "g1_3d_nav" ]]; then
    return 0
  fi

  if [[ -z "${runner}" ]]; then
    runner="${ROOT_DIR}/run_g1_3d_nav_bridge.sh"
  fi

  if navigation_bridge_healthy "${base_url}"; then
    echo "navigation bridge already healthy: ${base_url}"
    return 0
  fi

  if [[ ! -f "${runner}" ]]; then
    echo "navigation bridge runner missing: ${runner}"
    return 0
  fi

  echo "starting navigation bridge: provider=${provider} base_url=${base_url} runner=${runner}"
  nohup bash "${runner}" >>"${nav_log}" 2>&1 &

  local started=0
  local elapsed=0
  while (( elapsed < wait_seconds )); do
    sleep 1
    elapsed=$((elapsed + 1))
    if navigation_bridge_healthy "${base_url}"; then
      started=1
      break
    fi
  done

  if (( started == 1 )); then
    echo "navigation bridge ready: ${base_url}"
  else
    echo "navigation bridge not ready after ${wait_seconds}s: ${base_url}"
  fi
}

LIVEKIT_HOST=""
if [[ -n "${LIVEKIT_URL:-}" ]]; then
  LIVEKIT_HOST="$(python3 - <<'PY'
from urllib.parse import urlparse
import os
print(urlparse(os.environ.get("LIVEKIT_URL", "")).hostname or "")
PY
)"
fi

unset WSS_PROXY WS_PROXY wss_proxy ws_proxy

if [[ "${LIVEKIT_HOST}" == "localhost" || "${LIVEKIT_HOST}" == "127.0.0.1" || "${LIVEKIT_HOST}" =~ ^10\. || "${LIVEKIT_HOST}" =~ ^192\.168\. || "${LIVEKIT_HOST}" =~ ^172\.(1[6-9]|2[0-9]|3[0-1])\. ]]; then
  unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
  unset http_proxy https_proxy all_proxy
fi

if [[ -n "${HTTP_PROXY:-}" && -z "${http_proxy:-}" ]]; then
  export http_proxy="${HTTP_PROXY}"
fi
if [[ -n "${HTTPS_PROXY:-}" && -z "${https_proxy:-}" ]]; then
  export https_proxy="${HTTPS_PROXY}"
fi
if [[ -n "${ALL_PROXY:-}" && -z "${all_proxy:-}" ]]; then
  export all_proxy="${ALL_PROXY}"
fi

LOCAL_NO_PROXY="127.0.0.1,localhost,::1"
if [[ -n "${LIVEKIT_HOST}" ]]; then
  LOCAL_NO_PROXY="${LOCAL_NO_PROXY},${LIVEKIT_HOST}"
fi
if [[ -n "${NO_PROXY:-}" ]]; then
  export NO_PROXY="${LOCAL_NO_PROXY},${NO_PROXY}"
else
  export NO_PROXY="${LOCAL_NO_PROXY}"
fi
if [[ -n "${no_proxy:-}" ]]; then
  export no_proxy="${LOCAL_NO_PROXY},${no_proxy}"
else
  export no_proxy="${LOCAL_NO_PROXY}"
fi

export INTERRUPT_AGENT_LOAD_THRESHOLD="${INTERRUPT_AGENT_LOAD_THRESHOLD:-0.99}"
export INTERRUPT_AGENT_FORCE_LOAD="${INTERRUPT_AGENT_FORCE_LOAD:-0.20}"
export INTERRUPT_AGENT_PATCH_JOB_TOKEN="${INTERRUPT_AGENT_PATCH_JOB_TOKEN:-0}"

echo "livekit url: ${LIVEKIT_URL:-unset}"
echo "wss proxy: unset"
echo "livekit proxy bypass host: ${LIVEKIT_HOST:-unset}"
echo "agent backend: ${INTERRUPT_AGENT_BACKEND:-gemini_realtime}"
echo "agent runtime mode: ${INTERRUPT_AGENT_RUNTIME_MODE:-online_full}"
echo "agent local text decision mode: ${INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE:-disabled}"
echo "agent local text provider: ${INTERRUPT_AGENT_LOCAL_TEXT_PROVIDER:-ollama}"
echo "agent local text model: ${INTERRUPT_AGENT_LOCAL_TEXT_MODEL:-qwen2.5:7b}"
echo "agent load threshold: ${INTERRUPT_AGENT_LOAD_THRESHOLD}"
echo "agent forced load: ${INTERRUPT_AGENT_FORCE_LOAD}"
echo "agent patched job token: ${INTERRUPT_AGENT_PATCH_JOB_TOKEN}"

ensure_navigation_bridge

cd "${ROOT_DIR}"
PYTHON_BIN="${INTERRUPT_PYTHON_BIN:-${DEFAULT_PYTHON_BIN}}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "room-agent python 不可执行: ${PYTHON_BIN}" >&2
  exit 1
fi
exec "${PYTHON_BIN}" -m src.agent start "$@"
