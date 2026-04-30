#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/robot-frontgate.log"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "未找到虚拟环境，请先执行 ./bootstrap.sh"
  exit 1
fi

source "${VENV_DIR}/bin/activate"

exec > >(tee -a "${LOG_FILE}") 2>&1
echo "===== $(date '+%F %T') run_robot_frontgate_session.sh ====="

if [[ -f "${ROOT_DIR}/.env.local" ]]; then
  set -a
  source "${ROOT_DIR}/.env.local"
  set +a
fi

if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  source "${ROOT_DIR}/.env"
  set +a
fi

export INTERRUPT_WAKE_WORD_FACTORY="${INTERRUPT_WAKE_WORD_FACTORY:-src.om1_wakeword_gate:factory}"
export WAKEWORD_SCRIPT="${WAKEWORD_SCRIPT:-/home/unitree/g1-wakeword/wakeword_adaptive.py}"
export INTERRUPT_FRONTGATE_SESSION_COMMAND="${INTERRUPT_FRONTGATE_SESSION_COMMAND:-${ROOT_DIR}/run_frontgate_room_session.sh}"
export INTERRUPT_FRONTGATE_SESSION_TIMEOUT="${INTERRUPT_FRONTGATE_SESSION_TIMEOUT:-0}"
export INTERRUPT_FRONTGATE_ROOM_MAX_DURATION_S="${INTERRUPT_FRONTGATE_ROOM_MAX_DURATION_S:-0}"
export INTERRUPT_FRONTGATE_ROOM_STARTUP_TIMEOUT_S="${INTERRUPT_FRONTGATE_ROOM_STARTUP_TIMEOUT_S:-60}"
export INTERRUPT_FRONTGATE_ROOM_PRE_DISPATCH_DELAY_S="${INTERRUPT_FRONTGATE_ROOM_PRE_DISPATCH_DELAY_S:-2}"
export INTERRUPT_FRONTGATE_USER_AWAY_TIMEOUT_MS="${INTERRUPT_FRONTGATE_USER_AWAY_TIMEOUT_MS:-300000}"
export INTERRUPT_FRONTGATE_MIN_INTERRUPTION_DURATION_MS="${INTERRUPT_FRONTGATE_MIN_INTERRUPTION_DURATION_MS:-180}"
export INTERRUPT_FRONTGATE_FALSE_INTERRUPTION_TIMEOUT_MS="${INTERRUPT_FRONTGATE_FALSE_INTERRUPTION_TIMEOUT_MS:-900}"
export INTERRUPT_FRONTGATE_REALTIME_START_SENSITIVITY="${INTERRUPT_FRONTGATE_REALTIME_START_SENSITIVITY:-LOW}"
export PULSE_SOURCE="${PULSE_SOURCE:-alsa_input.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo}"
export PULSE_SINK="${PULSE_SINK:-alsa_output.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo}"
export PULSE_SINK_VOLUME_PERCENT="${PULSE_SINK_VOLUME_PERCENT:-100%}"
export OM1_CONSOLE_INPUT_DEVICE="${OM1_CONSOLE_INPUT_DEVICE:-mvsilicon B1 usb audio}"
export OM1_CONSOLE_OUTPUT_DEVICE="${OM1_CONSOLE_OUTPUT_DEVICE:-pulse}"
export INTERRUPT_RTC_INPUT_DEVICE="${INTERRUPT_RTC_INPUT_DEVICE:-plughw:CARD=audio,DEV=0}"
export INTERRUPT_RTC_OUTPUT_DEVICE="${INTERRUPT_RTC_OUTPUT_DEVICE:-pulse}"
if [[ "${OM1_CAPTURE_DEVICE:-}" == "pulse" ]]; then
  export OM1_CAPTURE_DEVICE="default"
fi
if [[ -z "${INTERRUPT_RTC_INPUT_DEVICE}" ]]; then
  export INTERRUPT_RTC_INPUT_DEVICE="plughw:CARD=audio,DEV=0"
fi
if [[ "${INTERRUPT_RTC_OUTPUT_DEVICE}" == "pulse" || "${INTERRUPT_RTC_OUTPUT_DEVICE}" == "default" || "${INTERRUPT_RTC_OUTPUT_DEVICE}" == "0" ]]; then
  export INTERRUPT_RTC_OUTPUT_DEVICE="${OM1_CONSOLE_OUTPUT_DEVICE}"
