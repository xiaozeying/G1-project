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

PROFILE="${INTERRUPT_OFFLINE_PROFILE:-}"
if [[ -n "${PROFILE}" ]]; then
  eval "$("${ROOT_DIR}/run_apply_offline_model_profile.sh" "${PROFILE}" robot)"
fi

RESOLVED_VLM_ENV="$("${ROOT_DIR}/.venv/bin/python" "${ROOT_DIR}/tools/resolve_vlm_runtime.py" --mode robot --require-offline)"
eval "${RESOLVED_VLM_ENV}"

export INTERRUPT_AGENT_RUNTIME_MODE="${INTERRUPT_AGENT_RUNTIME_MODE:-offline_singlebox}"
export INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE="${INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE:-prefer_tools}"
export INTERRUPT_VLM_ENABLED="${INTERRUPT_VLM_ENABLED:-1}"
export UNITREE_G1_CAMERA_DEVICE="${UNITREE_G1_CAMERA_DEVICE:-/dev/video2}"

echo "===== $(date '+%F %T') run_robot_offline_singlebox_acceptance.sh ====="
echo "profile: ${PROFILE:-<current_env>}"
echo "runtime_mode: ${INTERRUPT_AGENT_RUNTIME_MODE}"
echo "local_text_decision_mode: ${INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE}"
echo "local_text_base_url: ${INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL:-unset}"
echo "local_text_model: ${INTERRUPT_AGENT_LOCAL_TEXT_MODEL:-unset}"
echo "vlm_provider: ${INTERRUPT_VLM_PROVIDER:-unset}"
echo "vlm_base_url: ${INTERRUPT_VLM_BASE_URL:-unset}"
echo "vlm_model: ${INTERRUPT_VLM_MODEL:-unset}"
echo "camera_device: ${UNITREE_G1_CAMERA_DEVICE}"

cd "${ROOT_DIR}"
exec python tools/offline_singlebox_acceptance.py "$@"
