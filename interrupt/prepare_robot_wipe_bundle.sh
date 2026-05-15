#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAMP="${STAMP:-$(date +%F-voice-chain)}"
BACKUP_ROOT="${INTERRUPT_BACKUP_ROOT:-${ROOT_DIR}/backups/private}"
TARGET_DIR="${BACKUP_ROOT}/${STAMP}"
VERIFY_ONLY=0

log() {
  printf '[prepare] %s\n' "$*"
}

die() {
  printf '[prepare][error] %s\n' "$*" >&2
  exit 1
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --verify-only)
        VERIFY_ONLY=1
        ;;
      *)
        die "未知参数: $1"
        ;;
    esac
    shift
  done
}

verify_bundle() {
  printf '[verify] bundle dir: %s\n' "${TARGET_DIR}"
  find "${TARGET_DIR}" -maxdepth 1 -type f | sort || true
}

main() {
  parse_args "$@"
  if [[ "${VERIFY_ONLY}" == "1" ]]; then
    verify_bundle
    return 0
  fi

  mkdir -p "${TARGET_DIR}"
  log "输出目录: ${TARGET_DIR}"

  STAMP="${STAMP}" INTERRUPT_BACKUP_ROOT="${BACKUP_ROOT}" "${ROOT_DIR}/package_robot_voice_assets.sh"
  STAMP="${STAMP}" INTERRUPT_BACKUP_ROOT="${BACKUP_ROOT}" "${ROOT_DIR}/backup_robot_voice_chain.sh"

  cat <<EOF

刷盘前准备包已完成：${TARGET_DIR}

下一步建议：
  1. 把整个目录拷走或同步到安全位置
  2. 刷盘后恢复代码
  3. 在机器人上运行 ./restore_robot_voice_chain.sh
  4. 如需先体检，可运行 ./restore_robot_voice_chain.sh --verify-only
EOF
}

main "$@"
