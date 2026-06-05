#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
BRIDGE_PYTHON="${VENV_DIR}/bin/python"
LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "${LOG_DIR}"
BRIDGE_NAME="${INTERRUPT_FRONTGATE_BRIDGE_NAME:-frontgate-online-bridge}"
LOG_FILE="${INTERRUPT_FRONTGATE_BRIDGE_LOG_FILE:-${LOG_DIR}/${BRIDGE_NAME}.log}"

if [[ ! -x "${BRIDGE_PYTHON}" ]]; then
  echo "未找到 bridge Python: ${BRIDGE_PYTHON}" >&2
  exit 1
fi

exec > >(tee -a "${LOG_FILE}") 2>&1
echo "===== $(date '+%F %T') ${BRIDGE_NAME} ====="

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

cd "${ROOT_DIR}"
exec "${BRIDGE_PYTHON}" tools/frontgate_online_bridge.py "$@"
