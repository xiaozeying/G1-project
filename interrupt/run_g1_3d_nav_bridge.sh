#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

resolve_nav_root() {
  local configured="${INTERRUPT_G1_NAV_STACK_ROOT:-${INTERRUPT_G1_3D_NAV_ROOT:-}}"
  if [[ -n "${configured}" && -d "${configured}" ]]; then
    printf '%s\n' "${configured}"
    return 0
  fi

  local candidates=(
    "/home/unitree/g1_3d_nav_ros2_repo"
    "/home/zz/HongTu/g1_3d_nav_ros2_repo"
    "/home/unitree/g1_3d_nav-main"
    "/home/zz/HongTu/g1_3d_nav-main"
    "/home/unitree/g1_3d_nav"
    "/home/zz/HongTu/g1_3d_nav"
    "/home/unitree/g1_3d_nav/HongTu/G1Nav2D"
    "/home/zz/HongTu/g1_3d_nav/HongTu/G1Nav2D"
    "${ROOT_DIR}/../G1Nav2D"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -d "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

NAV_ROOT="$(resolve_nav_root)"
export INTERRUPT_G1_3D_NAV_ROOT="${NAV_ROOT}"
export INTERRUPT_G1_NAV_STACK_ROOT="${NAV_ROOT}"

if [[ -x "${NAV_ROOT}/run_nav_bridge.sh" ]]; then
  exec bash "${NAV_ROOT}/run_nav_bridge.sh" "$@"
fi

if [[ -f "/opt/ros/humble/setup.bash" ]]; then
  set +u
  # shellcheck disable=SC1091
  source /opt/ros/humble/setup.bash
  set -u
fi

for extra_setup in \
  "${NAV_ROOT}/g1_ws/install/setup.bash" \
  "${NAV_ROOT}/deepglint_ws/install/setup.bash" \
  "${NAV_ROOT}/livox_ws/install/setup.bash"
do
  if [[ -f "${extra_setup}" ]]; then
    set +u
    # shellcheck disable=SC1090
    source "${extra_setup}"
    set -u
  fi
done

if [[ -f "/home/unitree/botbrain_ws/install/setup.bash" ]]; then
  set +u
  # shellcheck disable=SC1091
  source /home/unitree/botbrain_ws/install/setup.bash
  set -u
fi

if [[ -f "${NAV_ROOT}/devel/setup.bash" ]]; then
  bridge_args=("$@")
  set --
  set +u
  # shellcheck disable=SC1090
  source "${NAV_ROOT}/devel/setup.bash"
  set -u
  set -- "${bridge_args[@]}"
fi

BRIDGE_PYTHON="python3"
if [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  BRIDGE_PYTHON="${ROOT_DIR}/.venv/bin/python"
fi

bridge_args=(
  --nav-root "${NAV_ROOT}"
)

if [[ -n "${INTERRUPT_G1_NAV_MAP_FILE:-}" ]]; then
  bridge_args+=(--map-file "${INTERRUPT_G1_NAV_MAP_FILE}")
fi

if [[ -n "${INTERRUPT_G1_NAV_WAYPOINTS_FILE:-}" ]]; then
  bridge_args+=(--waypoints-file "${INTERRUPT_G1_NAV_WAYPOINTS_FILE}")
fi

if [[ -n "${INTERRUPT_G1_NAV_ACTION_SERVER:-}" ]]; then
  bridge_args+=(--action-server "${INTERRUPT_G1_NAV_ACTION_SERVER}")
fi

if [[ -n "${INTERRUPT_G1_NAV_DOCKER_CONTAINER:-}" ]]; then
  bridge_args+=(--docker-container "${INTERRUPT_G1_NAV_DOCKER_CONTAINER}")
fi

exec "${BRIDGE_PYTHON}" "${ROOT_DIR}/bridge/g1_3d_nav_bridge.py" "${bridge_args[@]}" "$@"
