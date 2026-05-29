#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT_DIR="${COMPOSE_PROJECT_DIR:-${ROOT_DIR}}"

if docker compose version >/dev/null 2>&1; then
  exec docker compose "$@"
fi

if command -v docker-compose >/dev/null 2>&1; then
  exec docker-compose "$@"
fi

printf 'docker compose is unavailable. Run %s/deploy/compose/ensure_docker_compose.sh first.\n' "${ROOT_DIR}" >&2
exit 1
