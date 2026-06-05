#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_DIR="${ROOT_DIR}/deploy/compose"
ROBOT_HOST="${ROBOT_HOST:-unitree@192.168.100.30}"
ROBOT_HOME="${ROBOT_HOME:-/data/HongTu}"
ROBOT_INTERRUPT_DIR="${ROBOT_INTERRUPT_DIR:-${ROBOT_HOME}/interrupt}"
ROBOT_COMPOSE_DIR="${ROBOT_INTERRUPT_DIR}/deploy/compose"
ROBOT_SERVICE_DIR="${ROBOT_SERVICE_DIR:-/home/unitree/.config/systemd/user}"
ACTIVATE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --activate)
      ACTIVATE=1
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 1
      ;;
  esac
  shift
done

ssh -o StrictHostKeyChecking=no "${ROBOT_HOST}" "\
  mkdir -p ${ROBOT_COMPOSE_DIR} ${ROBOT_SERVICE_DIR} ${ROBOT_INTERRUPT_DIR}/volumes/frontgate_shared"

scp -o StrictHostKeyChecking=no \
  "${COMPOSE_DIR}/Dockerfile" \
  "${COMPOSE_DIR}/composectl.sh" \
  "${COMPOSE_DIR}/ensure_docker_compose.sh" \
  "${COMPOSE_DIR}/docker-compose.robot.wakeword-online.yaml" \
  "${COMPOSE_DIR}/env.robot.wakeword-online.example" \
  "${COMPOSE_DIR}/backup_robot_over_ssh.sh" \
  "${ROBOT_HOST}:${ROBOT_COMPOSE_DIR}/"

scp -o StrictHostKeyChecking=no \
  "${ROOT_DIR}/deploy/systemd/user/interrupt-frontgate-wakeword-online-compose.service" \
  "${ROBOT_HOST}:${ROBOT_SERVICE_DIR}/interrupt-frontgate-wakeword-online-compose.service"

ssh -o StrictHostKeyChecking=no "${ROBOT_HOST}" "\
  chmod +x ${ROBOT_COMPOSE_DIR}/composectl.sh ${ROBOT_COMPOSE_DIR}/ensure_docker_compose.sh ${ROBOT_COMPOSE_DIR}/backup_robot_over_ssh.sh && \
  if [ ! -f ${ROBOT_COMPOSE_DIR}/env.robot.wakeword-online ]; then \
    cp ${ROBOT_COMPOSE_DIR}/env.robot.wakeword-online.example ${ROBOT_COMPOSE_DIR}/env.robot.wakeword-online; \
  fi"

if [[ "${ACTIVATE}" == "1" ]]; then
  ssh -o StrictHostKeyChecking=no "${ROBOT_HOST}" "\
    cd ${ROBOT_INTERRUPT_DIR} && \
    ${ROBOT_COMPOSE_DIR}/ensure_docker_compose.sh && \
    ${ROBOT_COMPOSE_DIR}/composectl.sh \
      --env-file ${ROBOT_COMPOSE_DIR}/env.robot.wakeword-online \
      -f ${ROBOT_COMPOSE_DIR}/docker-compose.robot.wakeword-online.yaml \
      up -d --build online-brain wakeword-frontgate"
fi

if [[ "${ACTIVATE}" == "1" ]]; then
  printf 'wakeword+online compose deployment finished and activated: %s\n' "${ROBOT_HOST}"
else
  printf 'wakeword+online compose bundle staged on %s; activate later with --activate\n' "${ROBOT_HOST}"
fi
