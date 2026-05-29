#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VALIDATION_VENV_DIR="${MINICPM_VLLM_COLDSTART_VENV_DIR:-/tmp/interrupt-minicpm-vllm-coldstart}"
VLLM_SPEC="${MINICPM_VLLM_LAB_VLLM_SPEC:-vllm}"
BOOTSTRAP_PYTHON="${MINICPM_VLLM_LAB_BOOTSTRAP_PYTHON:-python3}"

echo "===== $(date '+%F %T') run_validate_minicpm_v46_vllm_coldstart.sh ====="
echo "validation_venv: ${VALIDATION_VENV_DIR}"
echo "bootstrap_python: ${BOOTSTRAP_PYTHON}"
echo "vllm_spec: ${VLLM_SPEC}"

rm -rf "${VALIDATION_VENV_DIR}"

MINICPM_VLLM_LAB_VENV_DIR="${VALIDATION_VENV_DIR}" \
MINICPM_VLLM_LAB_BOOTSTRAP_PYTHON="${BOOTSTRAP_PYTHON}" \
MINICPM_VLLM_LAB_VLLM_SPEC="${VLLM_SPEC}" \
  "${ROOT_DIR}/run_setup_minicpm_vllm_lab.sh"

python3 "${ROOT_DIR}/tools/verify_minicpm_v46_vllm_backport.py" \
  --target-venv "${VALIDATION_VENV_DIR}"
