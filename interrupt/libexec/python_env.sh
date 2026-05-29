#!/usr/bin/env bash

interrupt_activate_python_env() {
  local root_dir="$1"
  local venv_dir="${INTERRUPT_VENV_DIR:-${root_dir}/.venv}"
  local python_bin_override="${INTERRUPT_PYTHON_BIN:-}"

  if [[ -n "${python_bin_override}" ]]; then
    if [[ ! -x "${python_bin_override}" ]]; then
      echo "指定的 INTERRUPT_PYTHON_BIN 不可执行: ${python_bin_override}" >&2
      return 1
    fi
    export PATH="$(dirname "${python_bin_override}"):${PATH}"
    return 0
  fi

  if [[ ! -d "${venv_dir}" ]]; then
    echo "未找到虚拟环境，请先执行 ./bootstrap.sh 或设置 INTERRUPT_PYTHON_BIN" >&2
    return 1
  fi

  # shellcheck disable=SC1090
  source "${venv_dir}/bin/activate"
}
