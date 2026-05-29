#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OM1_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_VENV="${OM1_G1_RUNTIME_VENV:-${OM1_ROOT}/.venv-g1-runtime}"
SYSTEM_PYTHON="${OM1_G1_RUNTIME_SYSTEM_PYTHON:-$(command -v python3)}"
CREATE_VENV_ARGS=()

log() {
  printf '[g1-runtime] %s\n' "$*" >&2
}

die() {
  printf '[g1-runtime][error] %s\n' "$*" >&2
  exit 1
}

detect_cyclonedds_prefix() {
  local candidate
  for candidate in \
    /usr/local \
    /usr \
    /opt/cyclonedds \
    "${HOME}/cyclonedds/install"
  do
    if [[ -e "${candidate}/lib/libddsc.so" || -e "${candidate}/lib/libddsc.so.0" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

python_has_cyclonedds() {
  local python_bin="$1"
  "${python_bin}" - <<'PY' >/dev/null 2>&1
import cyclonedds
PY
}

runtime_python_works() {
  local python_bin="$1"
  local om1_root="$2"
  OM1_ROOT="${om1_root}" LD_LIBRARY_PATH="/usr/local/lib:${LD_LIBRARY_PATH:-}" "${python_bin}" - <<'PY' >/dev/null 2>&1
import os
import sys
from pathlib import Path

root = Path(os.environ["OM1_ROOT"])
sys.path.insert(0, str(root / "src"))
import cyclonedds  # noqa: F401
from unitree.unitree_sdk2py.g1.audio.g1_audio_client import AudioClient  # noqa: F401
from unitree.unitree_sdk2py.g1.arm.g1_arm_action_client import G1ArmActionClient  # noqa: F401
print("ok")
PY
}

recreate_runtime_venv() {
  if [[ -d "${TARGET_VENV}" ]]; then
    log "recreating runtime venv at ${TARGET_VENV}"
    rm -rf "${TARGET_VENV}"
  fi
  "${SYSTEM_PYTHON}" -m venv "${CREATE_VENV_ARGS[@]}" "${TARGET_VENV}"
}

create_runtime_venv() {
  if python_has_cyclonedds "${SYSTEM_PYTHON}"; then
    CREATE_VENV_ARGS=(--system-site-packages)
    log "system python already provides cyclonedds, reusing system site-packages"
  else
    CREATE_VENV_ARGS=()
  fi
  if [[ ! -x "${TARGET_VENV}/bin/python" ]]; then
    log "creating runtime venv at ${TARGET_VENV}"
    recreate_runtime_venv
  fi

  if [[ "${CREATE_VENV_ARGS[*]:-}" == *"--system-site-packages"* ]] && ! python_has_cyclonedds "${TARGET_VENV}/bin/python"; then
    log "existing runtime venv is missing system site-packages, recreating"
    recreate_runtime_venv
  fi
}

install_python_cyclonedds() {
  local prefix=""
  prefix="$(detect_cyclonedds_prefix || true)"
  if [[ -n "${prefix}" ]]; then
    export CYCLONEDDS_HOME="${prefix}"
    export CMAKE_PREFIX_PATH="${prefix}${CMAKE_PREFIX_PATH:+:${CMAKE_PREFIX_PATH}}"
    export LD_LIBRARY_PATH="${prefix}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
    log "using CycloneDDS prefix ${prefix}"
  else
    log "CycloneDDS prefix auto-detection failed, trying pip build with current environment"
  fi

  "${TARGET_VENV}/bin/python" -m pip install --upgrade pip setuptools wheel >/dev/null
  "${TARGET_VENV}/bin/python" -m pip install --no-cache-dir "cyclonedds==0.10.2"
}

main() {
  [[ -n "${SYSTEM_PYTHON}" ]] || die "python3 not found"
  [[ -d "${OM1_ROOT}/src" ]] || die "OM1 src directory is missing under ${OM1_ROOT}"

  if runtime_python_works "${SYSTEM_PYTHON}" "${OM1_ROOT}"; then
    log "system python already satisfies G1 runtime imports"
    printf '%s\n' "${SYSTEM_PYTHON}"
    return 0
  fi

  create_runtime_venv

  if ! python_has_cyclonedds "${TARGET_VENV}/bin/python"; then
    log "cyclonedds missing in runtime venv, installing"
    install_python_cyclonedds
  fi

  runtime_python_works "${TARGET_VENV}/bin/python" "${OM1_ROOT}" \
    || die "runtime python validation failed for ${TARGET_VENV}/bin/python"

  printf '%s\n' "${TARGET_VENV}/bin/python"
}

main "$@"
