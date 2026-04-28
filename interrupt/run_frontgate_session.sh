#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/frontgate.log"
FRONTGATE_PYTHON="${INTERRUPT_FRONTGATE_PYTHON:-}"

if [[ -z "${FRONTGATE_PYTHON}" && ! -d "${VENV_DIR}" ]]; then
  echo "未找到虚拟环境，请先执行 ./bootstrap.sh"
  exit 1
fi

if [[ -z "${FRONTGATE_PYTHON}" ]]; then
  source "${VENV_DIR}/bin/activate"
  FRONTGATE_PYTHON="python"
fi

exec > >(tee -a "${LOG_FILE}") 2>&1
echo "===== $(date '+%F %T') run_frontgate_session.sh ====="
echo "frontgate python: ${FRONTGATE_PYTHON}"

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

FACTORY="${INTERRUPT_WAKE_WORD_FACTORY:-src.mock_wakeword:factory}"
SESSION_COMMAND="${INTERRUPT_FRONTGATE_SESSION_COMMAND:-${ROOT_DIR}/run_local_voice_agent.sh}"
SESSION_TIMEOUT="${INTERRUPT_FRONTGATE_SESSION_TIMEOUT:-0}"

echo "frontgate factory: ${FACTORY}"
echo "frontgate session command: ${SESSION_COMMAND}"
echo "frontgate session timeout: ${SESSION_TIMEOUT}"

ARGS=(
  --factory "${FACTORY}"
  --session-command "${SESSION_COMMAND}"
  --session-timeout "${SESSION_TIMEOUT}"
)

if [[ $# -gt 0 ]]; then
  ARGS+=("$@")
fi

exec "${FRONTGATE_PYTHON}" "${ROOT_DIR}/tools/wakeword_session_frontgate.py" "${ARGS[@]}"
