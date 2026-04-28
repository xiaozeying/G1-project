#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/web.log"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "未找到虚拟环境，请先执行 ./bootstrap.sh"
  exit 1
fi

source "${VENV_DIR}/bin/activate"

exec > >(tee -a "${LOG_FILE}") 2>&1
echo "===== $(date '+%F %T') run_web_playground.sh ====="

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

exec python "${ROOT_DIR}/dev_server.py"
