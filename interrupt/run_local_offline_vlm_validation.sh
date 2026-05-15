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
shift || true

RESOLVED_VLM_ENV="$("${ROOT_DIR}/.venv/bin/python" "${ROOT_DIR}/tools/resolve_vlm_runtime.py" --mode local --require-offline)"
eval "${RESOLVED_VLM_ENV}"

export INTERRUPT_VLM_ENABLED="${INTERRUPT_VLM_ENABLED:-1}"
export INTERRUPT_VLM_IMAGE_PATH="${INTERRUPT_VLM_IMAGE_PATH:-${ROOT_DIR}/../OM1/system_hw_test/front_image.jpg}"

echo "===== $(date '+%F %T') run_local_offline_vlm_validation.sh ====="
echo "question: ${QUESTION}"
echo "INTERRUPT_VLM_ENABLED=${INTERRUPT_VLM_ENABLED}"
echo "INTERRUPT_VLM_RESOLVED_SOURCE=${INTERRUPT_VLM_RESOLVED_SOURCE:-unset}"
echo "INTERRUPT_VLM_RESOLVED_REASON=${INTERRUPT_VLM_RESOLVED_REASON:-unset}"
echo "INTERRUPT_VLM_PROVIDER=${INTERRUPT_VLM_PROVIDER}"
echo "INTERRUPT_VLM_BASE_URL=${INTERRUPT_VLM_BASE_URL}"
echo "INTERRUPT_VLM_MODEL=${INTERRUPT_VLM_MODEL:-unset}"
echo "INTERRUPT_VLM_IMAGE_PATH=${INTERRUPT_VLM_IMAGE_PATH}"

cd "${ROOT_DIR}"

python tools/check_env.py
python tools/vlm_backend_probe.py
python tools/vlm_smoke_test.py "${QUESTION}" --image "${INTERRUPT_VLM_IMAGE_PATH}" "$@"
