#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/livekit-server.log"
LIVEKIT_BIND_ADDRESS="${LIVEKIT_BIND_ADDRESS:-127.0.0.1}"
LIVEKIT_NODE_IP="${LIVEKIT_NODE_IP:-127.0.0.1}"
LIVEKIT_RTC_NODE_IP_IPV4="${LIVEKIT_RTC_NODE_IP_IPV4:-127.0.0.1}"
LIVEKIT_RTC_NODE_IP_IPV6="${LIVEKIT_RTC_NODE_IP_IPV6:-}"
LIVEKIT_RTC_FORCE_TCP="${LIVEKIT_RTC_FORCE_TCP:-false}"
LIVEKIT_RTC_ALLOW_TCP_FALLBACK="${LIVEKIT_RTC_ALLOW_TCP_FALLBACK:-true}"

exec > >(tee -a "${LOG_FILE}") 2>&1
echo "===== $(date '+%F %T') run_livekit_server.sh ====="

if ! command -v livekit-server >/dev/null 2>&1; then
  echo "未找到 livekit-server。请先安装 LiveKit Server。"
  echo "安装方式: curl -sSL https://get.livekit.io | bash"
  exit 1
fi

LIVEKIT_BIN="$(command -v livekit-server)"
if [[ ! -x "${LIVEKIT_BIN}" ]]; then
  echo "检测到 livekit-server 存在，但当前用户没有执行权限：${LIVEKIT_BIN}"
  ls -l "${LIVEKIT_BIN}" || true
  echo "请执行：sudo chmod 755 ${LIVEKIT_BIN}"
  exit 1
fi

echo "启动本地 LiveKit Server --dev"
echo "默认凭据: LIVEKIT_API_KEY=devkey LIVEKIT_API_SECRET=secret"
echo "bind address: ${LIVEKIT_BIND_ADDRESS}"
echo "node ip: ${LIVEKIT_NODE_IP}"
echo "rtc node ip ipv4: ${LIVEKIT_RTC_NODE_IP_IPV4}"
echo "rtc node ip ipv6: ${LIVEKIT_RTC_NODE_IP_IPV6:-disabled}"
echo "rtc force tcp: ${LIVEKIT_RTC_FORCE_TCP}"
echo "rtc allow tcp fallback: ${LIVEKIT_RTC_ALLOW_TCP_FALLBACK}"
exec livekit-server \
  --dev \
  --bind "${LIVEKIT_BIND_ADDRESS}" \
  --node-ip "${LIVEKIT_NODE_IP}" \
  --rtc.node_ip.ipv4 "${LIVEKIT_RTC_NODE_IP_IPV4}" \
  --rtc.force_tcp="${LIVEKIT_RTC_FORCE_TCP}" \
  --rtc.allow_tcp_fallback="${LIVEKIT_RTC_ALLOW_TCP_FALLBACK}"
