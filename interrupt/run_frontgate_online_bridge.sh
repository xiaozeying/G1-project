#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
BRIDGE_PYTHON="${VENV_DIR}/bin/python"
LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/frontgate-online-bridge.log"

if [[ ! -x "${BRIDGE_PYTHON}" ]]; then
  echo "未找到 online bridge Python: ${BRIDGE_PYTHON}" >&2
  exit 1
fi

exec > >(tee -a "${LOG_FILE}") 2>&1
echo "===== $(date '+%F %T') run_frontgate_online_bridge.sh ====="

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
