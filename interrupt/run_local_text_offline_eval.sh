#!/usr/bin/env bash
set -euo pipefail

INTERRUPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${INTERRUPT_DIR}/.." && pwd)"
OM1_DIR="${ROOT_DIR}/OM1"
OFFLINE_EVAL_DIR="${ROOT_DIR}/offline_eval"

MODE="${1:-batch}"
if [[ $# -gt 0 ]]; then
  shift
fi

OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:7b}"
OLLAMA_TEMPERATURE="${OLLAMA_TEMPERATURE:-0.2}"
OLLAMA_NUM_CTX="${OLLAMA_NUM_CTX:-4096}"
OLLAMA_TIMEOUT="${OLLAMA_TIMEOUT:-60}"
LOCAL_EVAL_MOCK_PORT="${LOCAL_EVAL_MOCK_PORT:-8879}"
RESULTS_FILE="${RESULTS_FILE:-${OFFLINE_EVAL_DIR}/results_auto_${OLLAMA_MODEL//[:\/]/_}.csv}"
RUNTIME_LOG="${RUNTIME_LOG:-${OFFLINE_EVAL_DIR}/runtime_auto_${OLLAMA_MODEL//[:\/]/_}.log}"
PYTHON_BIN="${PYTHON_BIN:-${OM1_DIR}/.venv_x86/bin/python}"
CONFIG_NAME="${CONFIG_NAME:-unitree_g1_text_arm_led_ollama_local_eval}"

PASS_THROUGH_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)
      OLLAMA_MODEL="$2"
      shift 2
      ;;
    --ollama-base-url)
      OLLAMA_BASE_URL="$2"
      shift 2
      ;;
    --mock-port)
      LOCAL_EVAL_MOCK_PORT="$2"
      shift 2
      ;;
    --results)
      RESULTS_FILE="$2"
      shift 2
      ;;
    --runtime-log)
      RUNTIME_LOG="$2"
      shift 2
      ;;
    --python-bin)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --config)
      CONFIG_NAME="$2"
      shift 2
      ;;
    *)
      PASS_THROUGH_ARGS+=("$1")
      shift
      ;;
  esac
done

echo "===== $(date '+%F %T') run_local_text_offline_eval.sh ====="
echo "mode: ${MODE}"
echo "ollama_base_url: ${OLLAMA_BASE_URL}"
echo "ollama_model: ${OLLAMA_MODEL}"
echo "mock_port: ${LOCAL_EVAL_MOCK_PORT}"
echo "results_file: ${RESULTS_FILE}"
echo "runtime_log: ${RUNTIME_LOG}"

require_file() {
  local path="$1"
  if [[ ! -e "${path}" ]]; then
    echo "missing required path: ${path}" >&2
    exit 1
  fi
}

require_file "${OM1_DIR}/scripts/run_local_offline_eval.sh"
require_file "${OFFLINE_EVAL_DIR}/run_phase1_batch.py"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl not found; cannot probe local Ollama service" >&2
  exit 1
fi

if ! curl -fsS "${OLLAMA_BASE_URL%/}/api/tags" >/dev/null; then
  echo "local ollama probe failed: ${OLLAMA_BASE_URL%/}/api/tags" >&2
  echo "hint: start ollama first, e.g. \`OLLAMA_HOST=0.0.0.0:11434 ollama serve\`" >&2
  exit 1
fi

export OLLAMA_BASE_URL
export OLLAMA_MODEL
export OLLAMA_TEMPERATURE
export OLLAMA_NUM_CTX
export OLLAMA_TIMEOUT
export LOCAL_EVAL_MOCK_PORT

case "${MODE}" in
  interactive)
    echo "starting interactive local text eval runtime"
    echo "send prompts from another terminal with:"
    echo "  python ${OM1_DIR}/scripts/send_mock_input.py \"你好\" --port ${LOCAL_EVAL_MOCK_PORT}"
    exec "${OM1_DIR}/scripts/run_local_offline_eval.sh" "${CONFIG_NAME}" "${PASS_THROUGH_ARGS[@]}"
    ;;
  batch)
    require_file "${PYTHON_BIN}"
    mkdir -p "$(dirname "${RESULTS_FILE}")"
    mkdir -p "$(dirname "${RUNTIME_LOG}")"
    exec "${PYTHON_BIN}" "${OFFLINE_EVAL_DIR}/run_phase1_batch.py" \
      --config "${CONFIG_NAME}" \
      --model "${OLLAMA_MODEL}" \
      --port "${LOCAL_EVAL_MOCK_PORT}" \
      --ollama-base-url "${OLLAMA_BASE_URL}" \
      --temperature "${OLLAMA_TEMPERATURE}" \
      --num-ctx "${OLLAMA_NUM_CTX}" \
      --timeout "${OLLAMA_TIMEOUT}" \
      --results "${RESULTS_FILE}" \
      --runtime-log "${RUNTIME_LOG}" \
      "${PASS_THROUGH_ARGS[@]}"
    ;;
  *)
    echo "unsupported mode: ${MODE}" >&2
    echo "usage: ./run_local_text_offline_eval.sh [batch|interactive]" >&2
    exit 1
    ;;
esac
