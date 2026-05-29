#!/usr/bin/env bash
set -euo pipefail

HOST_PORT="${OLLAMA_HOST:-0.0.0.0:11434}"
LOCAL_BIN_DIR="${INTERRUPT_LOCAL_TEXT_OLLAMA_BIN_DIR:-/data/HongTu/.local/bin}"
OLLAMA_MODELS_DIR="${OLLAMA_MODELS:-${INTERRUPT_LOCAL_TEXT_OLLAMA_MODELS_DIR:-/data/HongTu/ollama/models}}"

if [[ -d "${LOCAL_BIN_DIR}" ]]; then
  export PATH="${LOCAL_BIN_DIR}:${PATH}"
fi

echo "===== $(date '+%F %T') run_lan_ollama_serve.sh ====="
echo "OLLAMA_HOST=${HOST_PORT}"
echo "OLLAMA_MODELS=${OLLAMA_MODELS_DIR}"
echo "tip: G1 可通过 http://<开发机局域网IP>:11434 访问"

export OLLAMA_HOST="${HOST_PORT}"
export OLLAMA_MODELS="${OLLAMA_MODELS_DIR}"
exec ollama serve
