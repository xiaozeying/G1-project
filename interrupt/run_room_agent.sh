#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/room-agent.log"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "未找到虚拟环境，请先执行 ./bootstrap.sh"
  exit 1
fi

source "${VENV_DIR}/bin/activate"

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

cd "${ROOT_DIR}"
exec python -m src.agent start "$@"
