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
usage: ./scripts/mode.sh <online|offline|status>

Container-mode helper for the unified voice stack.
  online  -> apply stable online profile and recreate wakeword frontgate
  offline -> apply experimental offline profile and recreate wakeword frontgate
  status  -> print current dialogue mode from .env.local
EOF
}

ensure_env() {
  if [[ ! -f "${COMPOSE_ENV}" ]]; then
    echo "missing compose env: ${COMPOSE_ENV}" >&2
    echo "copy example first: cp ${ROOT_DIR}/deploy/compose/env.voice-stack.example ${COMPOSE_ENV}" >&2
    exit 1
  fi
}

apply_stack_mode() {
  "${ENSURE_COMPOSE}"
  "${COMPOSECTL}" --env-file "${COMPOSE_ENV}" -f "${COMPOSE_FILE}" up -d --build \
    ollama offline-brain online-brain wakeword-frontgate
  "${COMPOSECTL}" --env-file "${COMPOSE_ENV}" -f "${COMPOSE_FILE}" ps
}

main() {
  local mode="${1:-}"
  case "${mode}" in
    online|offline)
      ensure_env
      INTERRUPT_DIALOGUE_MODE_SKIP_RESTART=1 "${SWITCH_SCRIPT}" "${mode}"
      apply_stack_mode
      ;;
    status)
      INTERRUPT_DIALOGUE_MODE_SKIP_RESTART=1 "${SWITCH_SCRIPT}" status
      ;;
    -h|--help|help|"")
      usage
      ;;
    *)
      echo "unsupported mode: ${mode}" >&2
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
