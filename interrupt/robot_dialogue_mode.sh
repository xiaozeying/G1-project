#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_HOST="${ROBOT_HOST:-unitree@192.168.100.30}"
REMOTE_ROOT="${ROBOT_INTERRUPT_ROOT:-/data/HongTu/interrupt}"
REMOTE_SCRIPT="${REMOTE_ROOT}/switch_dialogue_mode.sh"
LOCAL_SCRIPT="${ROOT_DIR}/switch_dialogue_mode.sh"
LOCAL_PROFILE_DIR="${ROOT_DIR}/config/dialogue_modes"
REMOTE_PROFILE_DIR="${REMOTE_ROOT}/config/dialogue_modes"

usage() {
  cat <<'EOF'
usage: ./robot_dialogue_mode.sh <online|offline|status>

Remote helper for robot dialogue mode switching.
Examples:
  ./robot_dialogue_mode.sh online
  ./robot_dialogue_mode.sh offline
  ./robot_dialogue_mode.sh status
EOF
}

mode="${1:-}"
if [[ -z "${mode}" || "${mode}" == "help" || "${mode}" == "--help" || "${mode}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ ! -f "${LOCAL_SCRIPT}" ]]; then
  echo "missing local helper: ${LOCAL_SCRIPT}" >&2
  exit 1
fi

if [[ ! -d "${LOCAL_PROFILE_DIR}" ]]; then
  echo "missing local profile dir: ${LOCAL_PROFILE_DIR}" >&2
  exit 1
fi

ssh -o StrictHostKeyChecking=no "${REMOTE_HOST}" "mkdir -p '${REMOTE_PROFILE_DIR}'"
scp -o StrictHostKeyChecking=no "${LOCAL_SCRIPT}" "${REMOTE_HOST}:${REMOTE_SCRIPT}"
scp -o StrictHostKeyChecking=no "${LOCAL_PROFILE_DIR}"/*.env "${REMOTE_HOST}:${REMOTE_PROFILE_DIR}/"
ssh -o StrictHostKeyChecking=no "${REMOTE_HOST}" "chmod +x '${REMOTE_SCRIPT}' && '${REMOTE_SCRIPT}' '${mode}'"
