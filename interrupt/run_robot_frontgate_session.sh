#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/robot-frontgate.log"
HEALTH_LOG_FILE="${LOG_DIR}/audio-startup-health.log"

source "${ROOT_DIR}/libexec/python_env.sh"
source "${ROOT_DIR}/libexec/local_text_backend.sh"
interrupt_activate_python_env "${ROOT_DIR}"

exec > >(tee -a "${LOG_FILE}") 2>&1
echo "===== $(date '+%F %T') run_robot_frontgate_session.sh ====="

prepend_path_entry() {
  local entry="$1"
  local current="$2"
  if [[ -z "${entry}" ]]; then
    printf '%s' "${current}"
    return
  fi
  if [[ -z "${current}" ]]; then
    printf '%s' "${entry}"
    return
  fi
  case ":${current}:" in
    *":${entry}:"*) printf '%s' "${current}" ;;
    *) printf '%s:%s' "${entry}" "${current}" ;;
  esac
}

pick_om1_python() {
  local candidate
  for candidate in \
    "/home/unitree/HongTu/OM1/.venv-g1-runtime/bin/python" \
    "/home/unitree/HongTu/OM1/.venv-g1/bin/python" \
    "/home/unitree/HongTu/OM1/.venv/bin/python"
  do
    if [[ -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  printf '%s\n' "/home/unitree/HongTu/OM1/.venv-g1/bin/python"
}

health_log() {
  local status="$1"
  local detail="$2"
  local stamp
  stamp="$(date '+%F %T')"
  printf '%s status=%s detail=%s\n' "${stamp}" "${status}" "${detail}" | tee -a "${HEALTH_LOG_FILE}"
}

have_arecord_card() {
  local card_id="$1"
  arecord -l 2>/dev/null | grep -F " ${card_id} [" >/dev/null 2>&1
}

first_pulse_source_matching() {
  local pattern match
  for pattern in "$@"; do
    match="$(pactl list short sources 2>/dev/null | awk '{print $2}' | grep -F "${pattern}" | grep -v '\.monitor$' | head -n1 || true)"
    if [[ -n "${match}" ]]; then
      printf '%s\n' "${match}"
      return 0
    fi
  done
  return 1
}

is_usb_pulse_source() {
  local value="${1:-}"
  [[ -n "${value}" && "${value}" == *"usb"* && "${value}" == *"mvsilicon"* ]]
}

is_usb_pulse_sink() {
  local value="${1:-}"
  [[ -n "${value}" && "${value}" == *"usb"* && "${value}" == *"mvsilicon"* ]]
}

have_usb_alsa_capture() {
  arecord -l 2>/dev/null | grep -F "card 0: audio" >/dev/null 2>&1
}

first_pulse_sink_matching() {
  local pattern match
  for pattern in "$@"; do
    match="$(pactl list short sinks 2>/dev/null | awk '{print $2}' | grep -F "${pattern}" | head -n1 || true)"
    if [[ -n "${match}" ]]; then
      printf '%s\n' "${match}"
      return 0
    fi
  done
  return 1
}

wait_for_pulse_endpoint() {
  local endpoint_type="$1"
  local endpoint_name="$2"
  local timeout_s="$3"
  if [[ -z "${endpoint_name}" ]]; then
    return 1
  fi
  python3 - "${endpoint_type}" "${endpoint_name}" "${timeout_s}" <<'PY'
import subprocess
import sys
import time

endpoint_type, endpoint_name, timeout_s = sys.argv[1], sys.argv[2], float(sys.argv[3])
deadline = time.monotonic() + max(0.0, timeout_s)
command = ["pactl", "list", "short", "sinks" if endpoint_type == "sink" else "sources"]
while True:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            names = [line.split()[1] for line in completed.stdout.splitlines() if len(line.split()) >= 2]
            if endpoint_name in names:
                print("ready")
                raise SystemExit(0)
    except FileNotFoundError:
        break
    if time.monotonic() >= deadline:
        break
    time.sleep(0.25)
print("timeout")
raise SystemExit(1)
PY
}

run_audio_startup_preflight() {
  local enabled="${INTERRUPT_FRONTGATE_AUDIO_PREFLIGHT:-1}"
  if [[ "${enabled}" != "1" ]]; then
    echo "robot audio startup preflight: disabled"
    health_log "disabled" "audio_preflight_disabled"
    return 0
  fi
  local speak_script="${INTERRUPT_G1_SPEAK_SCRIPT:-}"
  if [[ -z "${speak_script}" || ! -f "${speak_script}" ]]; then
    echo "robot audio startup preflight: skipped speak_script=${speak_script:-unset}"
    health_log "skipped" "missing_speak_script:${speak_script:-unset}"
    return 0
  fi
  local prewarm_text="${INTERRUPT_FRONTGATE_AUDIO_PREWARM_TEXT:-系统音频预热}"
  local debug_flag="${INTERRUPT_FRONTGATE_AUDIO_PREFLIGHT_DEBUG:-1}"
  echo "robot audio startup preflight: begin sink=${PULSE_SINK:-unset} source=${PULSE_SOURCE:-unset}"
  if OM1_TTS_PREWARM_ONLY=1 OM1_TTS_DEBUG="${debug_flag}" PULSE_SINK="${PULSE_SINK:-}" bash "${speak_script}" "${prewarm_text}"; then
    echo "robot audio startup preflight: ok"
    health_log "ok" "sink=${PULSE_SINK:-unset} source=${PULSE_SOURCE:-unset}"
  else
    local rc=$?
    echo "robot audio startup preflight: failed rc=${rc}"
    health_log "failed" "rc=${rc} sink=${PULSE_SINK:-unset} source=${PULSE_SOURCE:-unset}"
    return "${rc}"
  fi
}

retry_audio_startup_preflight_once() {
  local delay_s="${INTERRUPT_FRONTGATE_AUDIO_PREFLIGHT_RETRY_DELAY_S:-2}"
  echo "robot audio startup preflight: retrying once after ${delay_s}s"
  sleep "${delay_s}"
  if command -v pactl >/dev/null 2>&1; then
    local refreshed_source=""
    local refreshed_sink=""
    refreshed_source="$(first_pulse_source_matching "usb" "mvsilicon" "alsa_input.usb" "platform-sound" "alsa_input.platform-sound" "alsa_input" || true)"
    refreshed_sink="$(first_pulse_sink_matching "usb" "mvsilicon" "platform-sound" "alsa_output" || true)"
    if [[ -n "${refreshed_source}" ]]; then
      export PULSE_SOURCE="${refreshed_source}"
    fi
    if [[ -n "${refreshed_sink}" ]]; then
      export PULSE_SINK="${refreshed_sink}"
    fi
    if [[ -n "${PULSE_SOURCE:-}" ]]; then
      pactl set-default-source "${PULSE_SOURCE}" || true
    fi
    if [[ -n "${PULSE_SINK:-}" ]]; then
      pactl set-default-sink "${PULSE_SINK}" || true
      pactl set-sink-mute "${PULSE_SINK}" 0 || true
      pactl set-sink-volume "${PULSE_SINK}" "${PULSE_SINK_VOLUME_PERCENT:-100%}" || true
    fi
  fi
  run_audio_startup_preflight
}

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

interrupt_maybe_force_singlebox_local_text_loopback

export INTERRUPT_ASSISTANT_AUDIO_MODE="${INTERRUPT_ASSISTANT_AUDIO_MODE:-local}"
export INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE="${INTERRUPT_LOCAL_TOOL_ACK_AUDIO_MODE:-local}"
export INTERRUPT_ENABLE_LOCAL_TEXT_REPLY_FALLBACK="${INTERRUPT_ENABLE_LOCAL_TEXT_REPLY_FALLBACK:-1}"

export LD_LIBRARY_PATH="$(prepend_path_entry "/usr/local/lib" "${LD_LIBRARY_PATH:-}")"
export INTERRUPT_G1_OM1_PYTHON="${INTERRUPT_G1_OM1_PYTHON:-$(pick_om1_python)}"
export INTERRUPT_G1_DIRECT_COMMAND_SCRIPT="${INTERRUPT_G1_DIRECT_COMMAND_SCRIPT:-/home/unitree/HongTu/OM1/scripts/g1_direct_command_fallback.py}"
export INTERRUPT_G1_FEEDBACK_SCRIPT="${INTERRUPT_G1_FEEDBACK_SCRIPT:-/home/unitree/HongTu/OM1/scripts/g1_watchdog_feedback.py}"

export INTERRUPT_WAKE_WORD_FACTORY="${INTERRUPT_WAKE_WORD_FACTORY:-src.om1_wakeword_gate:factory}"
export WAKEWORD_SCRIPT="${WAKEWORD_SCRIPT:-/home/unitree/g1-wakeword/wakeword_adaptive.py}"
export INTERRUPT_FRONTGATE_SESSION_COMMAND="${INTERRUPT_FRONTGATE_SESSION_COMMAND:-${ROOT_DIR}/run_frontgate_room_session.sh}"
export INTERRUPT_FRONTGATE_SESSION_TIMEOUT="${INTERRUPT_FRONTGATE_SESSION_TIMEOUT:-0}"
export INTERRUPT_FRONTGATE_ROOM_MAX_DURATION_S="${INTERRUPT_FRONTGATE_ROOM_MAX_DURATION_S:-0}"
export INTERRUPT_FRONTGATE_ROOM_STARTUP_TIMEOUT_S="${INTERRUPT_FRONTGATE_ROOM_STARTUP_TIMEOUT_S:-60}"
export INTERRUPT_FRONTGATE_ROOM_PRE_DISPATCH_DELAY_S="${INTERRUPT_FRONTGATE_ROOM_PRE_DISPATCH_DELAY_S:-2}"
export INTERRUPT_FRONTGATE_USER_AWAY_TIMEOUT_MS="${INTERRUPT_FRONTGATE_USER_AWAY_TIMEOUT_MS:-180000}"
export INTERRUPT_FRONTGATE_MIN_INTERRUPTION_DURATION_MS="${INTERRUPT_FRONTGATE_MIN_INTERRUPTION_DURATION_MS:-80}"
export INTERRUPT_FRONTGATE_FALSE_INTERRUPTION_TIMEOUT_MS="${INTERRUPT_FRONTGATE_FALSE_INTERRUPTION_TIMEOUT_MS:-500}"
export INTERRUPT_FRONTGATE_REALTIME_START_SENSITIVITY="${INTERRUPT_FRONTGATE_REALTIME_START_SENSITIVITY:-HIGH}"
export INTERRUPT_FRONTGATE_REALTIME_END_SENSITIVITY="${INTERRUPT_FRONTGATE_REALTIME_END_SENSITIVITY:-HIGH}"
export INTERRUPT_FRONTGATE_MIN_ENDPOINTING_DELAY_MS="${INTERRUPT_FRONTGATE_MIN_ENDPOINTING_DELAY_MS:-150}"
export INTERRUPT_FRONTGATE_MAX_ENDPOINTING_DELAY_MS="${INTERRUPT_FRONTGATE_MAX_ENDPOINTING_DELAY_MS:-600}"
export INTERRUPT_FRONTGATE_REALTIME_PREFIX_PADDING_MS="${INTERRUPT_FRONTGATE_REALTIME_PREFIX_PADDING_MS:-200}"
if [[ -z "${PULSE_SOURCE:-}" || "${PULSE_SOURCE:-}" == *"platform-sound"* || "${PULSE_SOURCE:-}" == *".monitor"* ]]; then
  export PULSE_SOURCE="alsa_input.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo"
fi
if [[ -z "${PULSE_SINK:-}" || "${PULSE_SINK:-}" == *"platform-sound"* || "${PULSE_SINK:-}" == *".monitor"* ]]; then
  export PULSE_SINK="alsa_output.usb-MV-SILICON_mvsilicon_B1_usb_audio_20190808-00.analog-stereo"
fi
export PULSE_SINK_VOLUME_PERCENT="${PULSE_SINK_VOLUME_PERCENT:-100%}"
export OM1_CONSOLE_INPUT_DEVICE="${OM1_CONSOLE_INPUT_DEVICE:-mvsilicon B1 usb audio}"
export OM1_CONSOLE_OUTPUT_DEVICE="${OM1_CONSOLE_OUTPUT_DEVICE:-pulse}"
export INTERRUPT_RTC_INPUT_DEVICE="${INTERRUPT_RTC_INPUT_DEVICE:-plughw:CARD=audio,DEV=0}"
export INTERRUPT_RTC_OUTPUT_DEVICE="${INTERRUPT_RTC_OUTPUT_DEVICE:-pulse}"

if ! have_arecord_card "audio" && have_arecord_card "APE"; then
  export INTERRUPT_RTC_INPUT_DEVICE="${INTERRUPT_RTC_INPUT_DEVICE/plughw:CARD=audio,DEV=0/plughw:CARD=APE,DEV=0}"
  if [[ "${OM1_CAPTURE_DEVICE:-default}" == "default" || "${OM1_CAPTURE_DEVICE:-}" == "pulse" || -z "${OM1_CAPTURE_DEVICE:-}" || "${OM1_CAPTURE_DEVICE:-}" == *"CARD=audio"* ]]; then
    export OM1_CAPTURE_DEVICE="plughw:CARD=APE,DEV=0"
  fi
  if [[ -z "${OM1_CAPTURE_HINTS:-}" || "${OM1_CAPTURE_HINTS:-}" == *"MV-SILICON"* || "${OM1_CAPTURE_HINTS:-}" == *"mvsilicon"* ]]; then
    export OM1_CAPTURE_HINTS="APE,platform-sound,NVIDIA Jetson Orin NX APE"
  fi
  if [[ -z "${OM1_CONSOLE_INPUT_DEVICE:-}" || "${OM1_CONSOLE_INPUT_DEVICE:-}" == *"mvsilicon"* || "${OM1_CONSOLE_INPUT_DEVICE:-}" == *"USB Audio"* ]]; then
    export OM1_CONSOLE_INPUT_DEVICE="default"
  fi
  if [[ -z "${INTERRUPT_FRONTGATE_WAIT_FOR_INPUT_DEVICE_SUBSTRING:-}" || "${INTERRUPT_FRONTGATE_WAIT_FOR_INPUT_DEVICE_SUBSTRING:-}" == *"mvsilicon"* ]]; then
    export INTERRUPT_FRONTGATE_WAIT_FOR_INPUT_DEVICE_SUBSTRING="platform-sound"
  fi
fi

if [[ "${OM1_CAPTURE_DEVICE:-}" == "pulse" ]]; then
  export OM1_CAPTURE_DEVICE="default"
fi
if [[ -z "${INTERRUPT_RTC_INPUT_DEVICE}" ]]; then
  export INTERRUPT_RTC_INPUT_DEVICE="plughw:CARD=audio,DEV=0"
fi
if [[ "${INTERRUPT_RTC_OUTPUT_DEVICE}" == "pulse" || "${INTERRUPT_RTC_OUTPUT_DEVICE}" == "default" || "${INTERRUPT_RTC_OUTPUT_DEVICE}" == "0" ]]; then
  export INTERRUPT_RTC_OUTPUT_DEVICE="${OM1_CONSOLE_OUTPUT_DEVICE}"
fi
export INTERRUPT_FRONTGATE_PYTHON="${INTERRUPT_FRONTGATE_PYTHON:-${INTERRUPT_G1_OM1_PYTHON}}"
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
export INTERRUPT_FRONTGATE_PULSE_WAIT_TIMEOUT_S="${INTERRUPT_FRONTGATE_PULSE_WAIT_TIMEOUT_S:-12.0}"

if command -v pactl >/dev/null 2>&1; then
  if have_usb_alsa_capture; then
    echo "robot usb alsa capture ready: ${INTERRUPT_RTC_INPUT_DEVICE}"
  elif [[ -n "${PULSE_SOURCE}" ]]; then
    if wait_for_pulse_endpoint "source" "${PULSE_SOURCE}" "${INTERRUPT_FRONTGATE_PULSE_WAIT_TIMEOUT_S}"; then
      echo "robot pulse source ready: ${PULSE_SOURCE}"
    else
      echo "robot pulse source not ready before timeout: ${PULSE_SOURCE}"
    fi
  fi
  if [[ -n "${PULSE_SINK}" ]]; then
    if wait_for_pulse_endpoint "sink" "${PULSE_SINK}" "${INTERRUPT_FRONTGATE_PULSE_WAIT_TIMEOUT_S}"; then
      echo "robot pulse sink ready: ${PULSE_SINK}"
    else
      echo "robot pulse sink not ready before timeout: ${PULSE_SINK}"
    fi
  fi
  if ! pactl list short sources 2>/dev/null | awk '{print $2}' | grep -Fx "${PULSE_SOURCE}" >/dev/null 2>&1; then
    FALLBACK_PULSE_SOURCE="$(first_pulse_source_matching "usb" "mvsilicon" "alsa_input.usb" || true)"
    if [[ -n "${FALLBACK_PULSE_SOURCE}" ]]; then
      export PULSE_SOURCE="${FALLBACK_PULSE_SOURCE}"
    fi
  fi
  if ! pactl list short sinks 2>/dev/null | awk '{print $2}' | grep -Fx "${PULSE_SINK}" >/dev/null 2>&1; then
    FALLBACK_PULSE_SINK="$(first_pulse_sink_matching "usb" "mvsilicon" "alsa_output.usb" || true)"
    if [[ -n "${FALLBACK_PULSE_SINK}" ]]; then
      export PULSE_SINK="${FALLBACK_PULSE_SINK}"
    fi
  fi
  CURRENT_PULSE_SOURCE="$(pactl info 2>/dev/null | sed -n 's/^Default Source: //p' | head -n1)"
  CURRENT_PULSE_SINK="$(pactl info 2>/dev/null | sed -n 's/^Default Sink: //p' | head -n1)"
  if ! is_usb_pulse_sink "${PULSE_SINK}"; then
    USB_SINK_CANDIDATE="$(first_pulse_sink_matching "usb-MV-SILICON" "mvsilicon" "alsa_output.usb" || true)"
    if [[ -n "${USB_SINK_CANDIDATE}" ]]; then
      export PULSE_SINK="${USB_SINK_CANDIDATE}"
    fi
  fi
  if have_usb_alsa_capture; then
    echo "robot usb alsa capture present: ${INTERRUPT_RTC_INPUT_DEVICE}"
    echo "robot pulse source kept as: ${CURRENT_PULSE_SOURCE:-unset}"
  elif pactl list short sources 2>/dev/null | awk '{print $2}' | grep -Fx "${PULSE_SOURCE}" >/dev/null 2>&1; then
    if [[ "${CURRENT_PULSE_SOURCE}" != "${PULSE_SOURCE}" ]]; then
      pactl set-default-source "${PULSE_SOURCE}" || true
    fi
    echo "robot pulse default source: ${CURRENT_PULSE_SOURCE:-unset} -> ${PULSE_SOURCE}"
  else
    echo "robot pulse preferred source missing: ${PULSE_SOURCE}"
    echo "robot frontgate will rely on direct ALSA capture instead of pulse source for USB microphone"
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

printf -v INTERRUPT_FRONTGATE_ROOM_AGENT_COMMAND_DEFAULT \
  "env INTERRUPT_USER_AWAY_TIMEOUT_MS=%q INTERRUPT_MIN_INTERRUPTION_DURATION_MS=%q INTERRUPT_FALSE_INTERRUPTION_TIMEOUT_MS=%q INTERRUPT_REALTIME_START_SENSITIVITY=%q INTERRUPT_REALTIME_END_SENSITIVITY=%q INTERRUPT_MIN_ENDPOINTING_DELAY_MS=%q INTERRUPT_MAX_ENDPOINTING_DELAY_MS=%q INTERRUPT_REALTIME_PREFIX_PADDING_MS=%q %q" \
  "${INTERRUPT_FRONTGATE_USER_AWAY_TIMEOUT_MS}" \
  "${INTERRUPT_FRONTGATE_MIN_INTERRUPTION_DURATION_MS}" \
  "${INTERRUPT_FRONTGATE_FALSE_INTERRUPTION_TIMEOUT_MS}" \
  "${INTERRUPT_FRONTGATE_REALTIME_START_SENSITIVITY}" \
  "${INTERRUPT_FRONTGATE_REALTIME_END_SENSITIVITY}" \
  "${INTERRUPT_FRONTGATE_MIN_ENDPOINTING_DELAY_MS}" \
  "${INTERRUPT_FRONTGATE_MAX_ENDPOINTING_DELAY_MS}" \
  "${INTERRUPT_FRONTGATE_REALTIME_PREFIX_PADDING_MS}" \
  "${ROOT_DIR}/run_room_agent.sh"
export INTERRUPT_FRONTGATE_ROOM_AGENT_COMMAND="${INTERRUPT_FRONTGATE_ROOM_AGENT_COMMAND:-${INTERRUPT_FRONTGATE_ROOM_AGENT_COMMAND_DEFAULT}}"

printf -v INTERRUPT_FRONTGATE_RTC_ENDPOINT_COMMAND_DEFAULT \
  "env INTERRUPT_RTC_INPUT_DEVICE=%q INTERRUPT_RTC_OUTPUT_DEVICE=%q PULSE_SOURCE=%q PULSE_SINK=%q %q" \
  "${INTERRUPT_RTC_INPUT_DEVICE}" \
  "${INTERRUPT_RTC_OUTPUT_DEVICE}" \
  "${PULSE_SOURCE}" \
  "${PULSE_SINK}" \
  "${ROOT_DIR}/run_robot_rtc_endpoint.sh"
export INTERRUPT_FRONTGATE_RTC_ENDPOINT_COMMAND="${INTERRUPT_FRONTGATE_RTC_ENDPOINT_COMMAND:-${INTERRUPT_FRONTGATE_RTC_ENDPOINT_COMMAND_DEFAULT}}"
export INTERRUPT_FRONTGATE_ENSURE_RTC_ENDPOINT="${INTERRUPT_FRONTGATE_ENSURE_RTC_ENDPOINT:-1}"

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
echo "robot frontgate realtime end sensitivity: ${INTERRUPT_FRONTGATE_REALTIME_END_SENSITIVITY}"
echo "robot frontgate min endpointing delay ms: ${INTERRUPT_FRONTGATE_MIN_ENDPOINTING_DELAY_MS}"
echo "robot frontgate max endpointing delay ms: ${INTERRUPT_FRONTGATE_MAX_ENDPOINTING_DELAY_MS}"
echo "robot frontgate realtime prefix padding ms: ${INTERRUPT_FRONTGATE_REALTIME_PREFIX_PADDING_MS}"
echo "robot console input device: ${INTERRUPT_INPUT_DEVICE}"
echo "robot console output device: ${INTERRUPT_OUTPUT_DEVICE:-default}"
echo "robot rtc input device: ${INTERRUPT_RTC_INPUT_DEVICE}"
echo "robot rtc output device: ${INTERRUPT_RTC_OUTPUT_DEVICE}"
echo "robot room agent command: ${INTERRUPT_FRONTGATE_ROOM_AGENT_COMMAND:-${ROOT_DIR}/run_room_agent.sh}"
echo "robot rtc endpoint command: ${INTERRUPT_FRONTGATE_RTC_ENDPOINT_COMMAND:-${ROOT_DIR}/run_robot_rtc_endpoint.sh}"
echo "robot ensure rtc endpoint on wake: ${INTERRUPT_FRONTGATE_ENSURE_RTC_ENDPOINT}"
echo "robot session device wait substring: ${INTERRUPT_FRONTGATE_WAIT_FOR_INPUT_DEVICE_SUBSTRING}"
echo "robot local text base_url: ${INTERRUPT_AGENT_LOCAL_TEXT_BASE_URL:-unset}"
echo "robot local text model: ${INTERRUPT_AGENT_LOCAL_TEXT_MODEL:-qwen2.5:1.5b}"

if ! run_audio_startup_preflight; then
  retry_audio_startup_preflight_once || true
fi

if ! interrupt_ensure_local_text_backend_ready "${ROOT_DIR}" "${LOG_DIR}/local-text-backend.log"; then
  echo "local text backend required but not ready; frontgate session will not start" >&2
  exit 1
fi

exec "${ROOT_DIR}/run_frontgate_session.sh" "$@"
