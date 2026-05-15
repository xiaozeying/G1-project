#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROBOT_HOME="${ROBOT_HOME:-${HOME}/HongTu}"
INTERRUPT_DIR="${INTERRUPT_DIR:-${ROOT_DIR}}"
OM1_DIR="${OM1_DIR:-${ROBOT_HOME}/OM1}"
WAKEWORD_DIR="${WAKEWORD_DIR:-${ROBOT_HOME}/g1-wakeword}"
SERVICE_NAME="${SERVICE_NAME:-interrupt-frontgate.service}"
SERVICE_TARGET_DIR="${HOME}/.config/systemd/user"
SERVICE_TARGET_PATH="${SERVICE_TARGET_DIR}/${SERVICE_NAME}"
PRIMARY_SERVICE_SOURCE="${INTERRUPT_DIR}/deploy/systemd/user/${SERVICE_NAME}"
BACKUP_DIR="${INTERRUPT_BACKUP_DIR:-${INTERRUPT_DIR}/backups/private/2026-04-30-board-upgrade}"
RESTORE_ASSET_TTS="${INTERRUPT_DIR}/restore_assets/om1/external_usb_tts.sh"
TARGET_TTS_SCRIPT="${OM1_DIR}/scripts/external_usb_tts.sh"
VENV_DIR="${INTERRUPT_DIR}/.venv"
WAKEWORD_PYTHON="${HOME}/miniforge3/envs/wakeword-clean/bin/python"
SKIP_BOOTSTRAP=0
VERIFY_ONLY=0

detect_backup_dir() {
  if [[ -n "${INTERRUPT_BACKUP_DIR:-}" ]]; then
    printf '%s\n' "${INTERRUPT_BACKUP_DIR}"
    return 0
  fi
  local root="${INTERRUPT_DIR}/backups/private"
  if [[ ! -d "${root}" ]]; then
    printf '%s\n' "${BACKUP_DIR}"
    return 0
  fi
  local latest
  latest="$(find "${root}" -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)"
  if [[ -n "${latest}" ]]; then
    printf '%s\n' "${latest}"
  else
    printf '%s\n' "${BACKUP_DIR}"
  fi
}

BACKUP_DIR="$(detect_backup_dir)"
BACKUP_ENV_FILE="${BACKUP_DIR}/robot-interrupt.env.local"
BACKUP_SERVICE_FILE="${BACKUP_DIR}/${SERVICE_NAME}"
BACKUP_OM1_ARCHIVE="${BACKUP_DIR}/om1-voice-assets.tar.gz"
BACKUP_WAKEWORD_ARCHIVE="${BACKUP_DIR}/g1-wakeword-assets.tar.gz"

log() {
  printf '[restore] %s\n' "$*"
}

warn() {
  printf '[restore][warn] %s\n' "$*" >&2
}

die() {
  printf '[restore][error] %s\n' "$*" >&2
  exit 1
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --skip-bootstrap)
        SKIP_BOOTSTRAP=1
        ;;
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

copy_if_missing() {
  local src="$1"
  local dst="$2"
  if [[ -e "${dst}" ]]; then
    log "已存在，跳过: ${dst}"
    return 0
  fi
  [[ -f "${src}" ]] || return 1
  install -D -m 0644 "${src}" "${dst}"
}

copy_executable() {
  local src="$1"
  local dst="$2"
  [[ -f "${src}" ]] || return 1
  install -D -m 0755 "${src}" "${dst}"
}

ensure_interrupt_env() {
  if [[ -f "${INTERRUPT_DIR}/.env.local" ]]; then
    log "已找到 ${INTERRUPT_DIR}/.env.local"
    return 0
  fi
  if [[ -f "${BACKUP_ENV_FILE}" ]]; then
    install -D -m 0600 "${BACKUP_ENV_FILE}" "${INTERRUPT_DIR}/.env.local"
    log "已从备份恢复 .env.local"
    return 0
  fi
  die "缺少 ${INTERRUPT_DIR}/.env.local，且未找到备份 ${BACKUP_ENV_FILE}"
}

ensure_om1_asset() {
  if [[ ! -d "${OM1_DIR}" && -f "${BACKUP_OM1_ARCHIVE}" ]]; then
    mkdir -p "${OM1_DIR}"
    tar -xzf "${BACKUP_OM1_ARCHIVE}" -C "$(dirname "${OM1_DIR}")"
    log "已从备份包恢复 OM1 关键资产"
  fi
  if [[ ! -d "${OM1_DIR}" ]]; then
    warn "未找到 OM1 目录: ${OM1_DIR}，跳过 external_usb_tts.sh 恢复"
    return 0
  fi
  if copy_executable "${RESTORE_ASSET_TTS}" "${TARGET_TTS_SCRIPT}"; then
    log "已同步 OM1 USB TTS 脚本 -> ${TARGET_TTS_SCRIPT}"
  else
    warn "未找到恢复资产 ${RESTORE_ASSET_TTS}"
  fi
}

