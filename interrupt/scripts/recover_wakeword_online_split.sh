#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_ENV="${COMPOSE_ENV:-${ROOT_DIR}/deploy/compose/env.robot.wakeword-online}"
COMPOSE_FILE="${COMPOSE_FILE:-${ROOT_DIR}/deploy/compose/docker-compose.robot.wakeword-online.yaml}"
COMPOSECTL="${ROOT_DIR}/deploy/compose/composectl.sh"
ENSURE_COMPOSE="${ROOT_DIR}/deploy/compose/ensure_docker_compose.sh"

if [[ ! -f "${COMPOSE_ENV}" ]]; then
  example_env="${ROOT_DIR}/deploy/compose/env.robot.wakeword-online.example"
  echo "missing compose env: ${COMPOSE_ENV}" >&2
  echo "copy example first: cp ${example_env} ${COMPOSE_ENV}" >&2
  exit 1
fi

mkdir -p "${ROOT_DIR}/volumes/frontgate_shared"
"${ENSURE_COMPOSE}"
"${COMPOSECTL}" --env-file "${COMPOSE_ENV}" -f "${COMPOSE_FILE}" up -d --build online-brain wakeword-frontgate
"${COMPOSECTL}" --env-file "${COMPOSE_ENV}" -f "${COMPOSE_FILE}" ps
