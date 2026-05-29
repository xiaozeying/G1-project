#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKUP_ROOT="${INTERRUPT_BACKUP_ROOT:-${ROOT_DIR}/backups/private}"
STAMP="${STAMP:-$(date +%F-%H%M%S)-robot-compose-backup}"
TARGET_DIR="${BACKUP_ROOT}/${STAMP}"
ROBOT_HOST="${ROBOT_HOST:-unitree@192.168.100.30}"
ROBOT_INTERRUPT_DIR="${ROBOT_INTERRUPT_DIR:-/home/unitree/HongTu/interrupt}"
ROBOT_OM1_DIR="${ROBOT_OM1_DIR:-/home/unitree/HongTu/OM1}"
ROBOT_WAKEWORD_DIR="${ROBOT_WAKEWORD_DIR:-/home/unitree/g1-wakeword}"

mkdir -p "${TARGET_DIR}"

ssh -o StrictHostKeyChecking=no "${ROBOT_HOST}" "\
  mkdir -p ${ROBOT_INTERRUPT_DIR}/backups/private/${STAMP} && \
  cd ${ROBOT_INTERRUPT_DIR} && \
  ./backup_robot_voice_chain.sh >/tmp/${STAMP}.backup.log 2>&1 || cat /tmp/${STAMP}.backup.log && \
  { \
    echo '# docker ps'; docker ps -a; \
    echo; echo '# docker images'; docker images; \
    echo; echo '# systemd'; systemctl --user status interrupt-frontgate.service --no-pager || true; \
  } > ${ROBOT_INTERRUPT_DIR}/backups/private/${STAMP}/docker-runtime.txt"

scp -o StrictHostKeyChecking=no -r \
  "${ROBOT_HOST}:${ROBOT_INTERRUPT_DIR}/backups/private/${STAMP}" \
  "${TARGET_DIR}/robot-backup"

scp -o StrictHostKeyChecking=no \
  "${ROBOT_HOST}:${ROBOT_INTERRUPT_DIR}/.env.local" \
  "${TARGET_DIR}/robot-interrupt.env.local"

tar -czf "${TARGET_DIR}/switch-machine-bundle.tgz" \
  -C "${ROOT_DIR}/.." \
  interrupt/deploy/compose \
  interrupt/deploy/systemd/user/interrupt-frontgate-compose.service \
  interrupt/restore_robot_voice_chain.sh \
  interrupt/backup_robot_voice_chain.sh

printf 'backup saved to %s\n' "${TARGET_DIR}"
