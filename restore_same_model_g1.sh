#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INTERRUPT_DIR="${INTERRUPT_DIR:-${ROOT_DIR}/interrupt}"
ROBOT_HOME="${ROBOT_HOME:-${ROOT_DIR}}"
OM1_DIR="${OM1_DIR:-${ROBOT_HOME}/OM1}"
WAKEWORD_DIR="${WAKEWORD_DIR:-${ROBOT_HOME}/g1-wakeword}"
HOME_LINK="${HOME}/HongTu"

usage() {
  cat <<'EOF'
usage: ./restore_same_model_g1.sh [--verify-only] [--enable-compose] [--skip-bootstrap]

Repo-root restore entrypoint for the same G1 robot model after reflashing.

This wrapper:
  1. normalizes repo-root paths
  2. ensures ~/HongTu points at the actual repo root
  3. checks whether tracked and non-tracked restore assets are present
  4. delegates the actual runtime restore to interrupt/restore_robot_voice_chain.sh

Notes:
  - interrupt/ and g1-wakeword/ are expected to come from git
  - OM1/ is not currently tracked in this repo and must exist locally, or be restorable from a backup bundle
EOF
}

latest_backup_dir() {
  local root="${INTERRUPT_DIR}/backups/private"
  if [[ ! -d "${root}" ]]; then
    return 1
  fi
  find "${root}" -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1
}

has_backup_archive() {
  local name="$1"
  local latest=""
  latest="$(latest_backup_dir || true)"
  [[ -n "${latest}" && -f "${latest}/${name}" ]]
}

ensure_home_link() {
  if [[ -L "${HOME_LINK}" || -e "${HOME_LINK}" ]]; then
    if [[ "${HOME_LINK}" -ef "${ROBOT_HOME}" ]]; then
      return 0
    fi
  fi
  ln -sfn "${ROBOT_HOME}" "${HOME_LINK}"
  printf '[restore-root] linked %s -> %s\n' "${HOME_LINK}" "${ROBOT_HOME}"
}

check_repo_layout() {
  [[ -d "${INTERRUPT_DIR}" ]] || {
    echo "[restore-root][error] missing interrupt dir: ${INTERRUPT_DIR}" >&2
    exit 1
  }
  [[ -x "${INTERRUPT_DIR}/restore_robot_voice_chain.sh" ]] || {
    echo "[restore-root][error] missing restore entrypoint: ${INTERRUPT_DIR}/restore_robot_voice_chain.sh" >&2
    exit 1
  }
  [[ -d "${WAKEWORD_DIR}" ]] || {
    echo "[restore-root][error] missing g1-wakeword dir: ${WAKEWORD_DIR}" >&2
    exit 1
  }
}

check_untracked_boundaries() {
  if [[ -d "${OM1_DIR}" ]]; then
    return 0
  fi
  if has_backup_archive "om1-voice-assets.tar.gz"; then
    printf '[restore-root] OM1 repo missing, but backup archive found under interrupt/backups/private\n'
    return 0
  fi
  cat >&2 <<EOF
[restore-root][error] missing OM1 dependency: ${OM1_DIR}

This repo currently does not fully track OM1/.
Before one-click restore can continue, provide one of:
  1. a local OM1 checkout at ${OM1_DIR}
  2. a backup archive interrupt/backups/private/<stamp>/om1-voice-assets.tar.gz

The same boundary applies to private runtime state such as:
  - interrupt/.env.local
  - interrupt/.venv
  - OM1/.venv-g1 or fallback runtime env
EOF
  exit 1
}

main() {
  local arg="${1:-}"
  if [[ "${arg}" == "-h" || "${arg}" == "--help" || "${arg}" == "help" ]]; then
    usage
    exit 0
  fi

  check_repo_layout
  check_untracked_boundaries
  ensure_home_link

  export INTERRUPT_DIR
  export ROBOT_HOME
  export OM1_DIR
  export WAKEWORD_DIR

  printf '[restore-root] repo_root=%s\n' "${ROOT_DIR}"
  printf '[restore-root] robot_home=%s\n' "${ROBOT_HOME}"
  printf '[restore-root] interrupt_dir=%s\n' "${INTERRUPT_DIR}"
  printf '[restore-root] om1_dir=%s\n' "${OM1_DIR}"
  printf '[restore-root] wakeword_dir=%s\n' "${WAKEWORD_DIR}"

  exec "${INTERRUPT_DIR}/restore_robot_voice_chain.sh" "$@"
}

main "$@"
