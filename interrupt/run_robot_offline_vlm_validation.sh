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

QUESTION="${1:-你前面有什么？}"
shift || true

RESOLVED_VLM_ENV="$("${ROOT_DIR}/.venv/bin/python" "${ROOT_DIR}/tools/resolve_vlm_runtime.py" --mode robot --require-offline)"
eval "${RESOLVED_VLM_ENV}"

export INTERRUPT_VLM_ENABLED="${INTERRUPT_VLM_ENABLED:-1}"

echo "===== $(date '+%F %T') run_robot_offline_vlm_validation.sh ====="
echo "question: ${QUESTION}"
echo "INTERRUPT_VLM_ENABLED=${INTERRUPT_VLM_ENABLED}"
echo "INTERRUPT_VLM_RESOLVED_SOURCE=${INTERRUPT_VLM_RESOLVED_SOURCE:-unset}"
echo "INTERRUPT_VLM_RESOLVED_REASON=${INTERRUPT_VLM_RESOLVED_REASON:-unset}"
echo "INTERRUPT_VLM_PROVIDER=${INTERRUPT_VLM_PROVIDER}"
echo "INTERRUPT_VLM_BASE_URL=${INTERRUPT_VLM_BASE_URL:-unset}"
echo "INTERRUPT_VLM_MODEL=${INTERRUPT_VLM_MODEL:-unset}"
echo "UNITREE_G1_CAMERA_DEVICE=${UNITREE_G1_CAMERA_DEVICE:-${INTERRUPT_VLM_CAMERA_DEVICE:-unset}}"

cd "${ROOT_DIR}"

python tools/check_env.py
python tools/vlm_backend_probe.py --require-model
python tools/vlm_smoke_test.py "${QUESTION}" "$@"
