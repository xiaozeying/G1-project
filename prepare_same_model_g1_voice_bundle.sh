#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INTERRUPT_DIR="${INTERRUPT_DIR:-${ROOT_DIR}/interrupt}"
ROBOT_HOME="${ROBOT_HOME:-${ROOT_DIR}}"
OM1_DIR="${OM1_DIR:-${ROBOT_HOME}/OM1}"
WAKEWORD_DIR="${WAKEWORD_DIR:-${ROBOT_HOME}/g1-wakeword}"

usage() {
  cat <<'EOF'
usage: ./prepare_same_model_g1_voice_bundle.sh [--verify-only]

Repo-root pre-wipe bundle entrypoint for the same G1 robot model.

This wrapper:
  1. normalizes repo-root paths
  2. checks whether the voice-chain backup prerequisites exist
  3. delegates to interrupt/prepare_robot_wipe_bundle.sh

Output bundle location:
  interrupt/backups/private/<stamp>/
EOF
}

check_repo_layout() {
  [[ -d "${INTERRUPT_DIR}" ]] || {
    echo "[prepare-root][error] missing interrupt dir: ${INTERRUPT_DIR}" >&2
    exit 1
  }
  [[ -x "${INTERRUPT_DIR}/prepare_robot_wipe_bundle.sh" ]] || {
    echo "[prepare-root][error] missing bundle entrypoint: ${INTERRUPT_DIR}/prepare_robot_wipe_bundle.sh" >&2
    exit 1
  }
}

check_voice_assets() {
  if [[ ! -d "${OM1_DIR}" ]]; then
    cat >&2 <<EOF
[prepare-root][error] missing OM1 dependency: ${OM1_DIR}

The pre-wipe voice bundle expects OM1 voice assets to be available locally so
they can be packed into interrupt/backups/private/<stamp>/om1-voice-assets.tar.gz.
EOF
    exit 1
  fi
  if [[ ! -d "${WAKEWORD_DIR}" ]]; then
    cat >&2 <<EOF
[prepare-root][error] missing g1-wakeword dir: ${WAKEWORD_DIR}

The pre-wipe voice bundle expects g1-wakeword to be available locally so it can
be packed into interrupt/backups/private/<stamp>/g1-wakeword-assets.tar.gz.
EOF
    exit 1
  fi
}

main() {
  local arg="${1:-}"
  if [[ "${arg}" == "-h" || "${arg}" == "--help" || "${arg}" == "help" ]]; then
    usage
    exit 0
  fi

  check_repo_layout
  check_voice_assets

  export INTERRUPT_DIR
  export ROBOT_HOME
  export OM1_DIR
  export WAKEWORD_DIR

  printf '[prepare-root] repo_root=%s\n' "${ROOT_DIR}"
  printf '[prepare-root] interrupt_dir=%s\n' "${INTERRUPT_DIR}"
  printf '[prepare-root] om1_dir=%s\n' "${OM1_DIR}"
  printf '[prepare-root] wakeword_dir=%s\n' "${WAKEWORD_DIR}"

  exec "${INTERRUPT_DIR}/prepare_robot_wipe_bundle.sh" "$@"
}

main "$@"
