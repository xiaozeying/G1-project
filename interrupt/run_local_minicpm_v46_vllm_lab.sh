#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export VLM_SERVER_PYTHON_BIN="${VLM_SERVER_PYTHON_BIN:-${ROOT_DIR}/.venv-minicpm-vllm-lab/bin/python}"
export VLM_SERVER_MODEL_PATH="${VLM_SERVER_MODEL_PATH:-openbmb/MiniCPM-V-4.6}"
export VLM_SERVER_HOST="${VLM_SERVER_HOST:-127.0.0.1}"
export VLM_SERVER_PORT="${VLM_SERVER_PORT:-8000}"
export VLM_SERVER_SERVED_MODEL_NAME="${VLM_SERVER_SERVED_MODEL_NAME:-MiniCPM-V-4_6}"
export VLM_SERVER_DTYPE="${VLM_SERVER_DTYPE:-auto}"
export VLM_SERVER_MAX_MODEL_LEN="${VLM_SERVER_MAX_MODEL_LEN:-2048}"
export VLM_SERVER_GPU_MEMORY_UTILIZATION="${VLM_SERVER_GPU_MEMORY_UTILIZATION:-0.90}"
export VLM_SERVER_TENSOR_PARALLEL_SIZE="${VLM_SERVER_TENSOR_PARALLEL_SIZE:-1}"
export VLM_SERVER_LIMIT_MM_PER_PROMPT="${VLM_SERVER_LIMIT_MM_PER_PROMPT:-{\"image\":1}}"
export VLM_SERVER_EXTRA_ARGS="${VLM_SERVER_EXTRA_ARGS:---enable-auto-tool-choice --tool-call-parser qwen3_coder --enforce-eager --skip-mm-profiling}"
# On this host, FlashInfer sampling falls back to JIT and requires `nvcc`.
# Disable it by default for the MiniCPM lab flow unless the caller opts in.
export VLLM_USE_FLASHINFER_SAMPLER="${VLLM_USE_FLASHINFER_SAMPLER:-0}"
# On the 8GB lab GPU, CUDA graph memory estimation can consume the remaining
# KV-cache headroom even after MiniCPM-V 4.6 is otherwise runnable.
export VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS="${VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS:-0}"

exec "${ROOT_DIR}/run_local_vllm_vision_server.sh"
