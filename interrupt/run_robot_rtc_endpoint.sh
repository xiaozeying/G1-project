#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/robot-rtc-endpoint.log"
VENV_DIR="${INTERRUPT_VENV_DIR:-${ROOT_DIR}/.venv}"
DEFAULT_PYTHON_BIN="${VENV_DIR}/bin/python"

source "${ROOT_DIR}/libexec/python_env.sh"
interrupt_activate_python_env "${ROOT_DIR}"

exec > >(tee -a "${LOG_FILE}") 2>&1
echo "===== $(date '+%F %T') run_robot_rtc_endpoint.sh ====="

have_arecord_card() {
  local card_id="$1"
  arecord -l 2>/dev/null | grep -F " ${card_id} [" >/dev/null 2>&1
}

first_usb_alsa_capture_device() {
  arecord -l 2>/dev/null | sed -n 's/^card [0-9]\+: \([^ ]\+\) \[.*device \([0-9]\+\): USB Audio .*/plughw:CARD=\1,DEV=\2/p' | head -n1
}

load_env_defaults() {
  local env_file="$1"
  [[ -f "${env_file}" ]] || return 0
  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ -z "${line}" ]] && continue
    [[ "${line}" =~ ^[[:space:]]*# ]] && continue
    if [[ "${line}" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
      local key="${BASH_REMATCH[1]}"
      local raw_value="${BASH_REMATCH[2]}"
      if [[ -z "${!key+x}" ]]; then
        if [[ "${raw_value}" =~ ^\"(.*)\"$ ]]; then
          printf -v "${key}" '%s' "${BASH_REMATCH[1]}"
        elif [[ "${raw_value}" =~ ^\'(.*)\'$ ]]; then
          printf -v "${key}" '%s' "${BASH_REMATCH[1]}"
        else
          printf -v "${key}" '%s' "${raw_value}"
        fi
        export "${key}"
      fi
    fi
  done < "${env_file}"
}

load_env_defaults "${ROOT_DIR}/.env.local"
load_env_defaults "${ROOT_DIR}/.env"

PYTHON_BIN="${INTERRUPT_PYTHON_BIN:-${DEFAULT_PYTHON_BIN}}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "rtc-endpoint python 不可执行: ${PYTHON_BIN}" >&2
  exit 1
fi
RESOLVED_VLM_ENV="$("${PYTHON_BIN}" "${ROOT_DIR}/tools/resolve_vlm_runtime.py" --mode robot --allow-online-fallback)"
eval "${RESOLVED_VLM_ENV}"

export INTERRUPT_RTC_ENDPOINT_ENABLED="${INTERRUPT_RTC_ENDPOINT_ENABLED:-1}"
export INTERRUPT_RTC_ROOM_NAME="${INTERRUPT_RTC_ROOM_NAME:-interrupt-demo}"
export INTERRUPT_RTC_IDENTITY="${INTERRUPT_RTC_IDENTITY:-robot-rtc-endpoint}"

LIVEKIT_HOST=""
if [[ -n "${LIVEKIT_URL:-}" ]]; then
  LIVEKIT_HOST="$(python3 - <<'PY'
from urllib.parse import urlparse
import os
print(urlparse(os.environ.get("LIVEKIT_URL", "")).hostname or "")
PY
)"
fi

if [[ "${LIVEKIT_HOST}" == "localhost" || "${LIVEKIT_HOST}" == "127.0.0.1" || "${LIVEKIT_HOST}" =~ ^10\. || "${LIVEKIT_HOST}" =~ ^192\.168\. || "${LIVEKIT_HOST}" =~ ^172\.(1[6-9]|2[0-9]|3[0-1])\. ]]; then
  unset WSS_PROXY WS_PROXY HTTP_PROXY HTTPS_PROXY ALL_PROXY
  unset wss_proxy ws_proxy http_proxy https_proxy all_proxy
fi

echo "rtc endpoint enabled: ${INTERRUPT_RTC_ENDPOINT_ENABLED}"
echo "rtc room: ${INTERRUPT_RTC_ROOM_NAME}"
echo "rtc identity: ${INTERRUPT_RTC_IDENTITY}"
echo "rtc publish microphone: ${INTERRUPT_RTC_PUBLISH_MICROPHONE:-1}"
echo "rtc subscribe audio: ${INTERRUPT_RTC_SUBSCRIBE_AUDIO:-1}"
echo "rtc auto redispatch on agent disconnect: ${INTERRUPT_RTC_AUTO_REDISPATCH_ON_AGENT_DISCONNECT:-1}"
echo "rtc redispatch cooldown s: ${INTERRUPT_RTC_REDISPATCH_COOLDOWN_S:-8}"
echo "rtc agent absence check interval s: ${INTERRUPT_RTC_AGENT_ABSENCE_CHECK_INTERVAL_S:-20}"
echo "resolved VLM source: ${INTERRUPT_VLM_RESOLVED_SOURCE:-unset}"
echo "resolved VLM reason: ${INTERRUPT_VLM_RESOLVED_REASON:-unset}"
echo "resolved VLM provider: ${INTERRUPT_VLM_PROVIDER:-unset}"
echo "resolved VLM base_url: ${INTERRUPT_VLM_BASE_URL:-unset}"
echo "resolved VLM model: ${INTERRUPT_VLM_MODEL:-unset}"
export INTERRUPT_RTC_INPUT_DEVICE="${INTERRUPT_RTC_INPUT_DEVICE:-plughw:CARD=audio,DEV=0}"
USB_ALSA_CAPTURE_DEVICE="$(first_usb_alsa_capture_device || true)"
if [[ "${INTERRUPT_RTC_INPUT_DEVICE}" == "plughw:CARD=audio,DEV=0" ]] && [[ -n "${USB_ALSA_CAPTURE_DEVICE}" ]]; then
  export INTERRUPT_RTC_INPUT_DEVICE="${USB_ALSA_CAPTURE_DEVICE}"
elif [[ "${INTERRUPT_RTC_INPUT_DEVICE}" == "plughw:CARD=audio,DEV=0" ]] && ! have_arecord_card "audio" && have_arecord_card "APE"; then
  export INTERRUPT_RTC_INPUT_DEVICE="plughw:CARD=APE,DEV=0"
fi

echo "rtc input device: ${INTERRUPT_RTC_INPUT_DEVICE}"
echo "rtc output device: ${INTERRUPT_RTC_OUTPUT_DEVICE:-default}"
echo "rtc proxy disabled for host: ${LIVEKIT_HOST:-unset}"

cd "${ROOT_DIR}"
exec "${PYTHON_BIN}" -m src.rtc_endpoint "$@"