fi
export INTERRUPT_FRONTGATE_ROOM_AGENT_COMMAND="${INTERRUPT_FRONTGATE_ROOM_AGENT_COMMAND:-env INTERRUPT_USER_AWAY_TIMEOUT_MS=${INTERRUPT_FRONTGATE_USER_AWAY_TIMEOUT_MS} INTERRUPT_MIN_INTERRUPTION_DURATION_MS=${INTERRUPT_FRONTGATE_MIN_INTERRUPTION_DURATION_MS} INTERRUPT_FALSE_INTERRUPTION_TIMEOUT_MS=${INTERRUPT_FRONTGATE_FALSE_INTERRUPTION_TIMEOUT_MS} INTERRUPT_REALTIME_START_SENSITIVITY=${INTERRUPT_FRONTGATE_REALTIME_START_SENSITIVITY} ${ROOT_DIR}/run_room_agent.sh}"
export INTERRUPT_FRONTGATE_RTC_ENDPOINT_COMMAND="${INTERRUPT_FRONTGATE_RTC_ENDPOINT_COMMAND:-env INTERRUPT_RTC_AUTO_DISPATCH_AGENT=0 INTERRUPT_RTC_AGENT_ABSENCE_CHECK_INTERVAL_S=0 INTERRUPT_RTC_INPUT_DEVICE=${INTERRUPT_RTC_INPUT_DEVICE} INTERRUPT_RTC_OUTPUT_DEVICE=${INTERRUPT_RTC_OUTPUT_DEVICE} PULSE_SOURCE=${PULSE_SOURCE} PULSE_SINK=${PULSE_SINK} ${ROOT_DIR}/run_robot_rtc_endpoint.sh}"
export INTERRUPT_FRONTGATE_PYTHON="${INTERRUPT_FRONTGATE_PYTHON:-/home/unitree/miniforge3/envs/wakeword-clean/bin/python}"
export OM1_CAPTURE_HINTS="${OM1_CAPTURE_HINTS:-mvsilicon B1 usb audio,USB Audio,MV-SILICON}"
export OM1_CAPTURE_DEVICE="${OM1_CAPTURE_DEVICE:-default}"
export OM1_WAKEWORD_CHUNK_DURATION="${OM1_WAKEWORD_CHUNK_DURATION:-1.6}"
export OM1_WAKEWORD_MERGE_HISTORY_CHUNKS="${OM1_WAKEWORD_MERGE_HISTORY_CHUNKS:-3}"
export OM1_AUDIO_GAIN="${OM1_AUDIO_GAIN:-2.2}"
export OM1_AUDIO_LEVEL_INTERVAL="${OM1_AUDIO_LEVEL_INTERVAL:-1.5}"
export OM1_WAKEWORD_READ_TIMEOUT_S="${OM1_WAKEWORD_READ_TIMEOUT_S:-12.0}"
export OM1_WAKEWORD_REOPEN_DELAY_S="${OM1_WAKEWORD_REOPEN_DELAY_S:-0.20}"
export OM1_WAKEWORD_MAX_CONSECUTIVE_ERRORS="${OM1_WAKEWORD_MAX_CONSECUTIVE_ERRORS:-20}"
export OM1_IDLE_MIN_RMS="${OM1_IDLE_MIN_RMS:-1100}"
export OM1_IDLE_MIN_PEAK="${OM1_IDLE_MIN_PEAK:-4200}"
export OM1_IDLE_SPEECH_RATIO="${OM1_IDLE_SPEECH_RATIO:-1.45}"
export OM1_IDLE_RELEASE_CHUNKS="${OM1_IDLE_RELEASE_CHUNKS:-2}"
export INTERRUPT_INPUT_DEVICE="${INTERRUPT_INPUT_DEVICE:-${OM1_CONSOLE_INPUT_DEVICE}}"
export INTERRUPT_OUTPUT_DEVICE="${INTERRUPT_OUTPUT_DEVICE:-${OM1_CONSOLE_OUTPUT_DEVICE:-0}}"
export INTERRUPT_FRONTGATE_WAIT_FOR_INPUT_DEVICE_SUBSTRING="${INTERRUPT_FRONTGATE_WAIT_FOR_INPUT_DEVICE_SUBSTRING:-mvsilicon B1 usb audio}"
export INTERRUPT_FRONTGATE_WAIT_FOR_INPUT_DEVICE_TIMEOUT="${INTERRUPT_FRONTGATE_WAIT_FOR_INPUT_DEVICE_TIMEOUT:-3.0}"

