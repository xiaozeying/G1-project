#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

PYTHON_BIN="${VLM_SERVER_PYTHON_BIN:-python3}"
MODEL_PATH="${VLM_SERVER_MODEL_PATH:-}"
HOST="${VLM_SERVER_HOST:-127.0.0.1}"
PORT="${VLM_SERVER_PORT:-9000}"
SERVED_MODEL_NAME="${VLM_SERVER_SERVED_MODEL_NAME:-}"
DP_SIZE="${VLM_SERVER_DP_SIZE:-1}"
TP_SIZE="${VLM_SERVER_TP_SIZE:-1}"
MEM_FRACTION="${VLM_SERVER_MEM_FRACTION_STATIC:-0.90}"
EXTRA_ARGS="${VLM_SERVER_EXTRA_ARGS:-}"

if [[ -z "${MODEL_PATH}" ]]; then
  echo "请先设置 VLM_SERVER_MODEL_PATH，例如："
  echo "  export VLM_SERVER_MODEL_PATH=/models/GLM-4.1V-9B"
  exit 1
fi

if ! "${PYTHON_BIN}" -c "import sglang" >/dev/null 2>&1; then
  echo "当前 Python 环境里未安装 sglang。"
  echo "请切换到已安装 sglang 的环境，或设置 VLM_SERVER_PYTHON_BIN 指向对应 Python。"
  exit 1
fi

CMD=(
  "${PYTHON_BIN}"
  -m
  sglang.launch_server
  --host "${HOST}"
  --port "${PORT}"
  --model-path "${MODEL_PATH}"
  --dp-size "${DP_SIZE}"
  --tp-size "${TP_SIZE}"
  --mem-fraction-static "${MEM_FRACTION}"
)

if [[ -n "${SERVED_MODEL_NAME}" ]]; then
  CMD+=(--served-model-name "${SERVED_MODEL_NAME}")
fi

if [[ -n "${EXTRA_ARGS}" ]]; then
  # shellcheck disable=SC2206
  EXTRA_PARTS=(${EXTRA_ARGS})
  CMD+=("${EXTRA_PARTS[@]}")
fi

echo "===== $(date '+%F %T') run_local_sglang_vision_server.sh ====="
echo "python: ${PYTHON_BIN}"
echo "model_path: ${MODEL_PATH}"
echo "host: ${HOST}"
echo "port: ${PORT}"
echo "served_model_name: ${SERVED_MODEL_NAME:-<default>}"
echo "dp_size: ${DP_SIZE}"
echo "tp_size: ${TP_SIZE}"
echo "mem_fraction_static: ${MEM_FRACTION}"
echo "extra_args: ${EXTRA_ARGS:-<none>}"

exec "${CMD[@]}"
