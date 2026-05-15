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

RESOLVED_VLM_ENV="$("${ROOT_DIR}/.venv/bin/python" "${ROOT_DIR}/tools/resolve_vlm_runtime.py" --mode local --allow-online-fallback)"
eval "${RESOLVED_VLM_ENV}"

export INTERRUPT_VLM_ENABLED="${INTERRUPT_VLM_ENABLED:-1}"
export INTERRUPT_VLM_IMAGE_PATH="${INTERRUPT_VLM_IMAGE_PATH:-${ROOT_DIR}/../OM1/system_hw_test/front_image.jpg}"
export INTERRUPT_ENABLE_SAFE_ACTION_GATEWAY="${INTERRUPT_ENABLE_SAFE_ACTION_GATEWAY:-1}"

exec "${ROOT_DIR}/run_local_voice_agent.sh" "$@"
