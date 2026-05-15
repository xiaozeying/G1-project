#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "未找到虚拟环境，请先执行 ./bootstrap.sh"
  exit 1
fi

source "${VENV_DIR}/bin/activate"

PROMPT="${1:-挥挥手}"
shift || true

export INTERRUPT_AGENT_BACKEND="${INTERRUPT_AGENT_BACKEND:-local_text_ollama}"
export INTERRUPT_AGENT_LOCAL_TEXT_PROVIDER="${INTERRUPT_AGENT_LOCAL_TEXT_PROVIDER:-ollama}"
export INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL="${INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL:-http://192.168.100.48:11434}"
export INTERRUPT_AGENT_LOCAL_TEXT_MODEL="${INTERRUPT_AGENT_LOCAL_TEXT_MODEL:-qwen2.5:7b}"

echo "===== $(date '+%F %T') run_robot_text_brain_smoke.sh ====="
echo "backend: ${INTERRUPT_AGENT_BACKEND}"
echo "provider: ${INTERRUPT_AGENT_LOCAL_TEXT_PROVIDER}"
echo "base_url: ${INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL}"
echo "model: ${INTERRUPT_AGENT_LOCAL_TEXT_MODEL}"
echo "prompt: ${PROMPT}"

cd "${ROOT_DIR}"
exec python -m tools.local_text_brain_smoke "${PROMPT}" "$@"
