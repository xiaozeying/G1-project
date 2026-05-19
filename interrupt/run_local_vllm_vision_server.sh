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
PORT="${VLM_SERVER_PORT:-8000}"
SERVED_MODEL_NAME="${VLM_SERVER_SERVED_MODEL_NAME:-}"
DTYPE="${VLM_SERVER_DTYPE:-auto}"
MAX_MODEL_LEN="${VLM_SERVER_MAX_MODEL_LEN:-8192}"
GPU_MEMORY_UTILIZATION="${VLM_SERVER_GPU_MEMORY_UTILIZATION:-0.90}"
TENSOR_PARALLEL_SIZE="${VLM_SERVER_TENSOR_PARALLEL_SIZE:-1}"
EXTRA_ARGS="${VLM_SERVER_EXTRA_ARGS:-}"
LIMIT_MM_PER_PROMPT="${VLM_SERVER_LIMIT_MM_PER_PROMPT:-}"

if [[ -z "${MODEL_PATH}" ]]; then
  echo "请先设置 VLM_SERVER_MODEL_PATH，例如："
  echo "  export VLM_SERVER_MODEL_PATH=/models/Qwen2.5-VL-7B-Instruct"
  exit 1
fi

if ! "${PYTHON_BIN}" -c "import vllm" >/dev/null 2>&1; then
  echo "当前 Python 环境里未安装 vllm。"
  echo "请切换到已安装 vllm 的环境，或设置 VLM_SERVER_PYTHON_BIN 指向对应 Python。"
  exit 1
fi

CMD=(
  "${PYTHON_BIN}"
  -m
  vllm.entrypoints.openai.api_server
  --host "${HOST}"
  --port "${PORT}"
  --model "${MODEL_PATH}"
  --dtype "${DTYPE}"
  --max-model-len "${MAX_MODEL_LEN}"
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}"
  --tensor-parallel-size "${TENSOR_PARALLEL_SIZE}"
)

if [[ -n "${SERVED_MODEL_NAME}" ]]; then
  CMD+=(--served-model-name "${SERVED_MODEL_NAME}")
fi

if [[ -n "${LIMIT_MM_PER_PROMPT}" ]]; then
  CMD+=(--limit-mm-per-prompt "${LIMIT_MM_PER_PROMPT}")
fi

if [[ -n "${EXTRA_ARGS}" ]]; then
  # shellcheck disable=SC2206
  EXTRA_PARTS=(${EXTRA_ARGS})
  CMD+=("${EXTRA_PARTS[@]}")
fi

echo "===== $(date '+%F %T') run_local_vllm_vision_server.sh ====="
echo "python: ${PYTHON_BIN}"
echo "model_path: ${MODEL_PATH}"
echo "host: ${HOST}"
echo "port: ${PORT}"
echo "served_model_name: ${SERVED_MODEL_NAME:-<default>}"
echo "dtype: ${DTYPE}"
echo "max_model_len: ${MAX_MODEL_LEN}"
echo "gpu_memory_utilization: ${GPU_MEMORY_UTILIZATION}"
echo "tensor_parallel_size: ${TENSOR_PARALLEL_SIZE}"
echo "limit_mm_per_prompt: ${LIMIT_MM_PER_PROMPT:-<none>}"
echo "extra_args: ${EXTRA_ARGS:-<none>}"

exec "${CMD[@]}"