if command -v pactl >/dev/null 2>&1; then
  CURRENT_PULSE_SOURCE="$(pactl info 2>/dev/null | sed -n 's/^Default Source: //p' | head -n1)"
  CURRENT_PULSE_SINK="$(pactl info 2>/dev/null | sed -n 's/^Default Sink: //p' | head -n1)"
  if pactl list short sources 2>/dev/null | awk '{print $2}' | grep -Fx "${PULSE_SOURCE}" >/dev/null 2>&1; then
    if [[ "${CURRENT_PULSE_SOURCE}" != "${PULSE_SOURCE}" ]]; then
      pactl set-default-source "${PULSE_SOURCE}" || true
    fi
    echo "robot pulse default source: ${CURRENT_PULSE_SOURCE:-unset} -> ${PULSE_SOURCE}"
  else
    echo "robot pulse preferred source missing: ${PULSE_SOURCE}"
  fi
  if pactl list short sinks 2>/dev/null | awk '{print $2}' | grep -Fx "${PULSE_SINK}" >/dev/null 2>&1; then
    if [[ "${CURRENT_PULSE_SINK}" != "${PULSE_SINK}" ]]; then
      pactl set-default-sink "${PULSE_SINK}" || true
    fi
    pactl set-sink-mute "${PULSE_SINK}" 0 || true
    pactl set-sink-volume "${PULSE_SINK}" "${PULSE_SINK_VOLUME_PERCENT}" || true
    echo "robot pulse default sink: ${CURRENT_PULSE_SINK:-unset} -> ${PULSE_SINK}"
    SINK_VOLUME_STATE="$(pactl get-sink-volume "${PULSE_SINK}" 2>/dev/null | head -n1 || true)"
    SINK_MUTE_STATE="$(pactl get-sink-mute "${PULSE_SINK}" 2>/dev/null || true)"
    echo "robot pulse sink volume target: ${PULSE_SINK_VOLUME_PERCENT}"
    echo "robot pulse sink volume state: ${SINK_VOLUME_STATE:-unknown}"
    echo "robot pulse sink mute state: ${SINK_MUTE_STATE:-unknown}"
  else
    echo "robot pulse preferred sink missing: ${PULSE_SINK}"
  fi
fi

echo "robot frontgate factory: ${INTERRUPT_WAKE_WORD_FACTORY}"
echo "robot wakeword script: ${WAKEWORD_SCRIPT}"
echo "robot frontgate python: ${INTERRUPT_FRONTGATE_PYTHON}"
echo "robot capture device: ${OM1_CAPTURE_DEVICE}"
echo "robot capture hints: ${OM1_CAPTURE_HINTS}"
echo "robot wakeword chunk duration: ${OM1_WAKEWORD_CHUNK_DURATION}"
echo "robot wakeword merge history chunks: ${OM1_WAKEWORD_MERGE_HISTORY_CHUNKS}"
echo "robot wakeword read timeout s: ${OM1_WAKEWORD_READ_TIMEOUT_S}"
echo "robot wakeword reopen delay s: ${OM1_WAKEWORD_REOPEN_DELAY_S}"
echo "robot wakeword max consecutive errors: ${OM1_WAKEWORD_MAX_CONSECUTIVE_ERRORS}"
echo "robot pulse source: ${PULSE_SOURCE}"
echo "robot pulse sink: ${PULSE_SINK}"
echo "robot session command: ${INTERRUPT_FRONTGATE_SESSION_COMMAND}"
echo "robot session timeout: ${INTERRUPT_FRONTGATE_SESSION_TIMEOUT}"
echo "robot room max duration: ${INTERRUPT_FRONTGATE_ROOM_MAX_DURATION_S}"
echo "robot room startup timeout: ${INTERRUPT_FRONTGATE_ROOM_STARTUP_TIMEOUT_S}"
echo "robot room pre-dispatch delay: ${INTERRUPT_FRONTGATE_ROOM_PRE_DISPATCH_DELAY_S}"
echo "robot frontgate user-away timeout: ${INTERRUPT_FRONTGATE_USER_AWAY_TIMEOUT_MS}"
echo "robot frontgate min interruption ms: ${INTERRUPT_FRONTGATE_MIN_INTERRUPTION_DURATION_MS}"
echo "robot frontgate false interruption timeout ms: ${INTERRUPT_FRONTGATE_FALSE_INTERRUPTION_TIMEOUT_MS}"
echo "robot frontgate realtime start sensitivity: ${INTERRUPT_FRONTGATE_REALTIME_START_SENSITIVITY}"
echo "robot console input device: ${INTERRUPT_INPUT_DEVICE}"
echo "robot console output device: ${INTERRUPT_OUTPUT_DEVICE:-default}"
echo "robot rtc input device: ${INTERRUPT_RTC_INPUT_DEVICE}"
echo "robot rtc output device: ${INTERRUPT_RTC_OUTPUT_DEVICE}"
echo "robot room agent command: ${INTERRUPT_FRONTGATE_ROOM_AGENT_COMMAND:-${ROOT_DIR}/run_room_agent.sh}"
echo "robot rtc endpoint command: ${INTERRUPT_FRONTGATE_RTC_ENDPOINT_COMMAND:-${ROOT_DIR}/run_robot_rtc_endpoint.sh}"
echo "robot session device wait substring: ${INTERRUPT_FRONTGATE_WAIT_FOR_INPUT_DEVICE_SUBSTRING}"

exec "${ROOT_DIR}/run_frontgate_session.sh" "$@"
