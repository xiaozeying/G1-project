#!/usr/bin/env bash
set -euo pipefail

TEXT="${1:-}"
if [[ -z "${TEXT}" ]]; then
  exit 0
fi

debug_log() {
  if [[ "${OM1_TTS_DEBUG:-0}" == "1" ]]; then
    echo "[external_usb_tts] $*" >&2
  fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
resolve_interrupt_root() {
  local requested="${INTERRUPT_ROOT:-}"
  if [[ -n "${requested}" && -d "${requested}" ]]; then
    printf '%s\n' "${requested}"
    return 0
  fi
  local candidate
  for candidate in \
    "$(cd "${SCRIPT_DIR}/../../.." && pwd)" \
    "$(cd "${SCRIPT_DIR}/../.." && pwd)/interrupt" \
    "/home/unitree/HongTu/interrupt" \
    "/home/zz/HongTu/robot_snapshots/HongTu_from_G1_2026-04-16/interrupt"; do
    if [[ -d "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  printf '%s\n' "/home/unitree/HongTu/interrupt"
}

INTERRUPT_ROOT="$(resolve_interrupt_root)"
EDGE_TTS_PYTHON="${OM1_EDGE_TTS_PYTHON:-${INTERRUPT_ROOT}/.venv/bin/python}"
EDGE_TTS_ZH_VOICE="${OM1_EDGE_TTS_ZH_VOICE:-zh-CN-XiaoxiaoNeural}"
EDGE_TTS_EN_VOICE="${OM1_EDGE_TTS_EN_VOICE:-en-US-JennyNeural}"
EDGE_TTS_RATE="${OM1_EDGE_TTS_RATE:-+0%}"
EDGE_TTS_VOLUME="${OM1_EDGE_TTS_VOLUME:-+0%}"
EDGE_TTS_PITCH="${OM1_EDGE_TTS_PITCH:-+0Hz}"
EDGE_TTS_TIMEOUT_S="${OM1_EDGE_TTS_TIMEOUT_S:-15}"
TTS_PREWARM_ONLY="${OM1_TTS_PREWARM_ONLY:-0}"
ALSA_PLAYBACK_DEVICE="${OM1_ALSA_PLAYBACK_DEVICE:-plughw:CARD=audio,DEV=0}"

list_pulse_sinks() {
  pactl list short sinks 2>/dev/null | awk '{print $2}'
}

sink_exists() {
  local sink_name="$1"
  [[ -n "${sink_name}" ]] || return 1
  list_pulse_sinks | grep -Fx "${sink_name}" >/dev/null 2>&1
}

alsa_playback_available() {
  aplay -l 2>/dev/null | grep -F "card 0: audio" >/dev/null 2>&1
}

REQUESTED_SINK="${OM1_EXTERNAL_SINK:-${PULSE_SINK:-}}"
DEFAULT_SINK="$(pactl info 2>/dev/null | awk -F': ' '/Default Sink/ {print $2}')"
USB_SINK="$(pactl list short sinks 2>/dev/null | awk '/usb|USB|mvsilicon|B1/ {print $2; exit}')"
PREFERRED_SINK=""
FORCE_ALSA_PLAYBACK=0

if [[ -n "${REQUESTED_SINK}" ]]; then
  if sink_exists "${REQUESTED_SINK}"; then
    PREFERRED_SINK="${REQUESTED_SINK}"
  elif alsa_playback_available; then
    FORCE_ALSA_PLAYBACK=1
  else
    PREFERRED_SINK="${DEFAULT_SINK}"
  fi
elif [[ -n "${DEFAULT_SINK}" && "${DEFAULT_SINK}" == *usb* ]]; then
  PREFERRED_SINK="${DEFAULT_SINK}"
elif [[ -n "${USB_SINK}" ]]; then
  PREFERRED_SINK="${USB_SINK}"
elif alsa_playback_available; then
  FORCE_ALSA_PLAYBACK=1
else
  PREFERRED_SINK="${DEFAULT_SINK}"
fi

ESPEAK_BIN="$(command -v espeak-ng || command -v espeak)"

normalize_fixed_reply() {
  local raw="$1"
  case "${raw}" in
    "我在，请说"|"我在，请讲")
      echo "wo zai, qing shuo"
      ;;
    "好的，已经把灯调成红色。")
      echo "hao de, yi jing ba deng tiao cheng hong se"
      ;;
    "好的，已经把灯调成蓝色。")
      echo "hao de, yi jing ba deng tiao cheng lan se"
      ;;
    "好的，已经把灯调成绿色。")
      echo "hao de, yi jing ba deng tiao cheng lu se"
      ;;
    "好的，已经把灯调成黄色。")
      echo "hao de, yi jing ba deng tiao cheng huang se"
      ;;
    "好的，已经关闭灯光。")
      echo "hao de, yi jing guan bi deng guang"
      ;;
    "好的，我来挥手。")
      echo "hao de, wo lai hui shou"
      ;;
    "好的，我来握手。")
      echo "hao de, wo lai wo shou"
      ;;
    "好的，我来鼓掌。")
      echo "hao de, wo lai gu zhang"
      ;;
    "好的，我来击掌。")
      echo "hao de, wo lai ji zhang"
      ;;
    "好的，我来比心。")
      echo "hao de, wo lai bi xin"
      ;;
    *)
      echo "${raw}"
      ;;
  esac
}

