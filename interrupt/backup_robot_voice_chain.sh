#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROBOT_HOME="${ROBOT_HOME:-${HOME}/HongTu}"
INTERRUPT_DIR="${INTERRUPT_DIR:-${ROOT_DIR}}"
OM1_DIR="${OM1_DIR:-${ROBOT_HOME}/OM1}"
WAKEWORD_DIR="${WAKEWORD_DIR:-${ROBOT_HOME}/g1-wakeword}"
SERVICE_NAME="${SERVICE_NAME:-interrupt-frontgate.service}"
SERVICE_SOURCE_PATH="${HOME}/.config/systemd/user/${SERVICE_NAME}"
STAMP="${STAMP:-$(date +%F-board-upgrade)}"
BACKUP_ROOT="${INTERRUPT_BACKUP_ROOT:-${INTERRUPT_DIR}/backups/private}"
BACKUP_DIR="${BACKUP_ROOT}/${STAMP}"
DEVICE_SNAPSHOT="${BACKUP_DIR}/device-snapshot.txt"

log() {
  printf '[backup] %s\n' "$*"
}

warn() {
  printf '[backup][warn] %s\n' "$*" >&2
}

copy_if_exists() {
  local src="$1"
  local dst="$2"
  if [[ -f "${src}" ]]; then
    install -D -m 0644 "${src}" "${dst}"
    log "已备份 ${src} -> ${dst}"
  else
    warn "文件不存在，跳过: ${src}"
  fi
}

freeze_env() {
  local python_bin="$1"
  local output="$2"
  if [[ -x "${python_bin}" ]]; then
    "${python_bin}" -m pip freeze > "${output}"
    log "已导出依赖冻结: ${output}"
  else
    warn "未找到 Python 环境，跳过 freeze: ${python_bin}"
  fi
}

write_device_snapshot() {
  {
    echo "# generated at $(date '+%F %T %Z')"
    echo
    echo "## uname"
    uname -a || true
    echo
    echo "## network"
    ip -brief addr || true
    echo
    echo "## arecord -l"
    arecord -l || true
    echo
    echo "## aplay -l"
    aplay -l || true
    echo
    echo "## pulse info"
    pactl info || true
    echo
    echo "## pulse sources"
    pactl list short sources || true
    echo
    echo "## pulse sinks"
    pactl list short sinks || true
    echo
    echo "## video devices"
    ls -l /dev/video* 2>/dev/null || true
    echo
    echo "## systemd user service"
    systemctl --user status "${SERVICE_NAME}" --no-pager || true
  } > "${DEVICE_SNAPSHOT}"
  log "已写入设备快照: ${DEVICE_SNAPSHOT}"
}

main() {
  mkdir -p "${BACKUP_DIR}"

  copy_if_exists "${INTERRUPT_DIR}/.env.local" "${BACKUP_DIR}/robot-interrupt.env.local"
  copy_if_exists "${INTERRUPT_DIR}/.env.local" "${BACKUP_DIR}/local-interrupt.env.local"
  copy_if_exists "${SERVICE_SOURCE_PATH}" "${BACKUP_DIR}/${SERVICE_NAME}"

  freeze_env "${INTERRUPT_DIR}/.venv/bin/python" "${BACKUP_DIR}/interrupt-venv-freeze.txt"
  freeze_env "${HOME}/miniforge3/envs/wakeword-clean/bin/python" "${BACKUP_DIR}/wakeword-clean-freeze.txt"
  freeze_env "${OM1_DIR}/.venv-g1/bin/python" "${BACKUP_DIR}/om1-venv-freeze.txt"

  write_device_snapshot

  if [[ -f "${WAKEWORD_DIR}/wakeword_adaptive.py" ]]; then
    log "已确认 wakeword 入口存在: ${WAKEWORD_DIR}/wakeword_adaptive.py"
  else
    warn "未找到 wakeword 入口: ${WAKEWORD_DIR}/wakeword_adaptive.py"
  fi

  cat <<EOF

备份完成：${BACKUP_DIR}

建议下一步：
  1. 确认 robot-interrupt.env.local 中的私钥和地址都是最新
  2. 视需要额外打包 ${OM1_DIR} 与 ${WAKEWORD_DIR}
  3. 刷盘后在新系统里运行 ./restore_robot_voice_chain.sh
EOF
}

main "$@"
