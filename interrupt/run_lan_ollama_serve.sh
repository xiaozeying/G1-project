#!/usr/bin/env bash
set -euo pipefail

HOST_PORT="${OLLAMA_HOST:-0.0.0.0:11434}"

echo "===== $(date '+%F %T') run_lan_ollama_serve.sh ====="
echo "OLLAMA_HOST=${HOST_PORT}"
echo "tip: G1 可通过 http://<开发机局域网IP>:11434 访问"

export OLLAMA_HOST="${HOST_PORT}"
exec ollama serve
