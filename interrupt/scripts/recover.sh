#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_ENV="${COMPOSE_ENV:-${ROOT_DIR}/deploy/compose/env.voice-stack}"
COMPOSE_FILE="${COMPOSE_FILE:-${ROOT_DIR}/deploy/compose/docker-compose.voice-stack.yaml}"
COMPOSECTL="${ROOT_DIR}/deploy/compose/composectl.sh"
ENSURE_COMPOSE="${ROOT_DIR}/deploy/compose/ensure_docker_compose.sh"
SWITCH_SCRIPT="${ROOT_DIR}/switch_dialogue_mode.sh"

usage() {
  cat <<'EOF'
usage: ./scripts/recover.sh [online|offline]

Recover the unified voice stack:
  1. ensure docker compose exists
  2. ensure required local directories exist
  3. start the relevant brain(s), wakeword frontgate, and ollama
  4. print container status

Default mode is read from interrupt/.env.local.
Passing online/offline applies that mode first, then restores the full stack once.
EOF
}

ensure_env() {
  if [[ ! -f "${COMPOSE_ENV}" ]]; then
    echo "missing compose env: ${COMPOSE_ENV}" >&2
    echo "copy example first: cp ${ROOT_DIR}/deploy/compose/env.voice-stack.example ${COMPOSE_ENV}" >&2
    exit 1
  fi
}

load_compose_env() {
  set -a
  # shellcheck disable=SC1090
  source "${COMPOSE_ENV}"
  set +a
}

ensure_dirs() {
  mkdir -p "${ROOT_DIR}/volumes/frontgate_shared"
  mkdir -p "${ROOT_DIR}/volumes/ollama-models"
}

current_mode() {
  python3 - "${ROOT_DIR}/.env.local" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
if not path.exists():
    print("online")
    raise SystemExit(0)
for raw in path.read_text(encoding="utf-8").splitlines():
    if raw.startswith("INTERRUPT_DIALOGUE_MODE="):
        print(raw.split("=", 1)[1].strip().strip("'").strip('"') or "online")
        raise SystemExit(0)
print("online")
PY
}

apply_requested_mode() {
  local mode="$1"
  INTERRUPT_DIALOGUE_MODE_SKIP_RESTART=1 "${SWITCH_SCRIPT}" "${mode}"
}

up_stack() {
  local mode="$1"
  "${ENSURE_COMPOSE}"
  case "${mode}" in
    online)
      "${COMPOSECTL}" --env-file "${COMPOSE_ENV}" -f "${COMPOSE_FILE}" up -d --build \
        online-brain wakeword-frontgate
      ;;
    offline)
      "${COMPOSECTL}" --env-file "${COMPOSE_ENV}" -f "${COMPOSE_FILE}" up -d --build \
        ollama offline-brain wakeword-frontgate
      ;;
    *)
      echo "unsupported mode for up_stack: ${mode}" >&2
      exit 1
      ;;
  esac
  "${COMPOSECTL}" --env-file "${COMPOSE_ENV}" -f "${COMPOSE_FILE}" ps
}

healthcheck() {
  local mode="$1"
  local online_url="http://127.0.0.1:${HOST_FRONTGATE_ONLINE_BRIDGE_PORT:-8787}/healthz"
  local offline_url="http://127.0.0.1:${HOST_FRONTGATE_OFFLINE_BRIDGE_PORT:-8788}/healthz"
  local ollama_url="http://127.0.0.1:11434/api/tags"
  echo "voice-stack healthcheck mode: ${mode}"
  curl -fsS "${online_url}" >/dev/null && echo "online-brain: ok" || echo "online-brain: not-ready"
  curl -fsS "${offline_url}" >/dev/null && echo "offline-brain: ok" || echo "offline-brain: not-ready"
  if [[ "${mode}" == "offline" ]]; then
    curl -fsS "${ollama_url}" >/dev/null && echo "ollama: ok" || echo "ollama: not-ready"
  fi
}

main() {
  local requested_mode="${1:-}"
  case "${requested_mode}" in
    online|offline)
      apply_requested_mode "${requested_mode}"
      ;;
    -h|--help|help)
      usage
      exit 0
      ;;
    "")
      ;;
    *)
      echo "unsupported mode: ${requested_mode}" >&2
      usage >&2
      exit 1
      ;;
  esac

  ensure_env
  ensure_dirs
  load_compose_env

  local effective_mode
  effective_mode="$(current_mode)"
  echo "voice-stack recover mode: ${effective_mode}"
  up_stack "${effective_mode}"
  healthcheck "${effective_mode}"
}

main "$@"