EDGE_TTS_TEXT="${TEXT}"
FALLBACK_TEXT="$(normalize_fixed_reply "${TEXT}")"
VOICE="default"
SPEED="${OM1_TTS_SPEED:-145}"
AMPLITUDE="${OM1_TTS_AMPLITUDE:-180}"
PITCH="${OM1_TTS_PITCH:-55}"

VOICE="$(python3 - "${EDGE_TTS_TEXT}" "${TEXT}" <<'PY'
import sys

edge_tts_text = sys.argv[1]
raw_text = sys.argv[2]

def has_han(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)

if has_han(edge_tts_text):
    if any(ch in raw_text for ch in "咩佢哋喺冇嘅"):
        print("zh-yue")
    else:
        print("zh")
else:
    print("default")
PY
)"

resolve_playback_command() {
  local requested="${OM1_TTS_PLAYBACK_COMMAND:-}"
  if [[ -n "${requested}" ]] && command -v "${requested}" >/dev/null 2>&1; then
    printf '%s\n' "${requested}"
    return 0
  fi
  local candidate
  for candidate in mpg123 ffplay mpv gst-play-1.0 play; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  printf '\n'
}

resolve_paplay_decoder() {
  local candidate
  if ! command -v paplay >/dev/null 2>&1; then
    printf '\n'
    return 0
  fi
  for candidate in ffmpeg mpg123; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  printf '\n'
}

decode_to_wav() {
  local decoder="$1"
  local audio_path="$2"
  local wav_path="$3"
  case "${decoder}" in
    ffmpeg)
      "${decoder}" -nostdin -loglevel error -y -i "${audio_path}" "${wav_path}"
      ;;
    mpg123)
      "${decoder}" -q -w "${wav_path}" "${audio_path}"
      ;;
    *)
      return 1
      ;;
  esac
}

play_wav_via_alsa() {
  local wav_path="$1"
  if [[ "${TTS_PREWARM_ONLY}" == "1" ]]; then
    debug_log "prewarm_only=1 alsa_device=${ALSA_PLAYBACK_DEVICE}"
    return 0
  fi
  aplay -q -D "${ALSA_PLAYBACK_DEVICE}" "${wav_path}"
}

play_audio_via_paplay() {
  local audio_path="$1"
  local decoder="$2"
  if [[ "${TTS_PREWARM_ONLY}" == "1" ]]; then
    debug_log "prewarm_only=1 decoder=${decoder} sink=${PREFERRED_SINK:-default}"
    return 0
  fi
  local temp_wav
  temp_wav="$(mktemp --suffix=.wav /tmp/om1-edge-tts-XXXXXX)"
  if ! decode_to_wav "${decoder}" "${audio_path}" "${temp_wav}"; then
    rm -f "${temp_wav}"
    return 1
  fi
  local play_rc=0
  if [[ "${FORCE_ALSA_PLAYBACK}" == "1" ]]; then
    play_wav_via_alsa "${temp_wav}" || play_rc=$?
  elif [[ -n "${PREFERRED_SINK}" ]]; then
    paplay --device="${PREFERRED_SINK}" --volume=65536 --stream-name="om1-local-reply" "${temp_wav}" || play_rc=$?
  else
    paplay --volume=65536 --stream-name="om1-local-reply" "${temp_wav}" || play_rc=$?
  fi
  if [[ "${play_rc}" != "0" && "${FORCE_ALSA_PLAYBACK}" != "1" ]] && alsa_playback_available; then
    debug_log "paplay_failed_rc=${play_rc} fallback=alsa device=${ALSA_PLAYBACK_DEVICE}"
    play_wav_via_alsa "${temp_wav}" || play_rc=$?
  fi
  rm -f "${temp_wav}"
  return "${play_rc}"
}

play_audio_file() {
  local audio_path="$1"
  local player="$2"
  if [[ "${TTS_PREWARM_ONLY}" == "1" ]]; then
    debug_log "prewarm_only=1 player=${player} sink=${PREFERRED_SINK:-default}"
    return 0
  fi
  case "${player}" in
    mpg123)
      "${player}" -q "${audio_path}"
      ;;
    ffplay)
      "${player}" -nodisp -autoexit -loglevel error "${audio_path}"
      ;;
    mpv)
      "${player}" --no-video --really-quiet "${audio_path}"
      ;;
    play)
      "${player}" -q "${audio_path}"
      ;;
    gst-play-1.0)
      "${player}" --quiet "${audio_path}"
      ;;
    *)
      return 1
      ;;
  esac
}

