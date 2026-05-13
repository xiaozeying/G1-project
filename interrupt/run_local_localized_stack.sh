#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export INTERRUPT_VLM_ENABLED="${INTERRUPT_VLM_ENABLED:-1}"
export INTERRUPT_VLM_PROVIDER="${INTERRUPT_VLM_PROVIDER:-ollama_native}"
export INTERRUPT_VLM_BASE_URL="${INTERRUPT_VLM_BASE_URL:-http://127.0.0.1:11434/v1}"
export INTERRUPT_VLM_MODEL="${INTERRUPT_VLM_MODEL:-gemma3:latest}"
export INTERRUPT_VLM_IMAGE_PATH="${INTERRUPT_VLM_IMAGE_PATH:-${ROOT_DIR}/../OM1/system_hw_test/front_image.jpg}"
export INTERRUPT_ENABLE_SAFE_ACTION_GATEWAY="${INTERRUPT_ENABLE_SAFE_ACTION_GATEWAY:-1}"

exec "${ROOT_DIR}/run_local_voice_agent.sh" "$@"
