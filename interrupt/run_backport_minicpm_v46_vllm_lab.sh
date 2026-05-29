#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TARGET_VENV_DIR="${MINICPM_VLLM_LAB_VENV_DIR:-${ROOT_DIR}/.venv-minicpm-vllm-lab}"
TARGET_SITE_PACKAGES="${MINICPM_VLLM_LAB_SITE_PACKAGES:-}"
SOURCE_MINICPMV46="${MINICPM_VLLM_LAB_SOURCE_MINICPMV46:-}"

echo "===== $(date '+%F %T') run_backport_minicpm_v46_vllm_lab.sh ====="
echo "target_venv_dir: ${TARGET_VENV_DIR}"
echo "target_site_packages: ${TARGET_SITE_PACKAGES:-<auto>}"
echo "source_minicpmv46: ${SOURCE_MINICPMV46:-<auto>}"

exec python3 "${ROOT_DIR}/tools/backport_minicpm_v46_vllm_lab.py" \
  --target-venv "${TARGET_VENV_DIR}" \
  --target-site-packages "${TARGET_SITE_PACKAGES}" \
  --source-minicpmv46 "${SOURCE_MINICPMV46}"