run_edge_tts() {
  local language="$1"
  local voice=""
  case "${language}" in
    zh)
      voice="${EDGE_TTS_ZH_VOICE}"
      ;;
    default)
      voice="${EDGE_TTS_EN_VOICE}"
      ;;
    *)
      return 1
      ;;
  esac
  if [[ ! -x "${EDGE_TTS_PYTHON}" ]]; then
    return 1
  fi
  local temp_audio
  temp_audio="$(mktemp --suffix=.mp3 /tmp/om1-edge-tts-XXXXXX)"
  if ! timeout "${EDGE_TTS_TIMEOUT_S}" "${EDGE_TTS_PYTHON}" - "${EDGE_TTS_TEXT}" "${voice}" "${EDGE_TTS_RATE}" "${EDGE_TTS_VOLUME}" "${EDGE_TTS_PITCH}" "${temp_audio}" <<'PY'
import asyncio
import sys

text, voice, rate, volume, pitch, output_path = sys.argv[1:7]

async def main() -> None:
    import edge_tts
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        volume=volume,
        pitch=pitch,
    )
    await communicate.save(output_path)

asyncio.run(main())
PY
  then
    rm -f "${temp_audio}"
    return 1
  fi
  local decoder
  decoder="$(resolve_paplay_decoder)"
  local play_rc=0
  if [[ -n "${decoder}" ]]; then
    debug_log "backend=edge_tts voice=${voice} sink=${PREFERRED_SINK:-default} force_alsa=${FORCE_ALSA_PLAYBACK} decoder=${decoder}"
    play_audio_via_paplay "${temp_audio}" "${decoder}" || play_rc=$?
  else
    local player
    player="$(resolve_playback_command)"
    if [[ -z "${player}" ]]; then
      rm -f "${temp_audio}"
      return 1
    fi
    debug_log "backend=edge_tts voice=${voice} sink=${PREFERRED_SINK:-default} force_alsa=${FORCE_ALSA_PLAYBACK} player=${player}"
    if [[ -n "${PREFERRED_SINK}" ]]; then
      PULSE_SINK="${PREFERRED_SINK}" play_audio_file "${temp_audio}" "${player}" || play_rc=$?
    else
      play_audio_file "${temp_audio}" "${player}" || play_rc=$?
    fi
  fi
  rm -f "${temp_audio}"
  return "${play_rc}"
}

ESPEAK_ARGS=(
  "-a" "${AMPLITUDE}"
  "-p" "${PITCH}"
  "-s" "${SPEED}"
)

if [[ "${VOICE}" != "default" ]]; then
  ESPEAK_ARGS+=("-v" "${VOICE}")
fi

if [[ "${VOICE}" == "zh" || "${VOICE}" == "default" ]]; then
  if run_edge_tts "${VOICE}"; then
    exit 0
  fi
fi

if [[ -z "${ESPEAK_BIN}" ]]; then
  echo "No TTS backend found" >&2
  exit 1
fi

if [[ "${TTS_PREWARM_ONLY}" == "1" ]]; then
  debug_log "backend=espeak-prewarm voice=${VOICE} sink=${PREFERRED_SINK:-default} force_alsa=${FORCE_ALSA_PLAYBACK} text=${FALLBACK_TEXT}"
  exit 0
fi

TEMP_WAV="$(mktemp --suffix=.wav /tmp/om1-espeak-XXXXXX)"
trap 'rm -f "${TEMP_WAV}"' EXIT
"${ESPEAK_BIN}" "${ESPEAK_ARGS[@]}" --stdout "${FALLBACK_TEXT}" > "${TEMP_WAV}"
debug_log "backend=espeak voice=${VOICE} sink=${PREFERRED_SINK:-default} force_alsa=${FORCE_ALSA_PLAYBACK} text=${FALLBACK_TEXT}"
if [[ "${FORCE_ALSA_PLAYBACK}" == "1" ]]; then
  play_wav_via_alsa "${TEMP_WAV}"
elif [[ -n "${PREFERRED_SINK}" ]]; then
  paplay --device="${PREFERRED_SINK}" --volume=65536 --stream-name="om1-local-reply" "${TEMP_WAV}" || {
    if alsa_playback_available; then
      debug_log "paplay_failed fallback=alsa device=${ALSA_PLAYBACK_DEVICE}"
      play_wav_via_alsa "${TEMP_WAV}"
    else
      exit 1
    fi
  }
else
  paplay --volume=65536 --stream-name="om1-local-reply" "${TEMP_WAV}" || {
    if alsa_playback_available; then
      debug_log "paplay_failed fallback=alsa device=${ALSA_PLAYBACK_DEVICE}"
      play_wav_via_alsa "${TEMP_WAV}"
    else
      exit 1
    fi
  }
fi
