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

PROMPT="${1:-挥挥手}"
QUESTION="${2:-你前面有什么？}"
shift 2 || true

RESOLVED_VLM_ENV="$("${ROOT_DIR}/.venv/bin/python" "${ROOT_DIR}/tools/resolve_vlm_runtime.py" --mode robot --allow-online-fallback)"
eval "${RESOLVED_VLM_ENV}"

export INTERRUPT_VLM_ENABLED="${INTERRUPT_VLM_ENABLED:-1}"

echo "===== $(date '+%F %T') run_robot_localized_stack_probe.sh ====="
echo "prompt: ${PROMPT}"
echo "question: ${QUESTION}"
echo "INTERRUPT_AGENT_RUNTIME_MODE=${INTERRUPT_AGENT_RUNTIME_MODE:-online_full}"
echo "INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE=${INTERRUPT_AGENT_LOCAL_TEXT_DECISION_MODE:-disabled}"
echo "INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL=${INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL:-unset}"
echo "INTERRUPT_AGENT_LOCAL_TEXT_MODEL=${INTERRUPT_AGENT_LOCAL_TEXT_MODEL:-unset}"
echo "INTERRUPT_VLM_RESOLVED_SOURCE=${INTERRUPT_VLM_RESOLVED_SOURCE:-unset}"
echo "INTERRUPT_VLM_RESOLVED_REASON=${INTERRUPT_VLM_RESOLVED_REASON:-unset}"
echo "INTERRUPT_VLM_PROVIDER=${INTERRUPT_VLM_PROVIDER:-unset}"
echo "INTERRUPT_VLM_BASE_URL=${INTERRUPT_VLM_BASE_URL:-unset}"
echo "INTERRUPT_VLM_MODEL=${INTERRUPT_VLM_MODEL:-unset}"

cd "${ROOT_DIR}"

python tools/check_env.py
python tools/agent_backend_probe.py
python -m tools.local_text_brain_smoke "${PROMPT}" \
  --backend "${INTERRUPT_AGENT_LOCAL_TEXT_BACKEND_OVERRIDE:-local_text_ollama}" \
  --base-url "${INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL:-http://192.168.100.48:11434}" \
  --model "${INTERRUPT_AGENT_LOCAL_TEXT_MODEL:-qwen2.5:7b}"
python tools/vlm_backend_probe.py --require-model
python tools/vlm_smoke_test.py "${QUESTION}" "$@"