ensure_service_file() {
  mkdir -p "${SERVICE_TARGET_DIR}"
  if [[ -f "${PRIMARY_SERVICE_SOURCE}" ]]; then
    install -m 0644 "${PRIMARY_SERVICE_SOURCE}" "${SERVICE_TARGET_PATH}"
    log "已安装 systemd user service -> ${SERVICE_TARGET_PATH}"
    return 0
  fi
  if [[ -f "${BACKUP_SERVICE_FILE}" ]]; then
    install -m 0644 "${BACKUP_SERVICE_FILE}" "${SERVICE_TARGET_PATH}"
    log "已从备份恢复 systemd user service -> ${SERVICE_TARGET_PATH}"
    return 0
  fi
  die "缺少 service 文件：${PRIMARY_SERVICE_SOURCE}"
}

ensure_interrupt_venv() {
  if [[ -x "${VENV_DIR}/bin/python" ]]; then
    log "已找到 interrupt 虚拟环境: ${VENV_DIR}"
    return 0
  fi
  if [[ "${SKIP_BOOTSTRAP}" == "1" ]]; then
    die "缺少 interrupt 虚拟环境，且当前启用了 --skip-bootstrap"
  fi
  log "开始重建 interrupt 虚拟环境"
  "${INTERRUPT_DIR}/bootstrap.sh"
}

ensure_wakeword_env() {
  if [[ ! -d "${WAKEWORD_DIR}" && -f "${BACKUP_WAKEWORD_ARCHIVE}" ]]; then
    mkdir -p "${WAKEWORD_DIR}"
    tar -xzf "${BACKUP_WAKEWORD_ARCHIVE}" -C "$(dirname "${WAKEWORD_DIR}")"
    log "已从备份包恢复 g1-wakeword 关键资产"
  fi
  if [[ -x "${WAKEWORD_PYTHON}" ]]; then
    log "已找到 wakeword-clean: ${WAKEWORD_PYTHON}"
    return 0
  fi
  if [[ -x "${WAKEWORD_DIR}/install_arm.sh" ]]; then
    log "开始执行 g1-wakeword/install_arm.sh"
    (
      cd "${WAKEWORD_DIR}"
      ./install_arm.sh
    )
    return 0
  fi
  warn "未找到 wakeword-clean，也没有 ${WAKEWORD_DIR}/install_arm.sh"
}

verify_paths() {
  [[ -d "${INTERRUPT_DIR}" ]] || die "未找到 interrupt 目录: ${INTERRUPT_DIR}"
  [[ -f "${INTERRUPT_DIR}/run_robot_frontgate_session.sh" ]] || die "interrupt 目录不完整: 缺少 run_robot_frontgate_session.sh"
  if [[ ! -d "${WAKEWORD_DIR}" ]]; then
    warn "未找到 g1-wakeword 目录: ${WAKEWORD_DIR}"
  fi
  log "使用备份目录: ${BACKUP_DIR}"
}

start_service() {
  systemctl --user daemon-reload
  systemctl --user enable "${SERVICE_NAME}" >/dev/null
  systemctl --user restart "${SERVICE_NAME}"
  log "已重启 ${SERVICE_NAME}"
}

run_verification() {
  local status_output
  status_output="$(systemctl --user is-active "${SERVICE_NAME}" 2>/dev/null || true)"
  printf '\n[verify] service active state: %s\n' "${status_output:-unknown}"
  printf '[verify] audio env lines:\n'
  grep -n '^INTERRUPT_ASSISTANT_AUDIO_MODE\|^INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE\|^PULSE_SINK\|^PULSE_SOURCE' \
    "${INTERRUPT_DIR}/.env.local" 2>/dev/null || true
  printf '[verify] latest frontgate log tail:\n'
  tail -n 20 "${INTERRUPT_DIR}/logs/frontgate.log" 2>/dev/null || true
}

print_summary() {
  cat <<EOF

恢复完成。建议马上执行以下检查：

  systemctl --user status ${SERVICE_NAME} --no-pager
  grep -n '^INTERRUPT_ASSISTANT_AUDIO_MODE\\|^INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE\\|^PULSE_SINK\\|^PULSE_SOURCE' ${INTERRUPT_DIR}/.env.local
  tail -n 80 ${INTERRUPT_DIR}/logs/frontgate.log

如果服务已是 active (running)，下一步就可以直接现场唤醒测试。
EOF
}

main() {
  parse_args "$@"
  verify_paths
  if [[ "${VERIFY_ONLY}" == "1" ]]; then
    run_verification
    return 0
  fi
  ensure_interrupt_env
  ensure_om1_asset
  ensure_service_file
  ensure_interrupt_venv
  ensure_wakeword_env
  start_service
  run_verification
  print_summary
}

main "$@"
