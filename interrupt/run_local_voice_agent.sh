#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/agent.log"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "未找到虚拟环境，请先执行 ./bootstrap.sh"
  exit 1
fi

source "${VENV_DIR}/bin/activate"

exec > >(tee -a "${LOG_FILE}") 2>&1
echo "===== $(date '+%F %T') run_local_voice_agent.sh ====="

if [[ -f "${ROOT_DIR}/.env.local" ]]; then
  set -a
  source "${ROOT_DIR}/.env.local"
  set +a
fi

if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  source "${ROOT_DIR}/.env"
  set +a
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
if [[ -n "${WSS_PROXY:-}" && -z "${wss_proxy:-}" ]]; then
  export wss_proxy="${WSS_PROXY}"
fi
if [[ -n "${WS_PROXY:-}" && -z "${ws_proxy:-}" ]]; then
  export ws_proxy="${WS_PROXY}"
fi

LOCAL_NO_PROXY="127.0.0.1,localhost,::1"
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

if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  echo "GEMINI_API_KEY 未设置。请先在 ${ROOT_DIR}/.env.local 或 ${ROOT_DIR}/.env 中填写。"
  exit 1
fi

cd "${ROOT_DIR}"

if [[ $# -gt 0 ]]; then
  exec python -m src.agent "$@"
fi

ARGS=(console)

if [[ -n "${INTERRUPT_INPUT_DEVICE:-}" ]]; then
  ARGS+=(--input-device "${INTERRUPT_INPUT_DEVICE}")
fi

if [[ -n "${INTERRUPT_OUTPUT_DEVICE:-}" ]]; then
  ARGS+=(--output-device "${INTERRUPT_OUTPUT_DEVICE}")
fi

if [[ "${INTERRUPT_TEXT_MODE:-}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
  ARGS+=(--text)
fi

if [[ "${INTERRUPT_RECORD:-}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
  ARGS+=(--record)
fi

exec python -m src.agent "${ARGS[@]}"
