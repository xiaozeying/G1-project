#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LAB_VENV_DIR="${MINICPM_VLLM_LAB_VENV_DIR:-${ROOT_DIR}/.venv-minicpm-vllm-lab}"
PYTHON_BIN="${MINICPM_VLLM_LAB_BOOTSTRAP_PYTHON:-python3}"
VLLM_SPEC="${MINICPM_VLLM_LAB_VLLM_SPEC:-vllm}"

echo "===== $(date '+%F %T') run_setup_minicpm_vllm_lab.sh ====="
echo "python: ${PYTHON_BIN}"
echo "venv: ${LAB_VENV_DIR}"
echo "vllm_spec: ${VLLM_SPEC}"

"${PYTHON_BIN}" -m venv "${LAB_VENV_DIR}"

"${LAB_VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
"${LAB_VENV_DIR}/bin/pip" install "${VLLM_SPEC}"

"${LAB_VENV_DIR}/bin/python" - <<'PY'
import importlib

for name in ("vllm", "transformers", "torch"):
    module = importlib.import_module(name)
    print(f"{name}={module.__version__}")
PY

if [[ -x "${ROOT_DIR}/run_backport_minicpm_v46_vllm_lab.sh" ]]; then
  MINICPM_VLLM_LAB_VENV_DIR="${LAB_VENV_DIR}" \
    "${ROOT_DIR}/run_backport_minicpm_v46_vllm_lab.sh" || {
      echo "WARN: MiniCPM-V 4.6 backport step did not complete."
      echo "      You can rerun it manually with ./run_backport_minicpm_v46_vllm_lab.sh"
    }
fi
