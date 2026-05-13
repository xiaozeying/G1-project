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

QUESTION="${1:-这张图里有什么？}"
ACTION="${2:-high wave}"

export INTERRUPT_VLM_ENABLED="${INTERRUPT_VLM_ENABLED:-1}"
export INTERRUPT_VLM_PROVIDER="${INTERRUPT_VLM_PROVIDER:-ollama_native}"
export INTERRUPT_VLM_BASE_URL="${INTERRUPT_VLM_BASE_URL:-http://127.0.0.1:11434/v1}"
export INTERRUPT_VLM_MODEL="${INTERRUPT_VLM_MODEL:-gemma3:latest}"
export INTERRUPT_VLM_IMAGE_PATH="${INTERRUPT_VLM_IMAGE_PATH:-${ROOT_DIR}/../OM1/system_hw_test/front_image.jpg}"
export INTERRUPT_ENABLE_SAFE_ACTION_GATEWAY="${INTERRUPT_ENABLE_SAFE_ACTION_GATEWAY:-1}"

echo "===== $(date '+%F %T') run_local_localized_stack_probe.sh ====="
echo "question: ${QUESTION}"
echo "action: ${ACTION}"
echo "INTERRUPT_VLM_PROVIDER=${INTERRUPT_VLM_PROVIDER}"
echo "INTERRUPT_VLM_BASE_URL=${INTERRUPT_VLM_BASE_URL}"
echo "INTERRUPT_VLM_MODEL=${INTERRUPT_VLM_MODEL:-unset}"
echo "INTERRUPT_ENABLE_SAFE_ACTION_GATEWAY=${INTERRUPT_ENABLE_SAFE_ACTION_GATEWAY}"
echo "INTERRUPT_VLM_IMAGE_PATH=${INTERRUPT_VLM_IMAGE_PATH}"

cd "${ROOT_DIR}"

python tools/check_env.py
python tools/vlm_backend_probe.py
python tools/vlm_smoke_test.py "${QUESTION}" --image "${INTERRUPT_VLM_IMAGE_PATH}" --structured
python tools/safe_action_gateway_smoke.py "${ACTION}" --image "${INTERRUPT_VLM_IMAGE_PATH}"
