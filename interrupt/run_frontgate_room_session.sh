#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "未找到虚拟环境，请先执行 ./bootstrap.sh"
  exit 1
fi

source "${VENV_DIR}/bin/activate"

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

RESOLVED_VLM_ENV="$("${ROOT_DIR}/.venv/bin/python" "${ROOT_DIR}/tools/resolve_vlm_runtime.py" --mode robot --allow-online-fallback)"
eval "${RESOLVED_VLM_ENV}"

echo "resolved VLM source: ${INTERRUPT_VLM_RESOLVED_SOURCE:-unset}"
echo "resolved VLM reason: ${INTERRUPT_VLM_RESOLVED_REASON:-unset}"
echo "resolved VLM provider: ${INTERRUPT_VLM_PROVIDER:-unset}"
echo "resolved VLM base_url: ${INTERRUPT_VLM_BASE_URL:-unset}"
echo "resolved VLM model: ${INTERRUPT_VLM_MODEL:-unset}"

cd "${ROOT_DIR}"
exec python tools/frontgate_room_session.py "$@"
