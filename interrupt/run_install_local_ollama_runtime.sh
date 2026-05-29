#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_ROOT="${INTERRUPT_LOCAL_TEXT_OLLAMA_RUNTIME_DIR:-/data/HongTu/ollama-runtime}"
BIN_DIR="${INTERRUPT_LOCAL_TEXT_OLLAMA_BIN_DIR:-/data/HongTu/.local/bin}"
MODELS_DIR="${INTERRUPT_LOCAL_TEXT_OLLAMA_MODELS_DIR:-/data/HongTu/ollama/models}"
DOWNLOAD_BASE_URL="${INTERRUPT_LOCAL_TEXT_OLLAMA_DOWNLOAD_BASE_URL:-https://ollama.com/download}"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

echo "===== $(date '+%F %T') run_install_local_ollama_runtime.sh ====="
echo "install_root: ${INSTALL_ROOT}"
echo "bin_dir: ${BIN_DIR}"
echo "models_dir: ${MODELS_DIR}"

mkdir -p "${INSTALL_ROOT}" "${BIN_DIR}" "${MODELS_DIR}"

download_and_extract() {
  local base_url="$1"
  local filename="$2"
  local target="$3"
  local zst_url="${base_url}/${filename}.tar.zst"
  local tgz_url="${base_url}/${filename}.tgz"

  if curl -fsI -L "${zst_url}" >/dev/null 2>&1; then
    echo "downloading: ${zst_url}"
    curl -fL --retry 3 --retry-delay 2 "${zst_url}" | zstd -d | tar -xf - -C "${target}"
    return 0
  fi

  echo "downloading: ${tgz_url}"
  curl -fL --retry 3 --retry-delay 2 "${tgz_url}" | tar -xzf - -C "${target}"
}

download_and_extract "${DOWNLOAD_BASE_URL}" "ollama-linux-arm64" "${INSTALL_ROOT}"

if [[ -f /etc/nv_tegra_release ]]; then
  echo "jetson detected: applying JetPack add-on runtime"
  if grep -q 'R36' /etc/nv_tegra_release; then
    download_and_extract "${DOWNLOAD_BASE_URL}" "ollama-linux-arm64-jetpack6" "${INSTALL_ROOT}"
  elif grep -q 'R35' /etc/nv_tegra_release; then
    download_and_extract "${DOWNLOAD_BASE_URL}" "ollama-linux-arm64-jetpack5" "${INSTALL_ROOT}"
  fi
fi

if [[ ! -x "${INSTALL_ROOT}/bin/ollama" ]]; then
  echo "ollama binary missing after install: ${INSTALL_ROOT}/bin/ollama" >&2
  exit 1
fi

ln -sfn "${INSTALL_ROOT}/bin/ollama" "${BIN_DIR}/ollama"

echo "linked ollama -> ${BIN_DIR}/ollama"
"${BIN_DIR}/ollama" --version

cat <<EOF

Install complete.
Suggested exports:
  export PATH="${BIN_DIR}:\$PATH"
  export OLLAMA_MODELS="${MODELS_DIR}"

Next steps:
  1. bash ./run_lan_ollama_serve.sh
  2. ollama pull gemma3:latest
EOF
