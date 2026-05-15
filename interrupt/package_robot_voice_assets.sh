#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROBOT_HOME="${ROBOT_HOME:-${HOME}/HongTu}"
OM1_DIR="${OM1_DIR:-${ROBOT_HOME}/OM1}"
WAKEWORD_DIR="${WAKEWORD_DIR:-${ROBOT_HOME}/g1-wakeword}"
STAMP="${STAMP:-$(date +%F-voice-assets)}"
BACKUP_ROOT="${INTERRUPT_BACKUP_ROOT:-${ROOT_DIR}/backups/private}"
PACKAGE_DIR="${BACKUP_ROOT}/${STAMP}"
STAGING_DIR="${PACKAGE_DIR}/staging"
OM1_ARCHIVE="${PACKAGE_DIR}/om1-voice-assets.tar.gz"
WAKEWORD_ARCHIVE="${PACKAGE_DIR}/g1-wakeword-assets.tar.gz"
MANIFEST="${PACKAGE_DIR}/asset-manifest.txt"

log() {
  printf '[package] %s\n' "$*"
}

warn() {
  printf '[package][warn] %s\n' "$*" >&2
}

copy_relative() {
  local base="$1"
  local relative="$2"
  local target_root="$3"
  local src="${base}/${relative}"
  local dst="${target_root}/${relative}"
  if [[ -f "${src}" ]]; then
    install -D -m 0644 "${src}" "${dst}"
    printf '%s\n' "${relative}" >> "${MANIFEST}"
  else
    warn "缺少文件，跳过: ${src}"
  fi
}

copy_exec_relative() {
  local base="$1"
  local relative="$2"
  local target_root="$3"
  local src="${base}/${relative}"
  local dst="${target_root}/${relative}"
  if [[ -f "${src}" ]]; then
    install -D -m 0755 "${src}" "${dst}"
    printf '%s\n' "${relative}" >> "${MANIFEST}"
  else
    warn "缺少文件，跳过: ${src}"
  fi
}

package_om1_assets() {
  local om1_stage="${STAGING_DIR}/OM1"
  mkdir -p "${om1_stage}"
  : > "${MANIFEST}"
  {
    echo "# OM1 voice assets"
    echo "scripts/external_usb_tts.sh"
    echo "scripts/g1_direct_command_fallback.py"
    echo "scripts/g1_watchdog_feedback.py"
    echo "scripts/run_g1.sh"
    echo "config/unitree_g1_text_arm_led_external_audio_gemini.json5"
  } >> "${MANIFEST}"

  copy_exec_relative "${OM1_DIR}" "scripts/external_usb_tts.sh" "${om1_stage}"
  copy_exec_relative "${OM1_DIR}" "scripts/run_g1.sh" "${om1_stage}"
  copy_relative "${OM1_DIR}" "scripts/g1_direct_command_fallback.py" "${om1_stage}"
  copy_relative "${OM1_DIR}" "scripts/g1_watchdog_feedback.py" "${om1_stage}"
  copy_relative "${OM1_DIR}" "config/unitree_g1_text_arm_led_external_audio_gemini.json5" "${om1_stage}"

  (
    cd "${STAGING_DIR}"
    tar -czf "${OM1_ARCHIVE}" OM1
  )
  log "已打包 OM1 关键语音资产 -> ${OM1_ARCHIVE}"
}

package_wakeword_assets() {
  local wake_stage="${STAGING_DIR}/g1-wakeword"
  mkdir -p "${wake_stage}"
  {
    echo
    echo "# g1-wakeword assets"
    echo "wakeword_adaptive.py"
    echo "install_arm.sh"
    echo "README.md"
    echo "requirements-arm.txt"
  } >> "${MANIFEST}"

  copy_relative "${WAKEWORD_DIR}" "wakeword_adaptive.py" "${wake_stage}"
  copy_exec_relative "${WAKEWORD_DIR}" "install_arm.sh" "${wake_stage}"
  copy_relative "${WAKEWORD_DIR}" "README.md" "${wake_stage}"
  copy_relative "${WAKEWORD_DIR}" "requirements-arm.txt" "${wake_stage}"

  (
    cd "${STAGING_DIR}"
    tar -czf "${WAKEWORD_ARCHIVE}" g1-wakeword
  )
  log "已打包 g1-wakeword 关键资产 -> ${WAKEWORD_ARCHIVE}"
}

main() {
  mkdir -p "${PACKAGE_DIR}" "${STAGING_DIR}"
  if [[ ! -d "${OM1_DIR}" ]]; then
    warn "未找到 OM1 目录: ${OM1_DIR}"
  else
    package_om1_assets
  fi
  if [[ ! -d "${WAKEWORD_DIR}" ]]; then
    warn "未找到 g1-wakeword 目录: ${WAKEWORD_DIR}"
  else
    package_wakeword_assets
  fi
  rm -rf "${STAGING_DIR}"
  cat <<EOF

关键资产打包完成：
  ${OM1_ARCHIVE}
  ${WAKEWORD_ARCHIVE}
  ${MANIFEST}

这些包适合在刷盘前导出，刷盘后再配合 restore 脚本还原工作区关键入口。
EOF
}

main "$@"
