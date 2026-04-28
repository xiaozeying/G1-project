#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"

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

if [[ -n "${HTTP_PROXY:-}" && -z "${http_proxy:-}" ]]; then
  export http_proxy="${HTTP_PROXY}"
fi
if [[ -n "${HTTPS_PROXY:-}" && -z "${https_proxy:-}" ]]; then
  export https_proxy="${HTTPS_PROXY}"
fi
if [[ -n "${ALL_PROXY:-}" && -z "${all_proxy:-}" ]]; then
  export all_proxy="${ALL_PROXY}"
fi

python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"

python -m pip install --upgrade pip setuptools wheel
python -m pip install -r "${ROOT_DIR}/requirements.txt"

echo
echo "环境已安装到 ${VENV_DIR}"
echo "下一步："
echo "  1. source ${VENV_DIR}/bin/activate"
echo "  2. cp ${ROOT_DIR}/.env.example ${ROOT_DIR}/.env.local"
echo "  3. 编辑 .env.local，填入 GEMINI_API_KEY"
echo "  4. ./run_livekit_server.sh"
echo "  5. ./run_local_voice_agent.sh"
echo "  6. ./run_web_playground.sh"
